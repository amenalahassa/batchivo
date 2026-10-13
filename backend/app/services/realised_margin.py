"""What a settled sale actually earned, from what was received and paid.

The planned margin answers "what should this earn". This answers "what did
it", and the two differ for ordinary reasons: the marketplace charged a fee
nobody predicted, the print used more filament than the slicer said, the plate
took an hour longer. SC-001 asks that the figure reported here be within two
percentage points of the margin computed from what actually moved -- cash in,
cash out.

## Where each figure comes from, in order of preference

**Revenue**: the order's own recorded amounts. Not the snapshot's list price:
what the customer was charged is what the order says, discounts and all.

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
from app.services.sale_snapshot import allocate_across_lines

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
    fees_paid: Decimal
    fees_source: str
    make_cost: Decimal
    postage_paid: Decimal

    profit: Decimal
    margin_pct: Optional[Decimal]
    margin_basis: str
    basis_amount: Decimal

    #: Each figure replaced by an observation, in words. Empty means every
    #: cost figure is the one the sale was priced on.
    substitutions: list[str] = field(default_factory=list)
    #: Why a figure could not be realised, where that is the case.
    gaps: list[str] = field(default_factory=list)


def _decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    """Exact conversion through ``str``, including out of JSON."""
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return default


def _planned_fee_total(item: OrderItem) -> Decimal:
    """The fees frozen on this line at the moment of sale."""
    return sum((_decimal(charge.get("amount")) for charge in (item.fees_json or [])), ZERO)


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
    revenue_received = item_revenue + shipping_share

    # --- what went out: fees ----------------------------------------------
    substitutions: list[str] = []
    gaps: list[str] = []

    actual_total = await _actual_fees_for_order(db, tenant, parent)
    if actual_total > ZERO:
        fees_paid = allocate_across_lines(actual_total, weights)[position]
        fees_source = "actual"
        substitutions.append("fees from a reconciled statement for this order")
    else:
        fees_paid = _planned_fee_total(item)
        fees_source = "planned"
        gaps.append("no reconciled fee is recorded for this order; the planned fees are used")

    # --- what went out: the make-cost -------------------------------------
    snapshot_lines = _snapshot_lines(item)
    quantity = Decimal(str(item.quantity or 1))
    unit_cost = _decimal(item.make_cost_at_sale)

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

    make_cost = (unit_cost * quantity).quantize(CENT)

    # --- postage ----------------------------------------------------------
    postage_share = allocate_across_lines(_decimal(parent.postage_paid), weights)[position]

    profit_exact = revenue_received - fees_paid - make_cost - postage_share

    basis = item.margin_basis_at_sale or "customer_total"
    if basis == "item_price":
        basis_amount = item_revenue
    elif basis == "net_revenue":
        basis_amount = revenue_received - fees_paid
    else:
        basis_amount = revenue_received

    if basis_amount > ZERO:
        margin_pct: Optional[Decimal] = (profit_exact / basis_amount * HUNDRED).quantize(
            Decimal("0.0001")
        )
    else:
        margin_pct = None

    return RealisedMargin(
        order_id=parent.id,
        order_item_id=item.id,
        revenue_received=revenue_received.quantize(CENT),
        shipping_revenue_allocated=shipping_share.quantize(CENT),
        fees_paid=fees_paid.quantize(CENT),
        fees_source=fees_source,
        make_cost=make_cost,
        postage_paid=postage_share.quantize(CENT),
        profit=profit_exact.quantize(CENT),
        margin_pct=margin_pct,
        margin_basis=basis,
        basis_amount=basis_amount.quantize(CENT),
        substitutions=substitutions,
        gaps=gaps,
    )


__all__ = ["OBSERVABLE_LINES", "RealisedMargin", "realised_margin"]
