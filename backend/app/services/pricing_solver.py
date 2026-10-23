"""The price that achieves a target margin (task T087).

What makes this non-trivial: the percentage fees a marketplace charges are
charged on the price being solved for. Pricing at cost plus a markup and then
subtracting the fees gives a price whose margin, once the fees land on the
*higher* number, is lower than the one asked for. The error is not small -- at
a 12.5% fee stack and a 35% target it is several points of margin -- and it is
the error an operator makes with a calculator, which is the reason this
endpoint exists.

**Why a closed form and not a root-finder.** With no clamp binding, margin is
linear in price under all three bases, so the required price has an exact
algebraic answer per basis. A bisection would land on the same number and
could not explain itself; FR-034 requires the solver to report the inputs that
produced its answer, and an operator asking "why that price" deserves the
arithmetic rather than "the search converged there". Caps break linearity, so
the loop below solves, sees which clamps bind, moves each bound fee into the
constant bucket and re-solves -- at most one pass per capped rule, which makes
it bounded and deterministic rather than iterative in the fixed-point sense
(research.md D10).

**The one shared arithmetic.** :func:`linearise` writes each rule as a rate on
the price plus a constant. It deliberately does *not* reimplement the fee
arithmetic: ``tests/unit/pricing/test_solver.py`` asserts that the line it
produces agrees with :func:`app.services.fee_engine.compute` at arbitrary
prices, so the two cannot drift. A solver with its own private notion of what
a fee costs is the second cost implementation this whole feature exists to
remove (Constitution III).

All arithmetic is :class:`~decimal.Decimal` (Constitution IV), enforced by
``tests/unit/pricing/test_no_float_in_money_paths.py``.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import TYPE_CHECKING, Optional, Sequence

from app.observability.tracing import traced
from app.core import clock
from app.models.fee_rule import COUNT_BASES, PERIODIC_BASES
from app.services import fee_engine
from app.services.channel_economics import ChannelEconomics, channel_defaults
from app.services.costing import (
    MARGIN_BASIS_LABELS,
    CostingService,
    MarginResult,
    resolve_margin_basis,
)
from app.services.fee_engine import FeeStack, OrderContext, TaxTreatment

if TYPE_CHECKING:
    from app.models.fee_rule import FeeRule
    from app.models.sales_channel import SalesChannel
    from app.services.pricing_policy import CostPolicy

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")

#: The precision the raw solved price is reported at. Four decimal places,
#: because the figure is an intermediate the rounding rule then acts on, and
#: quantising it to the cent first would make the reported adjustment wrong by
#: whatever the first rounding threw away.
RAW_PRECISION = Decimal("0.0001")

#: Rounding rules an operator may configure (FR-033). Every one rounds **up**:
#: rounding down would return a price whose margin is below the target the
#: operator asked for, which is the one thing the solver must not quietly do.
#: The adjustment is reported either way, so a rounding that costs the operator
#: a cent of margin is a decision they can see rather than one hidden in a
#: quantize call.
ROUNDING_RULES: tuple[str, ...] = (
    "nearest_cent",
    "nearest_five_cents",
    "nearest_dollar",
    "psychological_99",
    "psychological_95",
)

DEFAULT_ROUNDING_RULE = "nearest_cent"


@dataclass(frozen=True)
class LinearFee:
    """One fee written as ``rate × price + constant``.

    ``pinned`` marks a fee whose clamp bound, so it has stopped scaling with
    price: its rate is zero and its whole amount sits in ``constant``. That is
    the move that makes the clamp loop terminate (research.md D10).
    """

    name: str
    basis: str
    rate: Decimal
    constant: Decimal
    pinned: bool = False

    def at(self, price: Decimal) -> Decimal:
        return self.rate * price + self.constant


@dataclass(frozen=True)
class PriceAdjustment:
    """One deliberate move away from the solved price, named (FR-033).

    A rounding rule and a free-shipping threshold both change the answer. Both
    are the operator's own policy, so neither is a correction -- but a price
    that silently differs from the one the arithmetic produced is a price
    nobody can check, so each move is reported with where it came from and
    where it went.
    """

    key: str
    label: str
    from_price: Decimal
    to_price: Decimal

    @property
    def delta(self) -> Decimal:
        return self.to_price - self.from_price


@dataclass(frozen=True)
class SolveResult:
    """The price, what moved it, and everything behind it (FR-032 -- FR-035)."""

    achievable: bool
    target_margin_pct: Decimal
    margin_basis: str
    margin_basis_label: str

    #: The closed-form answer before any rounding or snap, or ``None`` when no
    #: price achieves the target.
    raw_price: Optional[Decimal] = None

    #: The price to charge: the raw price with every adjustment applied.
    price: Optional[Decimal] = None

    #: In the order they were applied (FR-033).
    adjustments: list[PriceAdjustment] = field(default_factory=list)

    #: Names of the fees whose cap or floor bound at the price returned
    #: (FR-032a). A capped fee must never read as a miscalculated one.
    binding_clamps: list[str] = field(default_factory=list)

    #: The margin actually achieved at ``price``. It differs from the target by
    #: whatever the rounding moved, and reporting it is the only way an
    #: operator can see that a psychological rounding rule bought them half a
    #: point of margin.
    margin_pct_at_price: Optional[Decimal] = None
    profit_at_price: Optional[Decimal] = None

    #: ``"unachievable"`` when no price exists (FR-035).
    reason: Optional[str] = None

    #: Which constraint made it unachievable, in words (FR-035).
    binding_constraint: Optional[str] = None

    #: Every figure the answer was computed from (FR-034).
    inputs: dict[str, object] = field(default_factory=dict)

    #: How many closed-form solves it took. One when no clamp bound.
    passes: int = 0

    @property
    def price_display(self) -> Optional[Decimal]:
        if self.price is None:
            return None
        return self.price.quantize(CENT)


@dataclass(frozen=True)
class LadderRung:
    """One price point and what it earns, for the operator to choose from.

    FR-007 forbids storing or computing a market judgement as a single number.
    What a customer will pay is not knowable from the data this system holds,
    so the system reports margin across a range and the choice stays with the
    person who knows the market. Nothing here is written anywhere.
    """

    price: Decimal
    margin_pct: Optional[Decimal]
    profit: Decimal
    margin_basis: str
    profit_per_machine_hour: Optional[Decimal] = None


def _incidence_factor(rule: "FeeRule") -> Decimal:
    """``incidence_pct`` as a multiplier, or one when it is unset.

    Matches :func:`app.services.fee_engine._charge_for`: incidence scales the
    whole charge, rate and fixed part alike, and an unset incidence scales
    nothing.
    """
    incidence = getattr(rule, "incidence_pct", None)
    if incidence is None:
        return ONE
    return Decimal(str(incidence)) / HUNDRED


def _basis_offset(basis: str, shipping_revenue: Decimal, extras: Decimal) -> Decimal:
    """The part of a rule's basis that does **not** move with the item price.

    ``item_subtotal`` is the price itself; ``item_plus_shipping`` adds the
    shipping the customer paid (FR-023); ``order_total`` adds the extras too.
    No basis reads another fee, which is why a fee stack is linear in price at
    all (research.md D9).
    """
    if basis == "item_subtotal":
        return ZERO
    if basis == "item_plus_shipping":
        return shipping_revenue
    if basis == "order_total":
        return shipping_revenue + extras
    raise ValueError(f"basis {basis!r} does not scale with price")


def linearise(
    rules: Sequence["FeeRule"],
    *,
    as_of: date,
    shipping_revenue: Decimal = ZERO,
    extras: Decimal = ZERO,
    quantity: int = 1,
    pinned: Optional[dict[str, Decimal]] = None,
) -> list[LinearFee]:
    """Write each rule in force as a rate on the price plus a constant.

    Periodic rules are excluded, exactly as :func:`fee_engine.compute` excludes
    them: a listing fee is absorbed over a period's order volume (FR-025) and
    charging it on one sale would price that sale as though it carried the
    month.

    ``pinned`` maps a fee's name to the amount its clamp holds it at. A pinned
    fee contributes a constant and no rate, which is what the clamp loop needs.
    """
    pinned = pinned or {}
    live = fee_engine.rules_in_effect(rules, as_of)
    out: list[LinearFee] = []

    for rule in live:
        if rule.basis in PERIODIC_BASES:
            continue

        name = rule.name
        if name in pinned:
            out.append(
                LinearFee(
                    name=name,
                    basis=rule.basis,
                    rate=ZERO,
                    constant=pinned[name],
                    pinned=True,
                )
            )
            continue

        incidence = _incidence_factor(rule)
        fixed = Decimal(str(rule.fixed_amount or ZERO))

        if rule.basis in COUNT_BASES:
            count = Decimal(quantity) if rule.basis == "per_unit_sold" else ONE
            out.append(
                LinearFee(
                    name=name,
                    basis=rule.basis,
                    rate=ZERO,
                    constant=fixed * count * incidence,
                )
            )
            continue

        rate = Decimal(str(rule.rate_pct or ZERO)) / HUNDRED
        offset = _basis_offset(rule.basis, shipping_revenue, extras)
        out.append(
            LinearFee(
                name=name,
                basis=rule.basis,
                rate=rate * incidence,
                constant=(offset * rate + fixed) * incidence,
            )
        )

    return out


@dataclass(frozen=True)
class _Coefficients:
    """``profit(P) = slope × P + intercept``, plus what the bases need.

    Reducing the whole chain to two numbers is what makes the answer exact and
    explainable: every basis below is one rearrangement of this line.
    """

    slope: Decimal
    intercept: Decimal

    #: Total rate charged on an amount that moves with price. Needed by the
    #: net-revenue basis, whose denominator shrinks as the fees grow.
    fee_rate: Decimal
    fee_constant: Decimal

    shipping_revenue: Decimal
    deduction_rate: Decimal


def _coefficients(
    fees: Sequence[LinearFee],
    *,
    make_cost: Decimal,
    postage_paid: Decimal,
    shipping_revenue: Decimal,
    deduction_rate: Decimal,
) -> _Coefficients:
    """Collapse the margin chain into one line in the price.

    The chain mirrors :meth:`app.services.costing.CostingService.margin` step
    for step -- fees on the gross, reserves on the customer total, then the
    make-cost and the postage -- because a solver that models the chain
    differently from the one that reports the margin returns a price whose
    margin, when the margin endpoint is asked, is not the one requested.
    """
    fee_rate = sum((fee.rate for fee in fees), ZERO)
    fee_constant = sum((fee.constant for fee in fees), ZERO)

    # profit(P) = (P + S)(1 - D) - (rate·P + const) - make_cost - postage
    slope = ONE - deduction_rate - fee_rate
    intercept = shipping_revenue * (ONE - deduction_rate) - fee_constant - make_cost - postage_paid
    return _Coefficients(
        slope=slope,
        intercept=intercept,
        fee_rate=fee_rate,
        fee_constant=fee_constant,
        shipping_revenue=shipping_revenue,
        deduction_rate=deduction_rate,
    )


def _solve_closed_form(
    coefficients: _Coefficients,
    *,
    basis: str,
    target: Decimal,
) -> tuple[Optional[Decimal], Optional[str]]:
    """The price at which profit equals ``target`` of the basis amount.

    One rearrangement per basis (research.md D10). Returns the price, or
    ``None`` with the binding constraint in words when the line and the target
    never meet at a positive price (FR-035).
    """
    slope = coefficients.slope
    intercept = coefficients.intercept
    shipping = coefficients.shipping_revenue

    if basis == "item_price":
        denominator = slope - target
        numerator = -intercept
        shape = "the item price"
    elif basis == "net_revenue":
        # The denominator itself shrinks with the fees, so the target is
        # charged against (1 - fee_rate) of the price.
        denominator = slope - target * (ONE - coefficients.fee_rate)
        numerator = target * (shipping - coefficients.fee_constant) - intercept
        shape = "net revenue after fees"
    else:
        denominator = slope - target
        numerator = target * shipping - intercept
        shape = "the total the customer paid"

    if denominator <= ZERO:
        return None, (
            f"a target of {(target * HUNDRED).quantize(Decimal('0.01'))}% of {shape} plus "
            f"{(coefficients.fee_rate * HUNDRED).quantize(Decimal('0.01'))}% of percentage fees "
            f"and {(coefficients.deduction_rate * HUNDRED).quantize(Decimal('0.01'))}% of "
            "reserves reaches or exceeds the whole amount, so no price leaves that margin "
            "behind -- every extra dollar of price is consumed by the percentages charged on it"
        )

    price = numerator / denominator
    if price <= ZERO:
        return None, (
            "the fixed costs and fees are already covered at a price of zero, so the target "
            f"margin is met at any price above {price.quantize(CENT)} -- there is no price to "
            "solve for"
        )
    return price, None


def _apply_rounding(price: Decimal, rule: Optional[str]) -> Optional[PriceAdjustment]:
    """Move the price onto the operator's rounding rule (FR-033).

    Always upward. A rule that rounded down would return a price whose margin
    is below the target the operator asked for, and the whole point of the
    solver is that the figure it returns is the one it promises.
    """
    name = rule or DEFAULT_ROUNDING_RULE
    if name not in ROUNDING_RULES:
        logger.warning(f"Unknown rounding rule {name!r}; rounding to the cent instead")
        name = DEFAULT_ROUNDING_RULE

    if name == "nearest_cent":
        rounded = price.quantize(CENT, rounding=ROUND_CEILING)
    elif name == "nearest_five_cents":
        rounded = (price / Decimal("0.05")).quantize(ONE, rounding=ROUND_CEILING) * Decimal("0.05")
    elif name == "nearest_dollar":
        rounded = price.quantize(ONE, rounding=ROUND_CEILING)
    else:
        tail = Decimal("0.99") if name == "psychological_99" else Decimal("0.95")
        whole = price.quantize(ONE, rounding=ROUND_CEILING) - ONE
        rounded = whole + tail
        while rounded < price:
            rounded += ONE

    rounded = rounded.quantize(CENT)
    if rounded == price.quantize(CENT) and rounded == price:
        return None
    return PriceAdjustment(
        key="rounding",
        label=f"Rounded by the {name.replace('_', ' ')} rule",
        from_price=price,
        to_price=rounded,
    )


def _apply_free_shipping_snap(
    price: Decimal,
    threshold: Optional[Decimal],
) -> Optional[PriceAdjustment]:
    """Lift a price to the channel's free-shipping threshold (FR-033).

    Only upward, and only when the price is below the threshold. The case it
    serves: the margin was solved on the assumption that the operator pays the
    postage, which on a channel with a threshold is only true once the order
    clears it. A price a dollar short of the threshold is priced as though
    shipping were free while the customer would in fact be charged for it.
    """
    if threshold is None:
        return None
    threshold = Decimal(str(threshold))
    if price >= threshold:
        return None
    return PriceAdjustment(
        key="free_shipping_snap",
        label=f"Snapped up to the free-shipping threshold of {threshold.quantize(CENT)}",
        from_price=price,
        to_price=threshold.quantize(CENT),
    )


def _clampable(rules: Sequence["FeeRule"]) -> int:
    """How many rules could clamp, which bounds the loop (research.md D10)."""
    return sum(
        1
        for rule in rules
        if getattr(rule, "min_amount", None) is not None
        or getattr(rule, "max_amount", None) is not None
    )


def _context_at(
    price: Decimal,
    *,
    shipping_revenue: Decimal,
    extras: Decimal,
    quantity: int,
) -> OrderContext:
    return OrderContext(
        item_subtotal=price,
        shipping_revenue=shipping_revenue,
        extras=extras,
        quantity=quantity,
    )


@traced("price.solve")
def solve(
    *,
    channel: "SalesChannel",
    make_cost: Decimal,
    target_margin_pct: Decimal,
    as_of: Optional[date] = None,
    rules: Optional[Sequence["FeeRule"]] = None,
    postage_paid: Decimal = ZERO,
    shipping_revenue: Decimal = ZERO,
    extras: Decimal = ZERO,
    quantity: int = 1,
    policy: Optional["CostPolicy"] = None,
    economics: Optional[ChannelEconomics] = None,
    margin_basis: Optional[str] = None,
    rounding_rule: Optional[str] = None,
    snap_to_free_shipping: bool = False,
) -> SolveResult:
    """The price that earns ``target_margin_pct`` on ``channel`` (FR-032).

    The loop: solve the closed form, compute the real fee stack at that price
    through :func:`fee_engine.compute`, and if a clamp bound that the line did
    not know about, pin that fee at the amount its clamp holds and solve again.
    Bounded by the number of rules that *could* clamp, so it cannot spin.

    The stack is recomputed through the fee engine rather than from the line,
    which is the point of checking at all: if the two ever disagreed, the
    answer would be a price whose margin the margin endpoint then disputes.

    ``snap_to_free_shipping`` is off by default because FR-033 makes the snap a
    MAY -- it is the operator's call whether a price should be dragged up to a
    threshold, and doing it unasked would quietly reprice a catalogue.
    """
    reference = as_of or clock.today()
    source = list(rules if rules is not None else (channel.fee_rules or []))
    target = Decimal(str(target_margin_pct)) / HUNDRED
    basis = resolve_margin_basis(policy, override=margin_basis)

    cost = Decimal(str(make_cost))
    postage = Decimal(str(postage_paid))
    shipping = Decimal(str(shipping_revenue))
    other = Decimal(str(extras))

    # The reserves, the rounding rule and the threshold are effective-dated
    # (FR-003, task T136): an input resolved by the caller for the date that
    # applies, not read off the channel row as it stands today. The fallback
    # keeps a stand-in without a session working.
    rates = economics if economics is not None else channel_defaults(channel)
    deduction_rate = rates.deduction_pct / HUNDRED

    effective_rounding = rounding_rule
    if effective_rounding is None:
        effective_rounding = rates.rounding_rule or (
            policy.rounding_rule if policy is not None else None
        )

    threshold = rates.free_shipping_threshold if snap_to_free_shipping else None

    inputs: dict[str, object] = {
        "make_cost": cost,
        "postage_paid": postage,
        "shipping_revenue": shipping,
        "extras": other,
        "quantity": quantity,
        "target_margin_pct": Decimal(str(target_margin_pct)),
        "margin_basis": basis,
        "expected_discount_pct": rates.expected_discount_pct,
        "expected_refund_pct": rates.expected_refund_pct,
        "rounding_rule": effective_rounding or DEFAULT_ROUNDING_RULE,
        "free_shipping_threshold": threshold,
        "as_of": reference,
    }

    pinned: dict[str, Decimal] = {}
    max_passes = _clampable(source) + 1
    price: Optional[Decimal] = None
    constraint: Optional[str] = None
    passes = 0
    coefficients: Optional[_Coefficients] = None

    for _ in range(max_passes):
        passes += 1
        fees = linearise(
            source,
            as_of=reference,
            shipping_revenue=shipping,
            extras=other,
            quantity=quantity,
            pinned=pinned,
        )
        coefficients = _coefficients(
            fees,
            make_cost=cost,
            postage_paid=postage,
            shipping_revenue=shipping,
            deduction_rate=deduction_rate,
        )
        price, constraint = _solve_closed_form(coefficients, basis=basis, target=target)
        if price is None:
            break

        stack = fee_engine.compute(
            channel,
            _context_at(price, shipping_revenue=shipping, extras=other, quantity=quantity),
            reference,
            rules=source,
        )
        newly_bound = {
            charge.name: charge.amount_exact
            for charge in stack.charges
            if charge.clamp_bound and charge.name not in pinned
        }
        if not newly_bound:
            break
        pinned.update(newly_bound)

    if price is None:
        inputs["fee_rate_pct"] = (
            (coefficients.fee_rate * HUNDRED) if coefficients is not None else ZERO
        )
        return SolveResult(
            achievable=False,
            target_margin_pct=Decimal(str(target_margin_pct)),
            margin_basis=basis,
            margin_basis_label=MARGIN_BASIS_LABELS[basis],
            reason="unachievable",
            binding_constraint=constraint,
            inputs=inputs,
            passes=passes,
        )

    assert coefficients is not None  # a solved price implies coefficients were built
    inputs["fee_rate_pct"] = coefficients.fee_rate * HUNDRED
    inputs["fee_constant"] = coefficients.fee_constant
    inputs["pinned_fees"] = dict(pinned)

    raw = price.quantize(RAW_PRECISION)

    adjustments: list[PriceAdjustment] = []
    final = price
    rounding_move = _apply_rounding(final, effective_rounding)
    if rounding_move is not None:
        adjustments.append(rounding_move)
        final = rounding_move.to_price
    else:
        final = final.quantize(CENT)

    snap = _apply_free_shipping_snap(final, threshold)
    if snap is not None:
        adjustments.append(snap)
        final = snap.to_price

    achieved = margin_at(
        final,
        channel=channel,
        make_cost=cost,
        as_of=reference,
        rules=source,
        postage_paid=postage,
        shipping_revenue=shipping,
        extras=other,
        quantity=quantity,
        policy=policy,
        economics=rates,
        margin_basis=basis,
    )

    return SolveResult(
        achievable=True,
        target_margin_pct=Decimal(str(target_margin_pct)),
        margin_basis=basis,
        margin_basis_label=MARGIN_BASIS_LABELS[basis],
        raw_price=raw,
        price=final,
        adjustments=adjustments,
        binding_clamps=sorted(pinned),
        margin_pct_at_price=achieved.margin_pct,
        profit_at_price=achieved.profit,
        inputs=inputs,
        passes=passes,
    )


def margin_at(
    price: Decimal,
    *,
    channel: "SalesChannel",
    make_cost: Decimal,
    as_of: Optional[date] = None,
    rules: Optional[Sequence["FeeRule"]] = None,
    postage_paid: Decimal = ZERO,
    shipping_revenue: Decimal = ZERO,
    extras: Decimal = ZERO,
    quantity: int = 1,
    machine_hours: Optional[Decimal] = None,
    policy: Optional["CostPolicy"] = None,
    economics: Optional[ChannelEconomics] = None,
    margin_basis: Optional[str] = None,
) -> MarginResult:
    """The margin at one price, through the ordinary margin path.

    Both the solver and the ladder report margins, and neither computes one
    itself: they ask :meth:`CostingService.margin`, so a figure the solver
    reports is the same figure the margin endpoint reports at that price. A
    second margin implementation here would be the defect this feature removed
    from the cost path, reintroduced one module along.
    """
    reference = as_of or clock.today()
    source = list(rules if rules is not None else (channel.fee_rules or []))
    context = _context_at(
        Decimal(str(price)),
        shipping_revenue=Decimal(str(shipping_revenue)),
        extras=Decimal(str(extras)),
        quantity=quantity,
    )
    stack: FeeStack = fee_engine.compute(channel, context, reference, rules=source)
    return CostingService.margin(
        context=context,
        make_cost=Decimal(str(make_cost)),
        channel=channel,
        fees=stack,
        policy=policy,
        economics=economics,
        tax=TaxTreatment(),
        postage_paid=Decimal(str(postage_paid)),
        margin_basis=margin_basis,
        machine_hours=machine_hours,
    )


@traced("price.ladder")
def ladder(
    *,
    channel: "SalesChannel",
    make_cost: Decimal,
    start: Decimal,
    stop: Decimal,
    step: Decimal,
    as_of: Optional[date] = None,
    rules: Optional[Sequence["FeeRule"]] = None,
    postage_paid: Decimal = ZERO,
    shipping_revenue: Decimal = ZERO,
    extras: Decimal = ZERO,
    quantity: int = 1,
    machine_hours: Optional[Decimal] = None,
    policy: Optional["CostPolicy"] = None,
    economics: Optional[ChannelEconomics] = None,
    margin_basis: Optional[str] = None,
) -> list[LadderRung]:
    """Margin at each price across a range, for the operator to choose from.

    FR-007: what a customer will pay is a market judgement, and this system
    holds no data from which it could be derived. Rather than compute one and
    present it as a figure, the ladder reports what each price would earn and
    leaves the choice with the person who knows the market. Nothing is written.

    ``start``, ``stop`` and ``step`` are arguments rather than constants
    precisely so that no default range becomes an implied recommendation.
    """
    start = Decimal(str(start))
    stop = Decimal(str(stop))
    step = Decimal(str(step))
    if step <= ZERO:
        raise ValueError("step must be positive, or the ladder has no rungs")
    if stop < start:
        raise ValueError("stop must not be below start")

    hours = Decimal(str(machine_hours)) if machine_hours is not None else None
    basis = resolve_margin_basis(policy, override=margin_basis)

    rungs: list[LadderRung] = []
    price = start
    while price <= stop:
        result = margin_at(
            price.quantize(CENT),
            channel=channel,
            make_cost=make_cost,
            as_of=as_of,
            rules=rules,
            postage_paid=postage_paid,
            shipping_revenue=shipping_revenue,
            extras=extras,
            quantity=quantity,
            machine_hours=hours,
            policy=policy,
            economics=economics,
            margin_basis=basis,
        )
        # Read off the margin result rather than divided again here. The same
        # arithmetic in two places is the defect this feature removed from the
        # cost path (Constitution III), and the two would differ: the margin
        # chain divides the unrounded profit, which is the figure the margin
        # endpoint reports at this price.
        rungs.append(
            LadderRung(
                price=price.quantize(CENT),
                margin_pct=result.margin_pct,
                profit=result.profit,
                margin_basis=result.margin_basis,
                profit_per_machine_hour=result.profit_per_machine_hour,
            )
        )
        price += step

    return rungs
