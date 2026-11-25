"""Platform admin switch: may this shop use the platform's Replicate token? (clarification Q2)

Off by default. Only a platform admin grants it, one shop at a time; each change
is written to the platform audit log. A single-shop VPS install authorises its
only shop through configuration (``GENAI_PLATFORM_TOKEN_ALL_TENANTS``) instead.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.auth.dependencies import PlatformAdmin, PlatformAdminDB
from app.config import get_settings
from app.models.platform_admin import PlatformAdminAuditLog
from app.models.tenant import Tenant
from app.schemas.genai import PlatformGenaiSettings, PlatformGenaiUpdate
from app.services.genai import credentials

router = APIRouter()


def _response(tenant: Tenant) -> PlatformGenaiSettings:
    settings = get_settings()
    return PlatformGenaiSettings(
        tenant_id=tenant.id,
        platform_token_allowed=bool(
            credentials.replicate_config(tenant).get("platform_token_allowed")
        ),
        platform_token_available=credentials.platform_token(settings) is not None,
        all_tenants=settings.genai_platform_token_all_tenants,
    )


async def _tenant(db, tenant_id: uuid.UUID) -> Tenant:
    tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.get("/tenants/{tenant_id}/genai", response_model=PlatformGenaiSettings)
async def get_platform_genai(
    tenant_id: uuid.UUID, admin: PlatformAdmin, db: PlatformAdminDB
) -> PlatformGenaiSettings:
    """Whether this shop may use the platform token."""
    return _response(await _tenant(db, tenant_id))


@router.put("/tenants/{tenant_id}/genai", response_model=PlatformGenaiSettings)
async def set_platform_genai(
    tenant_id: uuid.UUID,
    data: PlatformGenaiUpdate,
    request: Request,
    admin: PlatformAdmin,
    db: PlatformAdminDB,
) -> PlatformGenaiSettings:
    """Allow or refuse the platform token for this shop, with an audit entry."""
    tenant = await _tenant(db, tenant_id)
    current = dict(tenant.settings or {})
    config = dict(current.get("replicate") or {})
    before = bool(config.get("platform_token_allowed"))
    config["platform_token_allowed"] = data.platform_token_allowed
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    current["replicate"] = config
    tenant.settings = current
    db.add(
        PlatformAdminAuditLog(
            admin_user_id=admin.id,
            action="genai_platform_token",
            target_type="tenant",
            target_id=tenant.id,
            action_metadata={"before": before, "after": data.platform_token_allowed},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    )
    await db.commit()
    await db.refresh(tenant)
    return _response(tenant)


__all__ = ["router"]
