"""Tenant pricing policy endpoints (task T047).

Reading is open to every role — a viewer cannot price anything without knowing
the rates behind the figures they are looking at. Writing needs admin or owner,
and writes a *new* effective row rather than editing one (FR-003), so the rate
an order was costed at stays readable after the rate changes.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB
from app.models.user import UserTenant
from app.schemas.pricing_policy import PricingPolicyResponse, PricingPolicyUpdate
from app.services.pricing_policy import (
    PolicyMisconfigured,
    cost_policy_from_row,
    legacy_cost_policy,
    resolve_policy_row,
    write_policy,
)
from app.services.tenant_cost_settings import tenant_overhead_percentage

logger = logging.getLogger(__name__)

router = APIRouter()


def _response(
    policy,
    *,
    effective_to: Optional[date] = None,
    set_by_role: Optional[str] = None,
) -> PricingPolicyResponse:
    """Render a :class:`CostPolicy` snapshot as the API response."""
    return PricingPolicyResponse(
        print_labor_rate=policy.print_labor_rate,
        finishing_labor_rate=policy.finishing_labor_rate,
        default_machine_rate_per_hour=policy.default_machine_rate_per_hour,
        overhead_method=policy.overhead_method,
        overhead_monthly_pool=policy.overhead_monthly_pool,
        expected_monthly_machine_hours=policy.expected_monthly_machine_hours,
        overhead_rate_per_machine_hour=policy.overhead_rate_per_machine_hour,
        overhead_percentage=policy.overhead_percentage,
        electricity_rate_per_kwh=policy.electricity_rate_per_kwh,
        margin_basis=policy.margin_basis,
        default_target_margin_pct=policy.default_target_margin_pct,
        rounding_rule=policy.rounding_rule,
        sales_tax_recoverable=policy.sales_tax_recoverable,
        staleness_threshold_days=policy.staleness_threshold_days,
        margin_alert_threshold_pct=policy.margin_alert_threshold_pct,
        min_outcomes_before_auto_update=policy.min_outcomes_before_auto_update,
        estimate_divergence_threshold_pct=policy.estimate_divergence_threshold_pct,
        origin=policy.origin,
        effective_from=policy.effective_from,
        effective_to=effective_to,
        set_by_role=set_by_role,
    )


async def _role_in_tenant(db: AsyncSession, user_id, tenant_id) -> Optional[str]:
    """The role this user holds in this tenant, for FR-007a's audit field."""
    result = await db.execute(
        select(UserTenant.role).where(
            UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id
        )
    )
    role = result.scalars().first()
    return getattr(role, "value", role)


@router.get("/pricing-policy", response_model=PricingPolicyResponse)
async def get_pricing_policy(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    as_of: Optional[date] = Query(
        None, description="Read the policy in effect on this date instead of today"
    ),
) -> PricingPolicyResponse:
    """The pricing policy in effect, today or on ``as_of``.

    Available to every role. A tenant with no policy row yet gets the figures
    from their legacy settings, labelled ``legacy_settings`` so nobody mistakes
    a fallback for a decision (FR-050).
    """
    row = await resolve_policy_row(db, tenant, as_of)
    overhead_percentage: Decimal = tenant_overhead_percentage(tenant)

    if row is None:
        policy = legacy_cost_policy(tenant)
        return _response(policy.with_overhead_percentage(overhead_percentage))

    policy = cost_policy_from_row(row, overhead_percentage=overhead_percentage)
    return _response(policy, effective_to=row.effective_to, set_by_role=row.set_by_role)


@router.put("/pricing-policy", response_model=PricingPolicyResponse)
async def update_pricing_policy(
    changes: PricingPolicyUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> PricingPolicyResponse:
    """Change one or more levers, writing a new effective row.

    Requires admin or owner. Levers the body does not name are copied forward
    from the current row, and the superseded row is closed rather than edited.
    """
    role = await _role_in_tenant(db, user.id, tenant.id)
    try:
        row = await write_policy(
            db,
            tenant,
            changes.changes(),
            user=user,
            role=role,
            effective_from=changes.effective_from,
        )
    except PolicyMisconfigured as exc:
        # A policy that could not be used once stored is a validation failure,
        # not a server error: the operator can fix the body and try again.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    await db.commit()
    await db.refresh(row)

    policy = cost_policy_from_row(row, overhead_percentage=tenant_overhead_percentage(tenant))
    return _response(policy, effective_to=row.effective_to, set_by_role=row.set_by_role)
