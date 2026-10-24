"""Tenant pricing policy endpoints (task T047).

Reading is open to every role — a viewer cannot price anything without knowing
the rates behind the figures they are looking at. Writing needs admin or owner,
and writes a *new* effective row rather than editing one (FR-003), so the rate
an order was costed at stays readable after the rate changes.
"""

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB, role_in_tenant
from app.schemas.pricing_policy import PricingPolicyResponse, PricingPolicyUpdate
from app.services.pricing_policy import (
    PolicyMisconfigured,
    cost_policy_from_row,
    legacy_cost_policy,
    resolve_policy_row,
    write_policy,
)

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
        source=policy.source,
    )


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

    if row is None:
        return _response(legacy_cost_policy(tenant))

    policy = cost_policy_from_row(row)
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
    role = await role_in_tenant(db, user.id, tenant.id)
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

    policy = cost_policy_from_row(row)
    return _response(policy, effective_to=row.effective_to, set_by_role=row.set_by_role)
