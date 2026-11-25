"""Settings → AI: the tenant's Replicate token, monthly budget and model overrides (spec 008).

Owners and admins only (clarification Q3), like the other integrations. The
token is write-only: responses show its last four characters at most (FR-021).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB
from app.schemas.tenant_settings import (
    ReplicateConnectionTest,
    ReplicateSettingsResponse,
    ReplicateSettingsUpdate,
    ReplicateUsageResponse,
)
from app.services.tenant_settings import TenantSettingsService

router = APIRouter()


def _refused(errors: list[dict]) -> HTTPException:
    return HTTPException(status_code=422, detail=errors)


async def _settings_update(request: Request) -> ReplicateSettingsUpdate:
    """The request body, validated without echoing what was sent (FR-021, SC-006).

    FastAPI's own 422 repeats each refused value, which here could be a token.
    """
    try:
        payload = await request.json()
    except ValueError:
        raise _refused([{"loc": ["body"], "msg": "Invalid JSON", "type": "json_invalid"}])
    try:
        return ReplicateSettingsUpdate.model_validate(payload)
    except ValidationError as exc:
        raise _refused(
            [
                {"loc": ["body", *error["loc"]], "msg": error["msg"], "type": error["type"]}
                for error in exc.errors(
                    include_url=False, include_input=False, include_context=False
                )
            ]
        ) from None


SettingsUpdate = Annotated[ReplicateSettingsUpdate, Depends(_settings_update)]


@router.get("", response_model=ReplicateSettingsResponse)
async def get_replicate_settings(
    user: CurrentUser, tenant: CurrentTenant, _admin: RequireAdmin, db: TenantDB
) -> ReplicateSettingsResponse:
    """The Replicate settings with the token masked and this month's usage in USD."""
    return await TenantSettingsService(db).get_replicate_settings(tenant.id)


@router.put("", response_model=ReplicateSettingsResponse)
async def update_replicate_settings(
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
    # After the auth checks: FastAPI resolves dependencies in order, so a bad body
    # from a member or a stranger gets 403 / 401, not 422.
    data: SettingsUpdate,
) -> ReplicateSettingsResponse:
    """Save the token (encrypted), the monthly budget and model overrides."""
    return await TenantSettingsService(db).update_replicate_settings(tenant.id, data)


@router.post("/test", response_model=ReplicateConnectionTest)
async def test_replicate_connection(
    user: CurrentUser, tenant: CurrentTenant, _admin: RequireAdmin, db: TenantDB
) -> ReplicateConnectionTest:
    """Check that the token in use is accepted by Replicate."""
    return await TenantSettingsService(db).test_replicate_connection(tenant.id)


@router.get("/usage", response_model=ReplicateUsageResponse)
async def replicate_usage(
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
    months: int = Query(6, ge=1, le=24),
) -> ReplicateUsageResponse:
    """Spend and job count per calendar month, newest first."""
    return await TenantSettingsService(db).replicate_usage(tenant.id, months)


__all__ = ["router"]
