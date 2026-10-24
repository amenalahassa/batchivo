"""Reconciliation and channel profitability endpoints (task T077).

Two things an operator could not do before: record what a statement actually
charged beside what the rules predicted, and see a channel's periodic costs
absorbed over the orders that actually arrived.

Writing a recorded actual is monetary policy, so it needs admin or owner
(FR-007a). The P&L read is open to every role (FR-007c): a figure nobody but an
admin can see is a figure the people doing the work cannot act on.

The ``409`` is the interesting status here. An order-scoped amount that would
push the period's unallocated remainder below zero is a contradiction between
two figures the operator entered, and only they know which is wrong -- so it is
reported rather than absorbed (FR-041c).
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB
from app.models.fee_actual import FeeActual
from app.models.fee_rule import FeeRule
from app.models.order import Order
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.schemas.channel_pnl import (
    AbsorbedCostResponse,
    CategoryReconciliationResponse,
    ChannelPnLResponse,
)
from app.schemas.fee_actual import FeeActualCreate, FeeActualResponse
from app.schemas.margin_alert import (
    LineMovementResponse,
    MarginDivergenceListResponse,
    MarginDivergenceResponse,
)
from app.services import channel_pnl, fee_engine, margin_alert
from app.services.channel_economics import ChannelEconomics, economics_over
from app.services.channel_pnl import ReconciliationConflict
from app.services.costing import resolve_margin_basis
from app.services.pricing_policy import resolve_cost_policy

logger = logging.getLogger(__name__)

router = APIRouter()

ZERO = Decimal("0")
CENT = Decimal("0.01")


async def _channel_or_404(
    db: AsyncSession,
    tenant_id: UUID,
    channel_id: UUID,
) -> SalesChannel:
    result = await db.execute(
        select(SalesChannel).where(
            SalesChannel.id == channel_id,
            SalesChannel.tenant_id == tenant_id,
        )
    )
    channel = result.scalars().first()
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sales channel not found",
        )
    return channel


async def _orders_in_period(
    db: AsyncSession,
    tenant_id: UUID,
    channel_id: UUID,
    period_start: date,
    period_end: date,
) -> list[Order]:
    """Orders on this channel in this period.

    Dated by ``created_at``, which is the only date every order carries. A
    cancelled order is excluded: it charged no fees and absorbed no overhead,
    so counting it would flatter the per-order absorption.
    """
    result = await db.execute(
        select(Order)
        .where(
            Order.tenant_id == tenant_id,
            Order.sales_channel_id == channel_id,
            Order.status != "cancelled",
        )
        .order_by(Order.created_at)
    )
    orders = []
    for order in result.scalars().all():
        placed = order.created_at.date() if order.created_at is not None else None
        if placed is not None and period_start <= placed <= period_end:
            orders.append(order)
    return orders


async def _actuals_in_period(
    db: AsyncSession,
    tenant_id: UUID,
    channel_id: UUID,
    period_start: date,
    period_end: date,
    order_ids: set[UUID],
) -> list[FeeActual]:
    """Recorded actuals touching this period.

    A period-scoped row counts when its period is the one asked about. An
    order-scoped row counts when the statement it appeared on is this period
    (task T235): "the order-level actual belongs to the period its statement
    assigned it to, not the period it was placed in". A row that names no
    statement period -- every row recorded before the column existed -- falls
    back to the period its order was placed in, which is ``order_ids``.
    """
    result = await db.execute(
        select(FeeActual).where(
            FeeActual.tenant_id == tenant_id,
            FeeActual.sales_channel_id == channel_id,
        )
    )
    rows = []
    for row in result.scalars().all():
        if row.order_id is not None:
            if row.statement_period_start is not None:
                if (row.statement_period_start, row.statement_period_end) == (
                    period_start,
                    period_end,
                ):
                    rows.append(row)
            elif row.order_id in order_ids:
                rows.append(row)
        elif row.period_start == period_start and row.period_end == period_end:
            rows.append(row)
    return rows


@router.post(
    "/fee-actuals",
    response_model=FeeActualResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_fee_actual(
    payload: FeeActualCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> FeeActualResponse:
    """Record what a statement charged. Requires admin or owner (FR-007a).

    An order-scoped amount is checked against the period it falls in before it
    is written: if the order amounts for that category would exceed the period
    total the operator already recorded, the two contradict each other and the
    write is refused with a ``409`` rather than leaving a negative remainder
    for somebody to find later (FR-041c).
    """
    channel = await _channel_or_404(db, tenant.id, payload.sales_channel_id)

    if payload.order_id is not None:
        await _refuse_conflicting_order_amount(db, tenant.id, channel.id, payload)

    actual = FeeActual(
        tenant_id=tenant.id,
        sales_channel_id=channel.id,
        fee_category=payload.fee_category,
        amount=payload.amount,
        period_start=payload.period_start,
        period_end=payload.period_end,
        order_id=payload.order_id,
        statement_period_start=payload.statement_period_start,
        statement_period_end=payload.statement_period_end,
        # FR-041e: entered by a human, and never presented as observed until it
        # comes from an automated source.
        source="entered",
        recorded_by_user_id=user.id,
    )
    db.add(actual)
    await db.commit()
    await db.refresh(actual)
    logger.info(
        f"Recorded {payload.fee_category} actual of {payload.amount} on channel {channel.id}"
    )
    return FeeActualResponse.model_validate(actual)


async def _refuse_conflicting_order_amount(
    db: AsyncSession,
    tenant_id: UUID,
    channel_id: UUID,
    payload: FeeActualCreate,
) -> None:
    """FR-041c's edge case, refused at the moment it would be created."""
    order = (
        (
            await db.execute(
                select(Order).where(
                    Order.id == payload.order_id,
                    Order.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    placed = order.created_at.date() if order.created_at is not None else None
    statement = (
        (payload.statement_period_start, payload.statement_period_end)
        if payload.statement_period_start is not None
        else None
    )
    if placed is None and statement is None:
        return

    periods = (
        (
            await db.execute(
                select(FeeActual).where(
                    FeeActual.tenant_id == tenant_id,
                    FeeActual.sales_channel_id == channel_id,
                    FeeActual.fee_category == payload.fee_category,
                    FeeActual.order_id.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    for period in periods:
        if period.period_start is None or period.period_end is None:
            continue
        # The period this amount reconciles against: the statement it names,
        # or -- where it names none -- the one containing the placed date.
        if statement is not None:
            if (period.period_start, period.period_end) != statement:
                continue
        elif not (period.period_start <= placed <= period.period_end):
            continue

        order_ids = {
            row.id
            for row in await _orders_in_period(
                db, tenant_id, channel_id, period.period_start, period.period_end
            )
        }
        existing = await _actuals_in_period(
            db,
            tenant_id,
            channel_id,
            period.period_start,
            period.period_end,
            order_ids,
        )
        same_category = [row for row in existing if row.fee_category == payload.fee_category]
        try:
            channel_pnl.reconcile_category(
                payload.fee_category,
                planned=ZERO,
                actuals=same_category + [_Pending(payload)],
                strict=True,
            )
        except ReconciliationConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc


class _Pending:
    """The row about to be written, shaped like a ``FeeActual``.

    The conflict check has to include the amount being recorded, and building
    it as an unsaved ORM instance would risk it being flushed by the session
    before the check decided whether to keep it.
    """

    def __init__(self, payload: FeeActualCreate) -> None:
        self.order_id = payload.order_id
        self.statement_period_start = payload.statement_period_start
        self.statement_period_end = payload.statement_period_end
        self.fee_category = payload.fee_category
        self.amount = payload.amount


def _placed_on(order: Order) -> Optional[date]:
    return order.created_at.date() if order.created_at is not None else None


def _has_snapshot(order: Order) -> bool:
    """Whether the sale snapshot was written for this order (FR-036).

    ``pricing_rev`` is set on every line the snapshot writes, whether or not
    the channel had fee rules to freeze -- so an empty ``fees_json`` on a
    snapshotted line means "no planned fees", not "unknown".
    """
    return any(item.pricing_rev is not None for item in (order.items or []))


def _frozen_fees(order: Order) -> list[tuple[str, Decimal]]:
    """The planned fees the order's lines froze at sale, by name."""
    return [
        (str(charge.get("name")), Decimal(str(charge.get("amount") or ZERO)))
        for item in (order.items or [])
        for charge in (item.fees_json or [])
    ]


def _economics_on(
    segments: list[tuple[ChannelEconomics, date, date]], on: Optional[date]
) -> ChannelEconomics:
    for economics, lo, hi in segments:
        if on is not None and lo <= on <= hi:
            return economics
    return segments[-1][0]


async def _live_listings(
    db: AsyncSession, channel_id: UUID, period_start: date, period_end: date
) -> int:
    """Products with a price on this channel at any point in the period.

    What a per-listing rule multiplies by (task T214). Counted per product,
    not per price row: a quantity tier or a mid-period price change is still
    one listing. Price rows carry no tenant of their own; the channel does,
    and the caller has already resolved it within this tenant.
    """
    result = await db.execute(
        select(func.count(func.distinct(ProductPricing.product_id))).where(
            ProductPricing.sales_channel_id == channel_id,
            ProductPricing.is_active.is_(True),
            ProductPricing.valid_from <= period_end,
            (ProductPricing.valid_to.is_(None)) | (ProductPricing.valid_to >= period_start),
        )
    )
    return int(result.scalar() or 0)


@router.get("/channel-pnl", response_model=ChannelPnLResponse)
async def get_channel_pnl(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    channel_id: UUID = Query(..., description="The channel to report on"),
    period_start: date = Query(..., description="First day of the period"),
    period_end: date = Query(..., description="Last day of the period"),
) -> ChannelPnLResponse:
    """One channel over one period: revenue, fees, absorption and margin.

    Revenue is tax-exclusive, and the tax collected appears only as a liability
    (FR-028c, FR-028d). Periodic and per-listing costs are absorbed over the
    period's actual order volume, and reported as unabsorbed where there were
    no orders rather than divided by zero (FR-025).

    A past period reads what was frozen and in force then, never today's
    channel (task T215): each settled order's planned fees are the ones its
    snapshot froze at sale (FR-036), the remitter is the one in force on the
    day each order was placed, and the margin basis is the one in force at the
    period's end -- with a period whose orders sold under more than one basis
    labelled as such rather than blended (FR-031d). Changing a fee rule, the
    remitter or the basis today therefore leaves a closed period unchanged.
    """
    if period_end < period_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="period_end cannot be before period_start",
        )

    channel = await _channel_or_404(db, tenant.id, channel_id)
    orders = await _orders_in_period(db, tenant.id, channel.id, period_start, period_end)
    order_ids = {order.id for order in orders}

    rules = list(
        (
            await db.execute(
                select(FeeRule).where(
                    FeeRule.sales_channel_id == channel.id,
                    FeeRule.tenant_id == tenant.id,
                )
            )
        )
        .scalars()
        .all()
    )
    # The channel's levers as they stood across the period (T216): the
    # remitter on each order's day, the subscription for each part.
    segments = await economics_over(db, channel, period_start, period_end)

    # --- Revenue, tax-exclusive, the planned fees and the make-cost --------
    revenue = ZERO
    shipping_revenue = ZERO
    postage = ZERO
    tax_collected = ZERO
    tax_liability = ZERO
    make_cost_total = ZERO
    make_cost_unrecorded_lines = 0
    planned_amounts: list[tuple[str, Decimal]] = []
    planned_from_rules = 0
    bases_sold_on: set[str] = set()
    policy_by_day: dict[date, str] = {}

    for order in orders:
        placed = _placed_on(order)
        subtotal = Decimal(str(order.subtotal or ZERO))
        shipping = Decimal(str(order.shipping_cost or ZERO))
        tax = Decimal(str(getattr(order, "sales_tax_collected", ZERO) or ZERO))
        postage += Decimal(str(getattr(order, "postage_paid", ZERO) or ZERO))

        context, _ = fee_engine.exclusive_context(
            item_subtotal=subtotal,
            shipping_revenue=shipping,
            sales_tax_collected=tax,
            # Order totals are stored tax-exclusive of their own tax column,
            # so nothing is derived here; FR-028e only applies where a
            # recorded figure was inclusive.
            tax_inclusive=False,
            quantity=sum(item.quantity for item in (order.items or [])) or 1,
        )
        revenue += context.item_subtotal + context.shipping_revenue
        shipping_revenue += shipping
        tax_collected += tax
        if _economics_on(segments, placed).tax_remitter == "operator":
            tax_liability += tax

        if _has_snapshot(order):
            # The figures the sale froze -- a rule superseded since, or one
            # superseded mid-period, cannot reprice it (FR-036, FR-038).
            planned_amounts.extend(_frozen_fees(order))
        else:
            # Sold before snapshots existed: the rules as they stood on the
            # order's own day, never the period's end, and counted so the
            # response can say how many figures were derived rather than read.
            stack = fee_engine.compute(channel, context, placed or period_end, rules=rules)
            planned_amounts.extend((charge.name, charge.amount_exact) for charge in stack.charges)
            planned_from_rules += 1

        for item in order.items or []:
            if item.has_snapshot:
                make_cost_total += Decimal(str(item.make_cost_at_sale)) * Decimal(
                    item.quantity or 0
                )
            else:
                make_cost_unrecorded_lines += 1
            if item.margin_basis_at_sale:
                bases_sold_on.add(item.margin_basis_at_sale)

        if not any(item.margin_basis_at_sale for item in (order.items or [])):
            day = placed or period_end
            if day not in policy_by_day:
                policy_by_day[day] = resolve_margin_basis(
                    await resolve_cost_policy(db, tenant, day)
                )
            bases_sold_on.add(policy_by_day[day])

    planned_by_category = channel_pnl.sum_by_category(planned_amounts)
    planned_fee_total = sum(planned_by_category.values(), ZERO)

    # --- Plan against statement (FR-041d) ----------------------------------
    actuals = await _actuals_in_period(
        db, tenant.id, channel.id, period_start, period_end, order_ids
    )
    reconciliation = channel_pnl.reconcile(planned_by_category, actuals)
    recorded = [row.actual_total for row in reconciliation if row.actual_total is not None]
    actual_fee_total = sum(recorded, ZERO) if recorded else None
    unallocated = sum(
        (
            row.unallocated_remainder
            for row in reconciliation
            if row.unallocated_remainder is not None
        ),
        ZERO,
    )

    # --- Absorption over actual order volume (FR-025, task T214) -----------
    # Each periodic cost is owed once for the period -- the subscription for
    # the months it covers, at the figure in force for each part of it, and
    # the periodic fee rules from the rules in force during it -- and is then
    # spread over however many orders arrived, or reported unabsorbed.
    absorbed = []
    subscription = sum(
        (economics.monthly_cost * fee_engine.months_in(lo, hi) for economics, lo, hi in segments),
        ZERO,
    )
    if subscription > ZERO:
        absorbed.append(
            channel_pnl.absorb(
                key="monthly_cost",
                label="Channel subscription",
                total=subscription,
                order_count=len(orders),
            )
        )
    listings = await _live_listings(db, channel.id, period_start, period_end)
    periodic = fee_engine.periodic_charges(rules, period_start, period_end, listings=listings)
    periodic_total = sum((charge.amount_exact for charge in periodic), ZERO)
    if periodic_total > ZERO:
        absorbed.append(
            channel_pnl.absorb(
                key="periodic_fees",
                label="Listing and periodic fees",
                total=periodic_total,
                order_count=len(orders),
            )
        )
    unabsorbed = sum((cost.total for cost in absorbed if cost.is_unabsorbed), ZERO)

    # --- Margin, on the basis in force at the period's end -----------------
    # Derived by `channel_pnl`, not here (task T160). Resolved as at the
    # period's end rather than today, so changing the basis now does not
    # restate a closed period (FR-031d).
    basis = resolve_margin_basis(await resolve_cost_policy(db, tenant, period_end))
    bases = sorted(bases_sold_on | {basis})
    spans_change = len(bases) > 1
    margin = channel_pnl.period_margin(
        revenue_tax_exclusive=revenue,
        shipping_revenue=shipping_revenue,
        planned_fee_total=planned_fee_total,
        postage_paid=postage,
        absorbed_costs=absorbed,
        basis=basis,
        make_cost_total=make_cost_total,
    )

    notes: list[str] = []
    if planned_from_rules:
        notes.append(
            f"{planned_from_rules} of {len(orders)} orders were sold before sale snapshots, "
            f"so their planned fees are recomputed from the rules in force on each order's "
            f"own date rather than read from what was frozen"
        )
    if make_cost_unrecorded_lines:
        notes.append(
            f"{make_cost_unrecorded_lines} order lines froze no make-cost at sale, so the "
            f"period's make-cost leaves them out rather than recomputing them from today's "
            f"inputs"
        )
    if spans_change:
        notes.append(
            f"orders in this period sold under more than one margin basis "
            f"({', '.join(bases)}); the percentage is on the basis in force at the "
            f"period's end ({basis}) and is not a blend of them"
        )

    return ChannelPnLResponse(
        channel_id=channel.id,
        period_start=period_start,
        period_end=period_end,
        order_count=len(orders),
        revenue_tax_exclusive=revenue.quantize(CENT),
        sales_tax_collected=tax_collected.quantize(CENT),
        sales_tax_liability=tax_liability.quantize(CENT),
        postage_paid=postage.quantize(CENT),
        shipping_revenue=shipping_revenue.quantize(CENT),
        shipping_net=(shipping_revenue - postage).quantize(CENT),
        planned_fee_total=planned_fee_total.quantize(CENT),
        planned_fees_from_rules=planned_from_rules,
        actual_fee_total=actual_fee_total.quantize(CENT) if actual_fee_total is not None else None,
        unallocated_remainder=unallocated.quantize(CENT),
        fee_difference=(
            (actual_fee_total - planned_fee_total).quantize(CENT)
            if actual_fee_total is not None
            else None
        ),
        reconciliation=[
            CategoryReconciliationResponse(
                category=row.category,
                planned=row.planned,
                actual_period=row.actual_period,
                actual_order_scoped=row.actual_order_scoped,
                unallocated_remainder=row.unallocated_remainder,
                actual_total=row.actual_total,
                difference=row.difference,
                difference_pct_of_fee=row.difference_pct_of_fee,
            )
            for row in reconciliation
        ],
        absorbed_costs=[
            AbsorbedCostResponse(
                key=cost.key,
                label=cost.label,
                total=cost.total.quantize(CENT),
                order_count=cost.order_count,
                per_order=cost.per_order,
                is_unabsorbed=cost.is_unabsorbed,
            )
            for cost in absorbed
        ],
        unabsorbed_total=unabsorbed.quantize(CENT),
        make_cost_total=make_cost_total.quantize(CENT),
        make_cost_unrecorded_lines=make_cost_unrecorded_lines,
        profit=margin.profit.quantize(CENT),
        margin_pct=margin.margin_pct,
        margin_basis=margin.basis,
        margin_basis_label=margin.basis_label,
        margin_bases_in_period=bases,
        margin_basis_spans_change=spans_change,
        notes=notes,
    )


@router.get("/margin-divergence", response_model=MarginDivergenceListResponse)
async def get_margin_divergence(
    tenant: CurrentTenant,
    db: TenantDB,
    _user: CurrentUser,
    product_id: UUID | None = Query(None, description="Narrow to one product's settled lines"),
    since: date | None = Query(None, description="Only orders placed on or after this date"),
    only_alerting: bool = Query(
        False,
        description=(
            "Return only the lines past the operator's threshold -- what FR-042 "
            "says they must be alerted about"
        ),
    ),
    limit: int = Query(200, ge=1, le=1000),
) -> MarginDivergenceListResponse:
    """What settled lines actually earned, against the margin they were sold at.

    FR-042's second clause asks that the operator be alerted when a product's
    realised margin diverges from plan beyond their own threshold, and US7
    scenario 3 asks that they be told *which lines moved*. Both come from here.

    Open to every role (FR-007c). The threshold is monetary policy and is set
    on the pricing-policy screen; reading the consequence of it is not.

    Nothing is written. A realised margin is recomputed from records that
    already exist (Constitution V) and no snapshot is touched (FR-038): a
    divergence is an observation about history, not a correction to it.
    """
    found = await margin_alert.divergences(
        db,
        tenant,
        product_id=product_id,
        since=since,
        only_diverging=only_alerting,
        limit=limit,
    )
    policy = await resolve_cost_policy(db, tenant)

    return MarginDivergenceListResponse(
        divergences=[
            MarginDivergenceResponse(
                order_id=row.order_id,
                order_item_id=row.order_item_id,
                product_id=row.product_id,
                product_name=row.product_name,
                sold_on=row.sold_on,
                margin_basis=row.margin_basis,
                planned_margin_pct=row.planned_margin_pct,
                realised_margin_pct=row.realised_margin_pct,
                divergence_points=row.divergence_points,
                threshold_points=row.threshold_points,
                diverges=row.diverges,
                shortfall=row.shortfall,
                planned_profit=row.planned_profit,
                realised_profit=row.realised_profit,
                movements=[
                    LineMovementResponse(
                        key=movement.key,
                        planned=movement.planned,
                        realised=movement.realised,
                        delta=movement.delta,
                    )
                    for movement in row.movements
                ],
                fees_source=row.fees_source,
                substitutions=row.substitutions,
                gaps=row.gaps,
            )
            for row in found
        ],
        total=len(found),
        alerting=sum(1 for row in found if row.diverges),
        threshold_points=policy.margin_alert_threshold_pct,
    )
