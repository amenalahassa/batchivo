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
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB
from app.models.fee_actual import FeeActual
from app.models.fee_rule import FeeRule
from app.models.order import Order
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

    A period-scoped row counts when its period is the one asked about; an
    order-scoped row counts when its order falls inside the period, which is
    how an order amount reduces the right period's remainder (FR-041c).
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
            if row.order_id in order_ids:
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
    if placed is None:
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
        if not (period.period_start <= placed <= period.period_end):
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
        self.fee_category = payload.fee_category
        self.amount = payload.amount


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

    # --- Revenue, tax-exclusive, and the planned fee stack per order -------
    revenue = ZERO
    shipping_revenue = ZERO
    postage = ZERO
    tax_collected = ZERO
    stacks = []
    for order in orders:
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
        stacks.append(fee_engine.compute(channel, context, period_end, rules=rules))
        revenue += context.item_subtotal + context.shipping_revenue
        shipping_revenue += shipping
        tax_collected += tax

    planned_by_category = channel_pnl.planned_total(stacks)
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

    # --- Absorption over actual order volume (FR-025) ----------------------
    absorbed = []
    monthly = Decimal(str(channel.monthly_cost or ZERO))
    if monthly > ZERO:
        absorbed.append(
            channel_pnl.absorb(
                key="monthly_cost",
                label="Channel subscription",
                total=monthly,
                order_count=len(orders),
            )
        )
    periodic_total = sum((stack.periodic_total_exact for stack in stacks), ZERO)
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

    # --- Margin, on the basis in effect ------------------------------------
    # Derived by `channel_pnl`, not here. This route used to subtract its own
    # profit and choose its own denominator with a three-way `if`, which made
    # it a second implementation of the percentage `CostingService.margin`
    # already owns -- the divergence Constitution III forbids (task T160).
    policy = await resolve_cost_policy(db, tenant)
    margin = channel_pnl.period_margin(
        revenue_tax_exclusive=revenue,
        shipping_revenue=shipping_revenue,
        planned_fee_total=planned_fee_total,
        postage_paid=postage,
        absorbed_costs=absorbed,
        basis=resolve_margin_basis(policy),
    )
    profit = margin.profit
    margin_pct = margin.margin_pct

    return ChannelPnLResponse(
        channel_id=channel.id,
        period_start=period_start,
        period_end=period_end,
        order_count=len(orders),
        revenue_tax_exclusive=revenue.quantize(CENT),
        sales_tax_collected=tax_collected.quantize(CENT),
        sales_tax_liability=(
            tax_collected.quantize(CENT) if channel.tax_remitter == "operator" else ZERO
        ),
        postage_paid=postage.quantize(CENT),
        shipping_revenue=shipping_revenue.quantize(CENT),
        shipping_net=(shipping_revenue - postage).quantize(CENT),
        planned_fee_total=planned_fee_total.quantize(CENT),
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
        # The period's make-cost needs the snapshot Tier 3 writes at the moment
        # of sale (FR-036); until then it is reported as zero rather than
        # recomputed from today's inputs, which would restate history.
        make_cost_total=ZERO,
        profit=profit.quantize(CENT),
        margin_pct=margin_pct,
        margin_basis=margin.basis,
        margin_basis_label=margin.basis_label,
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
