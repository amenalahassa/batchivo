"""Realised margin against plan, and the alert when the two part company.

FR-042's second clause: "the operator MUST be alerted when a product's
realised margin diverges from plan beyond a threshold they set". US7 scenario 3
adds what the alert has to say -- *which lines moved* -- because "this product
is underperforming" sends an operator hunting, while "the fee line is £1.80
over and the material line is 12 g heavy" is something they can act on.

The threshold is ``margin_alert_threshold_pct`` on the tenant's pricing policy,
defaulting to 5 percentage points. It was settable from the start and read by
nothing: the figure existed, the comparison did not.

## What a divergence is measured between

**Plan** is the snapshot frozen on the order line at sale (FR-036): the price,
the fees and the make-cost as they stood. It is the margin the operator decided
to sell at, and it never moves (FR-038).

**Realised** is :mod:`app.services.realised_margin`: the same line recomputed
from what was actually received and actually paid -- reconciled fees where a
statement recorded them, actual filament and actual print hours where a
production run did.

The divergence is in **percentage points**, not percent: a plan of 35% against
a realised 28% diverges by 7, not by 20. The threshold is stated in points
because that is how an operator reasons about a margin slipping.

## What this never does

It does not write, and it does not reprice. A divergence is an observation
about history, computed on demand from records that already exist
(Constitution V). It raises no estimate revision of its own -- that is
``variance_service``'s job, through the proposal an operator accepts -- and it
never touches a snapshot. An alert is a thing to read, not a correction.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.order import Order, OrderItem
from app.services.costing import basis_amount_for
from app.services.pricing_policy import resolve_cost_policy
from app.services.realised_margin import RealisedMargin, realised_margin

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
POINTS = Decimal("0.01")

#: Lines worth naming in an alert. A line that moved by less than a cent is
#: noise, not a finding.
MOVEMENT_FLOOR = Decimal("0.01")


@dataclass(frozen=True)
class LineMovement:
    """One cost line that came in different from plan."""

    key: str
    planned: Decimal
    realised: Decimal

    @property
    def delta(self) -> Decimal:
        """Positive where the line cost more than planned."""
        return (self.realised - self.planned).quantize(CENT)


@dataclass(frozen=True)
class MarginDivergence:
    """One settled line's realised margin beside the margin it was sold at.

    ``diverges`` is the only field a caller needs to decide whether to alert;
    the rest is what the alert says. ``planned_margin_pct`` or
    ``realised_margin_pct`` being ``None`` -- fees consuming the whole basis --
    makes ``divergence_points`` ``None`` too, and such a line is reported
    rather than alerted on: a percentage that is undefined has not diverged,
    it is simply unanswerable (the net-revenue edge case in the spec).
    """

    order_id: Any
    order_item_id: Any
    product_id: Any
    product_name: Optional[str]
    sold_on: Optional[date]

    margin_basis: str
    planned_margin_pct: Optional[Decimal]
    realised_margin_pct: Optional[Decimal]
    #: Realised minus planned, in percentage points. Negative is a shortfall.
    divergence_points: Optional[Decimal]
    threshold_points: Decimal

    planned_profit: Decimal
    realised_profit: Decimal

    #: Which cost lines moved, heaviest movement first (US7 scenario 3).
    movements: list[LineMovement] = field(default_factory=list)
    #: Where the fee total came from, so a planned fee is never read as actual.
    fees_source: str = "planned"
    #: Figures that came from an observation rather than the snapshot.
    substitutions: list[str] = field(default_factory=list)
    #: Why something could not be realised.
    gaps: list[str] = field(default_factory=list)

    @property
    def diverges(self) -> bool:
        """Whether this line is past the operator's threshold.

        A shortfall and an overshoot both count. An item earning 20 points more
        than planned is as much a sign that the estimate is wrong as one
        earning 20 points less -- and the overshoot is the one that silently
        loses sales to a price nobody needed to charge.
        """
        if self.divergence_points is None:
            return False
        return abs(self.divergence_points) > self.threshold_points

    @property
    def shortfall(self) -> bool:
        """True where the line earned less than planned."""
        return self.divergence_points is not None and self.divergence_points < ZERO


def _decimal(value: Any, default: Decimal = ZERO) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return default


def _planned_fee_total(item: OrderItem) -> Decimal:
    return sum((_decimal(charge.get("amount")) for charge in (item.fees_json or [])), ZERO)


def _planned_lines(item: OrderItem) -> dict[str, Decimal]:
    breakdown = item.cost_breakdown_json or {}
    return {
        str(line.get("key")): _decimal(line.get("amount"))
        for line in (breakdown.get("lines") or [])
        if line.get("key") is not None
    }


def planned_margin_pct(
    item: OrderItem,
    *,
    shipping_revenue: Decimal = ZERO,
    postage_paid: Decimal = ZERO,
) -> tuple[Optional[Decimal], Decimal, str]:
    """The margin this line was sold at, from its own snapshot.

    Returns ``(margin_pct, profit, basis)``. The percentage is recomputed from
    the snapshot's recorded parts rather than read back, because no percentage
    is stored: FR-031c makes the basis a lens over the figures, and the figures
    are what was frozen.

    ``shipping_revenue`` and ``postage_paid`` are this line's share of the
    order-level amounts, passed in by the caller that allocated them. They are
    arguments rather than lookups so that the planned and realised figures are
    allocated the same way -- a shipping share computed twice by two different
    rules is a divergence the operator would read as a real one.
    """
    basis = item.margin_basis_at_sale or "customer_total"
    quantity = Decimal(str(item.quantity or 1))
    item_price = _decimal(item.list_price_at_sale) * quantity
    customer_total = item_price + shipping_revenue
    fees = _planned_fee_total(item)
    make_cost = _decimal(item.make_cost_at_sale) * quantity

    profit = (customer_total - fees - make_cost - postage_paid).quantize(CENT)
    basis_amount = basis_amount_for(
        basis,
        item_price=item_price,
        customer_total=customer_total,
        fee_total_exact=fees,
    )
    if basis_amount <= ZERO:
        return None, profit, basis
    return (profit / basis_amount * HUNDRED).quantize(POINTS), profit, basis


def _movements(item: OrderItem, realised: RealisedMargin) -> list[LineMovement]:
    """The cost lines that came in different from plan.

    Only the make-cost lines a production run can speak to move; the realised
    total is the planned total with those substituted, so comparing the two
    totals and attributing the whole difference to one line would be a guess.
    The honest statement is per line, which is what the alert needs anyway.

    The fee line is named separately below, because fees are not a make-cost
    line and a reconciled statement moves them without any run involved.
    """
    planned = _planned_lines(item)
    if not realised.realised_lines:
        # No per-line actuals: the difference, if any, is in the fees or the
        # revenue, which the margin figures already carry. Naming no line is
        # more useful than naming every line with a zero beside it.
        return []

    movements = [
        LineMovement(key=key, planned=planned.get(key, ZERO), realised=amount)
        for key, amount in realised.realised_lines.items()
        if abs(amount - planned.get(key, ZERO)) >= MOVEMENT_FLOOR
    ]

    # Fees sit alongside the cost lines in an alert even though they are not
    # one: on a marketplace they are the line most likely to have moved, and
    # FR-041 exists because the planned figure and the statement disagree.
    planned_fees = _planned_fee_total(item)
    if abs(realised.fees_paid - planned_fees) >= MOVEMENT_FLOOR:
        movements.append(
            LineMovement(key="fees", planned=planned_fees, realised=realised.fees_paid)
        )

    movements.sort(key=lambda movement: abs(movement.delta), reverse=True)
    return movements


async def divergence_for_item(
    db: AsyncSession,
    tenant: "Tenant",
    item: OrderItem,
    *,
    threshold_points: Optional[Decimal] = None,
    order: Optional[Order] = None,
) -> MarginDivergence:
    """One settled line's realised margin against the margin it was sold at."""
    if threshold_points is None:
        policy = await resolve_cost_policy(db, tenant)
        threshold_points = _decimal(policy.margin_alert_threshold_pct, Decimal("5"))

    realised = await realised_margin(db, tenant, item, order=order)
    # The realised figures already carry this line's share of the order-level
    # shipping and postage. Reusing them holds the plan and the actual to one
    # allocation, so a divergence is never an artefact of two different splits.
    planned_pct, planned_profit, basis = planned_margin_pct(
        item,
        shipping_revenue=realised.shipping_revenue_allocated,
        postage_paid=realised.postage_paid,
    )

    divergence: Optional[Decimal] = None
    if planned_pct is not None and realised.margin_pct is not None:
        divergence = (realised.margin_pct - planned_pct).quantize(POINTS)

    parent = order
    product = getattr(item, "product", None)
    # `Order` dates from `TimestampMixin`; there is no separate order_date.
    placed = getattr(parent, "created_at", None) if parent is not None else None

    return MarginDivergence(
        order_id=item.order_id,
        order_item_id=item.id,
        product_id=item.product_id,
        product_name=getattr(product, "name", None),
        sold_on=placed.date() if placed is not None else None,
        margin_basis=basis,
        planned_margin_pct=planned_pct,
        realised_margin_pct=realised.margin_pct,
        divergence_points=divergence,
        threshold_points=threshold_points,
        planned_profit=planned_profit,
        realised_profit=realised.profit,
        movements=_movements(item, realised),
        fees_source=realised.fees_source,
        substitutions=list(realised.substitutions),
        gaps=list(realised.gaps),
    )


async def divergences(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    product_id: Optional[Any] = None,
    since: Optional[date] = None,
    only_diverging: bool = False,
    limit: int = 200,
) -> list[MarginDivergence]:
    """Realised-versus-planned margin for settled lines, worst first.

    Only lines carrying a snapshot are considered: a line sold before Tier 3
    has no plan to diverge from, and reporting it as a 100% shortfall would be
    an artefact of the migration rather than a finding about the business.
    """
    policy = await resolve_cost_policy(db, tenant)
    threshold = _decimal(policy.margin_alert_threshold_pct, Decimal("5"))

    query = (
        select(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            Order.tenant_id == tenant.id,
            OrderItem.make_cost_at_sale.isnot(None),
        )
        .options(selectinload(OrderItem.product), selectinload(OrderItem.order))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    if product_id is not None:
        query = query.where(OrderItem.product_id == product_id)
    if since is not None:
        query = query.where(Order.created_at >= since)

    results: list[MarginDivergence] = []
    for item in (await db.execute(query)).scalars().all():
        try:
            found = await divergence_for_item(
                db, tenant, item, threshold_points=threshold, order=item.order
            )
        except Exception:  # pragma: no cover - one bad line must not hide the rest
            logger.warning("Could not realise margin for order item %s", item.id, exc_info=True)
            continue
        if only_diverging and not found.diverges:
            continue
        results.append(found)

    # Worst shortfall first: that is the order an operator wants to read in.
    results.sort(
        key=lambda found: (
            found.divergence_points if found.divergence_points is not None else Decimal("9999")
        )
    )
    return results


async def alerting_products(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    since: Optional[date] = None,
    limit: int = 200,
) -> list[MarginDivergence]:
    """The lines an operator should be told about (FR-042).

    One entry per diverging line. A product that diverged on several orders
    appears once per order, because each order's lines moved differently and a
    blended figure would hide which one to look at.
    """
    return await divergences(db, tenant, since=since, only_diverging=True, limit=limit)


__all__ = [
    "LineMovement",
    "MarginDivergence",
    "alerting_products",
    "divergence_for_item",
    "divergences",
    "planned_margin_pct",
]
