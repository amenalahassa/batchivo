"""What a settled sale actually earned, from what was received and paid.

The planned margin answers "what should this earn". This answers "what did
it", and the two differ for ordinary reasons: the marketplace charged a fee
nobody predicted, the print used more filament than the slicer said, the plate
took an hour longer. SC-001 asks that the figure reported here be within two
percentage points of the margin computed from what actually moved -- cash in,
cash out.

## Where each figure comes from, in order of preference

**Revenue**: the order's own recorded amounts, less anything recorded as
refunded against it (FR-040, task T189). Not the snapshot's list price: what
the customer was charged is what the order says, discounts and all -- and what
they kept is that less what went back. A refund reduces the revenue of the
lines it came from; it never rewrites the snapshot, which is what the sale was
priced on and is immutable (FR-038). Nothing recorded a refund at all before
T189, so a fully refunded order reported the margin it earned at sale, which
made SC-001 false by the whole refund.

**Fees**: a recorded actual for this order where one exists (FR-041b),
otherwise the planned fees frozen on the line at sale. Order-level actuals are
allocated across the lines pro-rata, with the rounding remainder to the
heaviest line, exactly as the planned ones were -- a reconciliation that is a
cent out for no findable reason is worse than one that is wrong by a pound.

**Make cost**: the snapshot's breakdown, with the material and machine lines
replaced by actuals where a production run recorded them. Labor, overhead and
packaging have no observed counterpart, so they stay as they were costed.

## What this never does

It does not write. A realised margin is recomputed from records on demand
(Constitution V), and nothing here touches the snapshot: the snapshot is what
the sale was priced on and is immutable (FR-038). It also never silently
presents a planned figure as an actual -- ``substitutions`` names every figure
that came from an observation, and ``fees_source`` says whether the fee total
was reconciled, planned, or a mixture.
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fee_actual import FeeActual
from app.models.order import Order, OrderItem
from app.models.production_run import ProductionRun
from app.services.refund_actuals import refunded_total
from app.services.costing import margin_of
from app.services.currency_edge import cost_in_sale_currency
from app.services.sale_snapshot import (
    allocate_across_lines,
    frozen_fee_total,
    snapshot_amount as _decimal,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")

#: The breakdown lines a production run can speak to. Everything else --
#: labor, overhead, packaging -- has no observed counterpart on a run, so
#: substituting anything there would be inventing an actual.
OBSERVABLE_LINES: frozenset[str] = frozenset({"material", "waste", "machine"})


@dataclass(frozen=True)
class RealisedMargin:
    """What one settled line earned, and which figures are observations.

    ``margin_pct`` is ``None`` where the basis is zero or negative -- fees
    consuming the whole revenue -- for the same reason the planned margin
    reports it as undefined: zero would read as break-even.
    """

    order_id: Any
    order_item_id: Any

    revenue_received: Decimal
    shipping_revenue_allocated: Decimal
    #: What was recorded as refunded, allocated to this line (FR-040).
    #:
    #: Reported separately rather than folded silently into
    #: ``revenue_received`` so a reader can see that a refund is the reason the
    #: margin moved. ``revenue_received`` is already net of it.
    refund_allocated: Decimal
    fees_paid: Decimal
    fees_source: str
    make_cost: Decimal
    postage_paid: Decimal

    #: ``None`` where the make-cost could not be converted (task T231).
    profit: Optional[Decimal]
    margin_pct: Optional[Decimal]
    margin_basis: str
    basis_amount: Decimal

    #: Each figure replaced by an observation, in words. Empty means every
    #: cost figure is the one the sale was priced on.
    substitutions: list[str] = field(default_factory=list)
    #: Why a figure could not be realised, where that is the case.
    gaps: list[str] = field(default_factory=list)
    #: The make-cost lines as realised, per unit, by key -- the snapshot's own
    #: lines with actuals substituted where a run recorded them. Empty where
    #: the line carries no breakdown to substitute into.
    #:
    #: Returned because an alert has to say *which* lines moved (US7 scenario
    #: 3): "this product underperformed" sends an operator hunting, while "the
    #: material line is 12 g heavy" is something they can act on. The totals
    #: alone cannot be decomposed after the fact without guessing.
    realised_lines: dict[str, Decimal] = field(default_factory=dict)


def _snapshot_lines(item: OrderItem) -> dict[str, Decimal]:
    """The snapshot's cost lines, by key."""
    breakdown = item.cost_breakdown_json or {}
    lines = breakdown.get("lines") or []
    return {
        str(line.get("key")): _decimal(line.get("amount"))
        for line in lines
        if line.get("key") is not None
    }


def _snapshot_premium(item: OrderItem) -> Decimal:
    breakdown = item.cost_breakdown_json or {}
    return _decimal(breakdown.get("failure_premium"))


async def _actual_fees_for_order(db: AsyncSession, tenant: "Tenant", order: Order) -> Decimal:
    """Fees recorded against this order, as a statement reconciled them.

    Order-level only (FR-041b). A period total is not attributable to one
    order, and spreading one across a period's orders would report a figure
    for this sale that nobody recorded about it.
    """
    rows = (
        (
            await db.execute(
                select(FeeActual).where(
                    FeeActual.tenant_id == tenant.id,
                    FeeActual.order_id == order.id,
                )
            )
        )
        .scalars()
        .all()
    )
    return sum((_decimal(row.amount) for row in rows), ZERO)


async def _run_actuals_for(
    db: AsyncSession, tenant: "Tenant", item: OrderItem
) -> Optional[ProductionRun]:
    """The most recent completed run for this product that recorded actuals.

    Loosely attributed on purpose, and the result says so. A production run
    makes stock, not an order line: the run that produced the unit which was
    later sold is not recorded anywhere, and pretending otherwise would be a
    fabricated link. The most recent run with actuals is the best available
    evidence of what this product actually takes, which is the question SC-001
    is asking.
    """
    if item.product_id is None:
        return None
    return (
        (
            await db.execute(
                select(ProductionRun)
                .where(
                    ProductionRun.tenant_id == tenant.id,
                    ProductionRun.product_id == item.product_id,
                    ProductionRun.status == "completed",
                )
                .order_by(ProductionRun.started_at.desc())
            )
        )
        .scalars()
        .first()
    )


def _machine_rate_from(item: OrderItem) -> Optional[Decimal]:
    """The machine rate the sale was costed at, from its own snapshot.

    Taken from the snapshot rather than from today's printer policy: a
    realised margin compares what was used against what was planned, and
    repricing the machine hour at today's rate would mix the two questions.
    """
    breakdown = item.cost_breakdown_json or {}
    rate = breakdown.get("machine_rate_per_hour")
    if rate is not None:
        return _decimal(rate)
    hours = _decimal(breakdown.get("machine_hours"))
    machine = _snapshot_lines(item).get("machine")
    if hours > ZERO and machine is not None:
        return machine / hours
    return None


def _cost_per_gram_from(item: OrderItem, run: Optional[ProductionRun]) -> Optional[Decimal]:
    """What a gram cost: the run's own figure first, else the sale's."""
    if run is not None:
        actual = _decimal(getattr(run, "cost_per_gram_actual", None), ZERO)
        if actual > ZERO:
            return actual
    breakdown = item.cost_breakdown_json or {}
    grams = _decimal(breakdown.get("part_grams"))
    material = _snapshot_lines(item).get("material")
    if grams > ZERO and material is not None:
        return material / grams
    return None


async def realised_margin(
    db: AsyncSession,
    tenant: "Tenant",
    item: OrderItem,
    *,
    order: Optional[Order] = None,
    siblings: Optional[Sequence[OrderItem]] = None,
    run: Optional[ProductionRun] = None,
) -> RealisedMargin:
    """What this settled line actually earned.

    ``siblings`` are the order's other lines, needed to allocate order-level
    amounts; they are loaded when not supplied. ``run`` overrides the
    production run used for the material and machine actuals, which is how a
    caller that knows the right run says so.
    """
    parent = order
    if parent is None:
        parent = (
            await db.execute(
                select(Order).where(Order.id == item.order_id, Order.tenant_id == tenant.id)
            )
        ).scalar_one()

    lines = list(siblings) if siblings is not None else None
    if lines is None:
        lines = list(
            (
                await db.execute(
                    select(OrderItem).where(
                        OrderItem.order_id == parent.id,
                        OrderItem.tenant_id == tenant.id,
                    )
                )
            )
            .scalars()
            .all()
        )
    if not lines:  # pragma: no cover - an order always has its own line
        lines = [item]

    weights = [_decimal(line.total_price) for line in lines]
    position = next(
        (index for index, line in enumerate(lines) if line.id == item.id),
        0,
    )

    # --- what came in -----------------------------------------------------
    item_revenue = _decimal(item.total_price)
    shipping_share = allocate_across_lines(_decimal(parent.shipping_cost), weights)[position]
    charged = item_revenue + shipping_share

    substitutions: list[str] = []
    gaps: list[str] = []

    # --- what went back out again: refunds (FR-040, task T189) -------------
    #
    # A refund is an actual recorded against the settled order, so it belongs
    # on this side of the comparison rather than in the plan. It is allocated
    # across the lines pro-rata by line subtotal -- the same allocation the
    # fees and the postage use, with the rounding remainder to the heaviest
    # line -- because a refund is recorded against the order and a margin is
    # reported per line.
    #
    # An order-level allocation, not a per-line one: which line a partial
    # refund was *for* is not recorded anywhere, and claiming it was would be
    # a fabricated link of exactly the kind `_run_actuals_for` refuses to
    # make. Where the refund is the whole order, every line goes to zero
    # revenue either way.
    #
    # Nothing is clamped. A refund larger than the line's revenue -- a goodwill
    # payment beyond the sale -- yields negative revenue and a negative margin,
    # which is what happened; flooring it at zero would hide a loss.
    refund_total = await refunded_total(db, tenant, parent.id)
    if refund_total > ZERO:
        refund_allocated = allocate_across_lines(refund_total, weights)[position]
        substitutions.append(f"revenue reduced by {refund_allocated} refunded on this order")
    else:
        refund_allocated = ZERO

    revenue_received = charged - refund_allocated

    # --- what went out: fees ----------------------------------------------

    actual_total = await _actual_fees_for_order(db, tenant, parent)
    if actual_total > ZERO:
        fees_paid = allocate_across_lines(actual_total, weights)[position]
        fees_source = "actual"
        substitutions.append("fees from a reconciled statement for this order")
    else:
        fees_paid = frozen_fee_total(item)
        fees_source = "planned"
        gaps.append("no reconciled fee is recorded for this order; the planned fees are used")

    # --- what went out: the make-cost -------------------------------------
    snapshot_lines = _snapshot_lines(item)
    quantity = Decimal(str(item.quantity or 1))
    unit_cost = _decimal(item.make_cost_at_sale)
    realised_lines: dict[str, Decimal] = {}

    if not snapshot_lines:
        gaps.append("this line carries no cost breakdown, so no actual could be substituted")
    else:
        resolved = dict(snapshot_lines)
        chosen_run = run if run is not None else await _run_actuals_for(db, tenant, item)

        if chosen_run is None:
            gaps.append("no completed production run records what this product actually takes")
        else:
            grams = _decimal(getattr(chosen_run, "actual_total_weight_grams", None), ZERO)
            per_gram = _cost_per_gram_from(item, chosen_run)
            if grams > ZERO and per_gram is not None and per_gram > ZERO:
                # The run's weight covers the whole plate's filament -- part and
                # purge together -- so it replaces both lines at once rather
                # than being split on a ratio nobody measured.
                resolved["material"] = grams * per_gram
                resolved["waste"] = ZERO
                substitutions.append(
                    f"material from run {chosen_run.run_number}: {grams} g actually used"
                )
            elif "material" in snapshot_lines:
                gaps.append("the production run recorded no actual filament weight")

            hours = _decimal(getattr(chosen_run, "duration_hours", None), ZERO)
            rate = _machine_rate_from(item)
            if hours > ZERO and rate is not None:
                resolved["machine"] = hours * rate
                substitutions.append(
                    f"machine time from run {chosen_run.run_number}: {hours} h actually taken"
                )
            elif "machine" in snapshot_lines:
                gaps.append("the production run recorded no actual print time")

        # The failure premium is carried as it was costed. It is a charge for
        # starts that never became sellable parts, and a single run of a
        # settled order says nothing about the yield across many.
        unit_cost = sum(resolved.values(), ZERO) + _snapshot_premium(item)
        realised_lines = {key: amount.quantize(CENT) for key, amount in resolved.items()}

    # Kept in the books currency; set against revenue in the order's through
    # the rate the sale froze (task T231). With none frozen it is unknown, and
    # so is every figure built on it.
    in_sale_currency = cost_in_sale_currency(item, unit_cost * quantity)
    if in_sale_currency is None:
        gaps.append(
            "no exchange rate was frozen onto this sale, so its make-cost, kept in "
            "the books currency, cannot be set against what the customer paid"
        )
    make_cost = (in_sale_currency if in_sale_currency is not None else ZERO).quantize(CENT)

    # --- postage ----------------------------------------------------------
    if parent.postage_paid is None:
        gaps.append(
            "the postage paid on this order is unrecorded, so the margin carries none "
            "-- record it on the order once the label is bought (task T230)"
        )
    postage_share = allocate_across_lines(_decimal(parent.postage_paid), weights)[position]

    # The one margin derivation (task T221). The item-price basis is taken net
    # of the refund -- what was kept, on every basis -- through `refund`.
    basis = item.margin_basis_at_sale or "customer_total"
    figures = margin_of(
        item_price=item_revenue,
        shipping_revenue=shipping_share,
        fees=fees_paid,
        make_cost=make_cost,
        postage_paid=postage_share,
        basis=basis,
        refund=refund_allocated,
    )
    profit_exact: Optional[Decimal] = figures.profit
    basis_amount = figures.basis_amount
    margin_pct = figures.margin_pct
    if in_sale_currency is None:
        profit_exact = None
        margin_pct = None

    return RealisedMargin(
        order_id=parent.id,
        order_item_id=item.id,
        revenue_received=revenue_received.quantize(CENT),
        shipping_revenue_allocated=shipping_share.quantize(CENT),
        refund_allocated=refund_allocated.quantize(CENT),
        fees_paid=fees_paid.quantize(CENT),
        fees_source=fees_source,
        make_cost=make_cost,
        postage_paid=postage_share.quantize(CENT),
        profit=profit_exact.quantize(CENT) if profit_exact is not None else None,
        margin_pct=margin_pct,
        margin_basis=basis,
        basis_amount=basis_amount.quantize(CENT),
        substitutions=substitutions,
        gaps=gaps,
        realised_lines=realised_lines,
    )


__all__ = ["OBSERVABLE_LINES", "RealisedMargin", "realised_margin"]
