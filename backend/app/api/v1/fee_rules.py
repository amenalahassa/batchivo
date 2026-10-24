"""Fee rule endpoints (task T076).

The permission split is FR-007a's: fee rules are monetary policy, so writing
one needs admin or owner, while reading is open to every role -- a viewer
cannot judge a margin without seeing the fees behind it (FR-007c). The preview
endpoint is a read in every sense except its HTTP verb: it creates nothing and
is open to member, because inspecting what a hypothetical order would be
charged is how an operator checks a rule before trusting it.

Overlap is refused rather than resolved (FR-022). Two rules of the same name on
one channel whose date ranges intersect would both be charged, silently
doubling that fee; the operator is told which existing rule conflicts so they
can close it rather than guess.

A rule is superseded, never edited (FR-022, FR-003, task T233). Changing what a
rule charges -- its rate, fixed amount, clamps, incidence or basis -- closes
the current row the day before the change takes effect and opens a new one,
so a past date's preview, a closed period's P&L and a scenario's inputs read
the figures that were in force then. A rule may be deleted only while nothing
has been priced under it; one that has is closed instead.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB, RequireMember
from app.models.fee_actual import FeeActual
from app.models.fee_rule import FeeRule
from app.models.order import Order
from app.models.sales_channel import SalesChannel
from app.schemas.fee_rule import (
    FeeChargeResponse,
    FeePreviewRequest,
    FeePreviewResponse,
    FeeRuleCreate,
    FeeRuleListResponse,
    FeeRuleResponse,
    FeeRuleUpdate,
)
from app.services import fee_engine
from app.services.fee_engine import FeeRuleInvalid

logger = logging.getLogger(__name__)

router = APIRouter()


async def _channel_or_404(
    db: AsyncSession,
    tenant: CurrentTenant,
    channel_id: UUID,
) -> SalesChannel:
    """The channel, scoped to the tenant.

    Scoped explicitly as well as by RLS: `rls_enabled` is off in development,
    and a tenant filter that only exists in a database policy is a tenant
    filter that disappears on a developer's machine (Constitution I).
    """
    result = await db.execute(
        select(SalesChannel).where(
            SalesChannel.id == channel_id,
            SalesChannel.tenant_id == tenant.id,
        )
    )
    channel = result.scalars().first()
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sales channel not found",
        )
    return channel


async def _rules_for(
    db: AsyncSession,
    channel_id: UUID,
    tenant_id: UUID,
) -> list[FeeRule]:
    result = await db.execute(
        select(FeeRule)
        .where(FeeRule.sales_channel_id == channel_id, FeeRule.tenant_id == tenant_id)
        .order_by(FeeRule.sort_order, FeeRule.name)
    )
    return list(result.scalars().all())


def _ranges_overlap(
    from_a: date,
    to_a: Optional[date],
    from_b: date,
    to_b: Optional[date],
) -> bool:
    """Whether two effective periods intersect, treating null as open-ended."""
    if to_a is not None and to_a < from_b:
        return False
    if to_b is not None and to_b < from_a:
        return False
    return True


async def _refuse_overlap(
    db: AsyncSession,
    channel: SalesChannel,
    *,
    name: str,
    applies_from: date,
    applies_to: Optional[date],
    exclude_id: Optional[UUID] = None,
) -> None:
    """FR-022: two rules of the same name must not overlap on dates."""
    for existing in await _rules_for(db, channel.id, channel.tenant_id):
        if existing.id == exclude_id or existing.name != name:
            continue
        if _ranges_overlap(applies_from, applies_to, existing.applies_from, existing.applies_to):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"a rule named {name!r} already applies from "
                    f"{existing.applies_from} to {existing.applies_to or 'now'}; "
                    "close that one before opening another, or both would be charged"
                ),
            )


#: The fields that say what a rule charges. Changing any of them supersedes
#: the rule; the rest -- its name, its order on the screen, its dates -- are
#: how it is presented and when it applies, and are corrected in place.
CHARGE_FIELDS: frozenset[str] = frozenset(
    {"basis", "rate_pct", "fixed_amount", "min_amount", "max_amount", "incidence_pct"}
)


def _same(old: object, new: object) -> bool:
    """Whether a rule's figure is unchanged, comparing amounts as decimals."""
    if old is None or new is None:
        return old is new
    if isinstance(old, str) or isinstance(new, str):
        return old == new
    return Decimal(str(old)) == Decimal(str(new))


def _start_of(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


async def _rule_has_been_used(db: AsyncSession, channel: SalesChannel, rule: FeeRule) -> bool:
    """Whether anything has been priced or reconciled under this rule.

    An order placed on the channel while the rule was in force was priced
    under it, and a recorded actual in its category was reconciled against it.
    Either makes the rule part of a record that must stay reproducible.
    """
    orders = select(Order.id).where(
        Order.tenant_id == channel.tenant_id,
        Order.sales_channel_id == channel.id,
        Order.created_at >= _start_of(rule.applies_from),
    )
    if rule.applies_to is not None:
        orders = orders.where(Order.created_at < _start_of(rule.applies_to + timedelta(days=1)))
    if (await db.execute(orders.limit(1))).first() is not None:
        return True

    actuals = select(FeeActual.id).where(
        FeeActual.tenant_id == channel.tenant_id,
        FeeActual.sales_channel_id == channel.id,
        FeeActual.fee_category == rule.name,
    )
    return (await db.execute(actuals.limit(1))).first() is not None


def _validate(
    *,
    basis: str,
    rate_pct: Optional[Decimal],
    min_amount: Optional[Decimal],
    max_amount: Optional[Decimal],
    incidence_pct: Optional[Decimal],
) -> None:
    """Run the engine's own validation, so one definition of valid exists."""
    try:
        fee_engine.validate_rule(
            basis=basis,
            rate_pct=rate_pct,
            min_amount=min_amount,
            max_amount=max_amount,
            incidence_pct=incidence_pct,
        )
    except FeeRuleInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/{channel_id}/fee-rules", response_model=FeeRuleListResponse)
async def list_fee_rules(
    channel_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    as_of: Optional[date] = Query(
        None, description="Return the rules in effect on this date instead of all of them"
    ),
) -> FeeRuleListResponse:
    """The channel's fee rules in ``sort_order``.

    Without ``as_of`` every rule is returned, including closed ones: an
    operator reconciling a statement from March needs to see the rule that
    applied in March as well as the one that applies now.
    """
    channel = await _channel_or_404(db, tenant, channel_id)
    rules = await _rules_for(db, channel.id, tenant.id)
    reference = as_of or clock.today()
    if as_of is not None:
        rules = fee_engine.rules_in_effect(rules, as_of)

    return FeeRuleListResponse(
        rules=[FeeRuleResponse.model_validate(rule) for rule in rules],
        total=len(rules),
        as_of=reference,
    )


@router.post(
    "/{channel_id}/fee-rules",
    response_model=FeeRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_fee_rule(
    channel_id: UUID,
    payload: FeeRuleCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> FeeRuleResponse:
    """Add a fee rule. Requires admin or owner (FR-007a)."""
    channel = await _channel_or_404(db, tenant, channel_id)
    _validate(
        basis=payload.basis,
        rate_pct=payload.rate_pct,
        min_amount=payload.min_amount,
        max_amount=payload.max_amount,
        incidence_pct=payload.incidence_pct,
    )
    await _refuse_overlap(
        db,
        channel,
        name=payload.name,
        applies_from=payload.applies_from,
        applies_to=payload.applies_to,
    )

    rule = FeeRule(
        tenant_id=tenant.id,
        sales_channel_id=channel.id,
        **payload.model_dump(),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    logger.info(f"Created fee rule {rule.name} on channel {channel.id}")
    return FeeRuleResponse.model_validate(rule)


@router.put("/{channel_id}/fee-rules/{rule_id}", response_model=FeeRuleResponse)
async def update_fee_rule(
    channel_id: UUID,
    rule_id: UUID,
    payload: FeeRuleUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> FeeRuleResponse:
    """Change a fee rule. Requires admin or owner (FR-007a).

    A change to what the rule charges supersedes it (task T233): the current
    row closes the day before ``effective_from`` -- today by default -- and
    the response is the new row that opens on it. Only a rule nothing has yet
    been priced under, changed from its own first day, is corrected in place.
    A change to the name, order or dates alone is a correction to how the rule
    is presented and is made in place.
    """
    channel = await _channel_or_404(db, tenant, channel_id)
    result = await db.execute(
        select(FeeRule).where(
            FeeRule.id == rule_id,
            FeeRule.sales_channel_id == channel.id,
            FeeRule.tenant_id == tenant.id,
        )
    )
    rule = result.scalars().first()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fee rule not found")

    changes = payload.changes()
    opens_on = changes.pop("effective_from", None) or clock.today()
    merged = {
        "basis": changes.get("basis", rule.basis),
        "rate_pct": changes.get("rate_pct", rule.rate_pct),
        "min_amount": changes.get("min_amount", rule.min_amount),
        "max_amount": changes.get("max_amount", rule.max_amount),
        "incidence_pct": changes.get("incidence_pct", rule.incidence_pct),
    }
    _validate(**merged)

    moved = sorted(
        field
        for field in CHARGE_FIELDS & set(changes)
        if not _same(getattr(rule, field), changes[field])
    )

    in_place = not moved or (
        opens_on <= rule.applies_from and not await _rule_has_been_used(db, channel, rule)
    )
    if in_place:
        await _refuse_overlap(
            db,
            channel,
            name=changes.get("name", rule.name),
            applies_from=changes.get("applies_from", rule.applies_from),
            applies_to=changes.get("applies_to", rule.applies_to),
            exclude_id=rule.id,
        )
        for field, value in changes.items():
            setattr(rule, field, value)
        await db.commit()
        await db.refresh(rule)
        logger.info(f"Corrected fee rule {rule.id} on channel {channel.id} in place")
        return FeeRuleResponse.model_validate(rule)

    if opens_on <= rule.applies_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"orders have been priced under this rule since {rule.applies_from}, so a "
                f"change to what it charges must take effect after that day; give an "
                f"effective_from later than {rule.applies_from}"
            ),
        )
    if rule.applies_to is not None and opens_on > rule.applies_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"this rule closed on {rule.applies_to}; open a new rule rather than "
                f"superseding a closed one"
            ),
        )

    successor = FeeRule(
        tenant_id=tenant.id,
        sales_channel_id=channel.id,
        name=changes.get("name", rule.name),
        basis=merged["basis"],
        rate_pct=merged["rate_pct"],
        fixed_amount=changes.get("fixed_amount", rule.fixed_amount),
        min_amount=merged["min_amount"],
        max_amount=merged["max_amount"],
        incidence_pct=merged["incidence_pct"],
        sort_order=changes.get("sort_order", rule.sort_order),
        applies_from=opens_on,
        applies_to=changes.get("applies_to", rule.applies_to),
    )
    rule.applies_to = opens_on - timedelta(days=1)
    await db.flush()
    await _refuse_overlap(
        db,
        channel,
        name=successor.name,
        applies_from=successor.applies_from,
        applies_to=successor.applies_to,
        exclude_id=rule.id,
    )
    db.add(successor)
    await db.commit()
    await db.refresh(successor)
    logger.info(
        f"Superseded fee rule {rule.id} on channel {channel.id} from {opens_on} "
        f"(changed: {', '.join(moved)})"
    )
    return FeeRuleResponse.model_validate(successor)


@router.delete("/{channel_id}/fee-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fee_rule(
    channel_id: UUID,
    rule_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> None:
    """Remove a fee rule. Requires admin or owner (FR-007a).

    Deleted only while nothing has been priced or reconciled under it -- a
    rule entered by mistake (task T233). A rule an order or a recorded actual
    already used is closed instead, from today, so the orders priced under it
    stay reproducible; deleting it would make them unexplainable.
    """
    channel = await _channel_or_404(db, tenant, channel_id)
    result = await db.execute(
        select(FeeRule).where(
            FeeRule.id == rule_id,
            FeeRule.sales_channel_id == channel.id,
            FeeRule.tenant_id == tenant.id,
        )
    )
    rule = result.scalars().first()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fee rule not found")

    if await _rule_has_been_used(db, channel, rule):
        today = clock.today()
        if rule.applies_to is None or rule.applies_to > today:
            rule.applies_to = max(today, rule.applies_from)
        await db.commit()
        logger.info(
            f"Closed fee rule {rule_id} on channel {channel.id} from {rule.applies_to}: "
            f"orders were priced under it, so it was kept rather than deleted"
        )
        return

    await db.delete(rule)
    await db.commit()
    logger.info(f"Deleted fee rule {rule_id} from channel {channel.id}")


@router.post("/{channel_id}/fee-rules/preview", response_model=FeePreviewResponse)
async def preview_fee_rules(
    channel_id: UUID,
    payload: FeePreviewRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> FeePreviewResponse:
    """What a hypothetical order would be charged.

    Creates nothing, which is why it is open to member: the fee engine made
    inspectable is how an operator checks a rule before believing a margin
    built on it (FR-018).
    """
    channel = await _channel_or_404(db, tenant, channel_id)
    rules = await _rules_for(db, channel.id, tenant.id)
    reference = payload.as_of or clock.today()

    context, treatment = fee_engine.exclusive_context(
        item_subtotal=payload.item_subtotal,
        shipping_revenue=payload.shipping_revenue,
        extras=payload.extras,
        sales_tax_collected=payload.sales_tax_collected,
        tax_inclusive=payload.amounts_are_tax_inclusive,
        quantity=payload.quantity,
        listings=payload.listings,
    )
    stack = fee_engine.compute(channel, context, reference, rules=rules)

    return FeePreviewResponse(
        charges=[FeeChargeResponse.model_validate(c) for c in stack.charges],
        total=stack.total,
        periodic=[FeeChargeResponse.model_validate(c) for c in stack.periodic],
        periodic_total=stack.periodic_total,
        bound_clamps=stack.bound_clamps,
        as_of=reference,
        revenue_tax_exclusive=(context.item_subtotal + context.shipping_revenue).quantize(
            Decimal("0.01")
        ),
        tax_exclusive_derived=treatment.derived_from_inclusive,
    )
