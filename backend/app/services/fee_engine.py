"""The fee stack a channel charges on one sale (task T070).

What this module replaces: ``SalesChannel.calculate_platform_fee``, a single
percentage plus a single fixed amount. A real marketplace charges a transaction
fee on the item *plus the shipping it collected*, a payment processor charges
its own percentage plus a fixed amount on the whole order, a regulatory fee
lands on the item alone, a listing fee is charged whether or not anything sold,
and some of those are capped. One percentage could express one of them, which
is why every margin this system reported was wrong by the other four.

Three rules this engine keeps, each of which is a way the model is usually got
wrong (research.md D9):

1. **No fee is ever charged on another fee.** Every basis is an amount or a
   count taken from the order. Rule order therefore cannot change any total --
   it decides presentation and which clamp is attributed where, nothing more.
2. **Shipping revenue is never netted before fees.** A fee on
   ``item_plus_shipping`` is charged on what the customer actually paid for
   shipping, not on what is left after postage (FR-023).
3. **An expectation is labelled as one.** ``incidence_pct`` scales a *planning*
   figure, is flagged ``is_expected``, and never touches a recorded actual
   (FR-029, FR-041e).

**Rounding.** Each charge carries both an exact amount and a presentation
amount rounded to the cent. The margin chain in :mod:`app.services.costing`
sums the exact ones and rounds once; the itemised list an operator reads shows
the rounded ones. That is the opposite boundary from the cost breakdown, which
sums *rounded* lines so that an operator can add them up, and the difference is
deliberate: a cost breakdown is a list that must total, while a fee stack is
one step inside an arithmetic chain whose end is a price. Rounding the stack
early moves the margin by a cent, and the acceptance case pins which of the two
the spec depends on.

All arithmetic is :class:`~decimal.Decimal`. Constitution IV, enforced by
``tests/unit/pricing/test_no_float_in_money_paths.py``.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Optional, Sequence

from app.core import clock
from app.models.fee_rule import COUNT_BASES, FEE_BASES, PERIODIC_BASES

if TYPE_CHECKING:
    from app.models.fee_rule import FeeRule
    from app.models.sales_channel import SalesChannel

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")


class FeeRuleInvalid(ValueError):
    """Raised when a rule could not be charged as written.

    A validation failure rather than a server error: the operator can correct
    the rule and save again, so the endpoints turn it into a ``422``.
    """


@dataclass(frozen=True)
class OrderContext:
    """The amounts and counts a fee stack is computed from.

    Every amount here is **tax-exclusive** (FR-028a). Where a recorded figure
    arrived tax-inclusive, as a marketplace statement usually shows it,
    :func:`tax_exclusive_amount` derives the exclusive figure and the margin
    path reports what it derived (FR-028e) rather than leaving the reader to
    work it out.
    """

    #: The item lines, tax-exclusive and before any fee.
    item_subtotal: Decimal

    #: Shipping *revenue* charged to the customer -- never postage paid.
    shipping_revenue: Decimal = ZERO

    #: Units on the line, which a ``per_unit_sold`` rule multiplies by.
    quantity: int = 1

    #: Anything else the customer paid that is neither item nor shipping, such
    #: as gift wrap. Part of ``order_total`` and of nothing else.
    extras: Decimal = ZERO

    #: Live listings, for the periodic view. A sale's stack never charges these.
    listings: int = 1

    #: Months the periodic view covers, for a ``per_month`` rule.
    months: int = 1

    #: Sales tax taken from the customer. Present so one context can describe a
    #: whole sale, and deliberately absent from every basis below (FR-028c).
    sales_tax_collected: Decimal = ZERO

    @property
    def item_plus_shipping(self) -> Decimal:
        """FR-023: the item plus what the customer paid for shipping."""
        return self.item_subtotal + self.shipping_revenue

    @property
    def order_total(self) -> Decimal:
        """What the customer paid, tax-exclusive and before any fee.

        Item plus shipping plus extras, and never another fee or the tax
        (research.md D9).
        """
        return self.item_subtotal + self.shipping_revenue + self.extras


@dataclass(frozen=True)
class FeeCharge:
    """One fee as it would be or was charged, with everything behind it.

    ``amount_exact`` is the unrounded figure the margin chain consumes;
    ``amount`` is the same figure rounded to the cent for presentation. Both
    are carried because reporting only the rounded one makes a stack of five
    fees drift from the statement it predicts, while reporting only the exact
    one quotes an operator a fee to four decimal places.
    """

    name: str
    basis: str
    amount: Decimal
    amount_exact: Decimal

    #: ``"min"`` or ``"max"`` when a clamp changed the amount, else ``None``.
    #: FR-021c: a capped fee must never read as a miscalculated one.
    clamp_applied: Optional[str] = None

    #: True when ``incidence_pct`` scaled this figure, so it is what the
    #: channel charges on average rather than what it charged here (FR-029).
    is_expected: bool = False

    # The inputs, kept so a figure is explainable without recomputing it
    # (FR-018).
    rate_pct: Decimal = ZERO
    fixed_amount: Decimal = ZERO
    basis_amount: Decimal = ZERO
    incidence_pct: Optional[Decimal] = None
    rule_id: Optional[object] = None

    @property
    def clamp_bound(self) -> bool:
        return self.clamp_applied is not None


@dataclass(frozen=True)
class FeeStack:
    """Every fee charged on one sale, plus the periodic ones that were not."""

    charges: list[FeeCharge] = field(default_factory=list)

    #: Rules absorbed over a period rather than charged on a sale (FR-025).
    #: Reported, never silently dropped: a listing fee an operator configured
    #: and then never saw again is a cost they stop believing in.
    periodic: list[FeeCharge] = field(default_factory=list)

    @property
    def total_exact(self) -> Decimal:
        """The unrounded total, which the margin chain uses."""
        return sum((charge.amount_exact for charge in self.charges), ZERO)

    @property
    def total(self) -> Decimal:
        """The total, rounded once to the cent."""
        return self.total_exact.quantize(CENT)

    @property
    def periodic_total_exact(self) -> Decimal:
        return sum((charge.amount_exact for charge in self.periodic), ZERO)

    @property
    def periodic_total(self) -> Decimal:
        return self.periodic_total_exact.quantize(CENT)

    @property
    def bound_clamps(self) -> list[str]:
        """Names of the fees whose cap or floor bound (FR-032a)."""
        return [charge.name for charge in self.charges if charge.clamp_bound]

    @property
    def variable_rate_pct(self) -> Decimal:
        """Total percentage charged on an amount that moves with price.

        The solver needs this: it is the part of the stack that scales with the
        price it is solving for. A clamped rule has stopped scaling, so it is
        excluded here and moved into the fixed bucket by the caller
        (research.md D10).
        """
        return sum(
            (
                charge.rate_pct
                for charge in self.charges
                if charge.basis not in COUNT_BASES and not charge.clamp_bound
            ),
            ZERO,
        )

    def named(self, name: str) -> Optional[FeeCharge]:
        for charge in self.charges:
            if charge.name == name:
                return charge
        return None


@dataclass(frozen=True)
class TaxTreatment:
    """What tax was collected, and whether it was taken out of the amounts.

    Carried alongside the context rather than recomputed by each reader, which
    is the point: the tax comes out of a recorded figure exactly once, before
    any fee is charged on it. An earlier draft of this module let the fee
    engine charge an inclusive amount while the margin path divided by an
    exclusive one, which is the same figure derived twice and is the class of
    defect this feature exists to remove.
    """

    #: Tax taken from the customer, whoever remits it.
    collected: Decimal = ZERO

    #: True when the amounts handed in were tax-inclusive and the exclusive
    #: figures were derived from them here (FR-028e).
    derived_from_inclusive: bool = False

    #: How much was actually removed from the revenue amounts. Equal to
    #: ``collected`` when the amounts were inclusive, and zero otherwise.
    removed: Decimal = ZERO


def tax_exclusive_amount(
    recorded: Decimal,
    sales_tax: Decimal,
    *,
    tax_inclusive: bool,
) -> Decimal:
    """The tax-exclusive figure behind a recorded amount (FR-028a, FR-028e).

    A marketplace statement typically shows the gross the customer paid. Margin
    is always computed on the exclusive amount, under every basis and on every
    channel, so the subtraction happens once -- here -- and the margin path
    reports the figure it derived, so a reconciliation against the statement
    does not have to redo it by hand.
    """
    if not tax_inclusive:
        return recorded
    return recorded - sales_tax


def exclusive_context(
    *,
    item_subtotal: Decimal,
    shipping_revenue: Decimal = ZERO,
    extras: Decimal = ZERO,
    sales_tax_collected: Decimal = ZERO,
    tax_inclusive: bool = False,
    quantity: int = 1,
    listings: int = 1,
    months: int = 1,
) -> tuple[OrderContext, TaxTreatment]:
    """Build the one tax-exclusive context the whole chain reads (FR-028a).

    Both the fee stack and the margin are computed from the context this
    returns, so no fee is ever charged on an amount the margin then treats as
    smaller. The tax comes off here or nowhere.

    Where the amounts arrive inclusive, the tax is removed **pro rata** across
    the item, the shipping and any extras the customer paid. Pro rata is a
    choice rather than a derivation: a marketplace statement rarely splits its
    tax, and attributing all of it to the item would understate the item's
    margin by the shipping share. The property that matters either way is that
    the exclusive components still sum to the exclusive total.
    """
    item = Decimal(str(item_subtotal))
    shipping = Decimal(str(shipping_revenue))
    other = Decimal(str(extras))
    tax = Decimal(str(sales_tax_collected))
    gross = item + shipping + other

    if tax_inclusive and tax > ZERO and gross > ZERO:
        share = tax_exclusive_amount(gross, tax, tax_inclusive=True) / gross
        item = item * share
        shipping = shipping * share
        other = other * share
        treatment = TaxTreatment(collected=tax, derived_from_inclusive=True, removed=tax)
    else:
        treatment = TaxTreatment(collected=tax, derived_from_inclusive=False, removed=ZERO)

    context = OrderContext(
        item_subtotal=item,
        shipping_revenue=shipping,
        extras=other,
        quantity=quantity,
        listings=listings,
        months=months,
        sales_tax_collected=tax,
    )
    return context, treatment


def validate_rule(
    *,
    basis: str,
    rate_pct: Optional[Decimal] = None,
    min_amount: Optional[Decimal] = None,
    max_amount: Optional[Decimal] = None,
    incidence_pct: Optional[Decimal] = None,
) -> None:
    """Refuse a rule that could not be charged as written.

    Called at save time rather than at compute time: a rule stored with a floor
    above its cap would otherwise charge whichever the code applied last, and
    which one that is would be a property of the implementation (FR-021d).
    """
    if basis not in FEE_BASES:
        raise FeeRuleInvalid(f"basis must be one of {FEE_BASES}, not {basis!r}")

    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise FeeRuleInvalid(
            f"min_amount {min_amount} exceeds max_amount {max_amount}: a floor above a "
            "cap is a rule no amount can satisfy (FR-021d)"
        )

    if rate_pct is not None and rate_pct < ZERO:
        raise FeeRuleInvalid("rate_pct cannot be negative")

    if rate_pct is not None and rate_pct > ZERO and basis in COUNT_BASES:
        # A percentage of a count is not an amount. Refusing it is the only
        # honest option: charging zero would hide the operator's mistake and
        # charging the rate against the count would invent a currency figure
        # out of a quantity.
        raise FeeRuleInvalid(
            f"basis {basis!r} is a count, not an amount, so a rate of {rate_pct} has no "
            "meaning; put the charge in fixed_amount"
        )

    if incidence_pct is not None and not (ZERO <= incidence_pct <= HUNDRED):
        raise FeeRuleInvalid(
            f"incidence_pct is a share of orders and must be between 0 and 100, not {incidence_pct}"
        )


def _basis_amount(basis: str, context: OrderContext) -> Decimal:
    """The amount or count a rule on ``basis`` is charged against.

    Every branch reads only from the order. There is deliberately no branch
    that reads another fee: fee-on-fee is inexpressible rather than merely
    discouraged (research.md D9).
    """
    if basis == "item_subtotal":
        return context.item_subtotal
    if basis == "item_plus_shipping":
        return context.item_plus_shipping
    if basis == "order_total":
        return context.order_total
    if basis == "per_order":
        return Decimal(1)
    if basis == "per_unit_sold":
        return Decimal(context.quantity)
    if basis == "per_listing":
        return Decimal(context.listings)
    if basis == "per_month":
        return Decimal(context.months)
    raise FeeRuleInvalid(f"unknown fee basis {basis!r}")


def _charge_for(rule: "FeeRule", context: OrderContext) -> FeeCharge:
    """Compute one rule's charge: rate, fixed, clamp, then incidence.

    The order of the last two matters. A clamp applies to what the rule
    actually charges when it lands (FR-021b), so it binds first; incidence then
    scales that capped amount into what the channel charges on average
    (FR-029). Scaling first and clamping afterwards would cap an average rather
    than a charge, and would report a cap as binding on orders where it did
    not.
    """
    basis = rule.basis
    basis_amount = _basis_amount(basis, context)
    rate = Decimal(str(rule.rate_pct or ZERO))
    fixed = Decimal(str(rule.fixed_amount or ZERO))

    if basis in COUNT_BASES:
        # A count basis charges its fixed amount once per thing counted. Its
        # rate is refused at save time, so nothing is silently ignored here.
        amount = fixed * basis_amount
    else:
        amount = basis_amount * rate / HUNDRED + fixed

    clamp: Optional[str] = None
    maximum = rule.max_amount
    minimum = rule.min_amount
    if maximum is not None and amount > Decimal(str(maximum)):
        amount = Decimal(str(maximum))
        clamp = "max"
    elif minimum is not None and amount < Decimal(str(minimum)):
        amount = Decimal(str(minimum))
        clamp = "min"

    incidence = rule.incidence_pct
    is_expected = False
    if incidence is not None:
        incidence = Decimal(str(incidence))
        if incidence != HUNDRED:
            amount = amount * incidence / HUNDRED
            is_expected = True
    else:
        incidence = None

    return FeeCharge(
        name=rule.name,
        basis=basis,
        amount=amount.quantize(CENT),
        amount_exact=amount,
        clamp_applied=clamp,
        is_expected=is_expected,
        rate_pct=rate,
        fixed_amount=fixed,
        basis_amount=basis_amount,
        incidence_pct=incidence,
        rule_id=getattr(rule, "id", None),
    )


def rules_in_effect(
    rules: Sequence["FeeRule"],
    as_of: date,
) -> list["FeeRule"]:
    """The rules in force on ``as_of``, in ``sort_order``.

    Sorted by ``sort_order`` then by name, so two channels configured the same
    way present their fees the same way and a tie is resolved by something
    stable rather than by insertion order.
    """
    live = [rule for rule in rules if rule.applies_on(as_of)]
    return sorted(live, key=lambda rule: (rule.sort_order, rule.name))


def compute(
    channel: "SalesChannel",
    context: OrderContext,
    as_of: Optional[date] = None,
    *,
    rules: Optional[Sequence["FeeRule"]] = None,
    include_periodic: bool = False,
) -> FeeStack:
    """The fees ``channel`` charges on the sale ``context`` describes.

    ``rules`` overrides the channel's own list, which is what the legacy
    comparison profile and the scenario service both need: the same engine run
    against a different rule set, rather than a second engine (research.md D7).

    ``include_periodic`` puts per-listing and per-month rules into the charges
    rather than into ``periodic``. A single sale never carries them -- they are
    absorbed over a period's actual order volume by
    :mod:`app.services.channel_pnl` (FR-025) -- but the channel P&L view wants
    them charged.
    """
    reference = as_of or clock.today()
    source = rules if rules is not None else (channel.fee_rules or [])

    charges: list[FeeCharge] = []
    periodic: list[FeeCharge] = []
    for rule in rules_in_effect(source, reference):
        charge = _charge_for(rule, context)
        if rule.basis in PERIODIC_BASES and not include_periodic:
            periodic.append(charge)
        else:
            charges.append(charge)

    return FeeStack(charges=charges, periodic=periodic)
