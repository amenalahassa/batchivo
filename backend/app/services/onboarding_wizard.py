"""The setup wizard a new tenant runs after verifying their email.

Progress lives in `tenant.settings["onboarding"]`. A tenant without that key
signed up before the wizard existed and is treated as finished, so nobody who
already uses the console is sent back through it. Every step writes through
the path the settings screens use, so the wizard keeps no second copy of how a
name, a currency or a brand colour is stored.
"""

import logging
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provenance_http import record_operator_origins
from app.auth.dependencies import role_in_tenant
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.onboarding import (
    OnboardingStatusResponse,
    OnboardingStep1Request,
    OnboardingStep2Request,
    OnboardingStep3Request,
    OnboardingStepResponse,
)
from app.schemas.tenant_settings import (
    BrandingSettingsUpdate,
    ShopSettingsUpdate,
    TenantSettings,
    TenantUpdate,
)
from app.services.tenant_module_service import TenantModuleService
from app.services.tenant_settings import TenantSettingsService

logger = logging.getLogger(__name__)

LAST_STEP = 4


def new_wizard_progress() -> dict[str, Any]:
    """The progress a freshly verified tenant starts with."""
    return {"current_step": 1, "completed_steps": [], "is_completed": False, "step_data": {}}


def _progress(tenant: Tenant) -> dict[str, Any]:
    stored = (tenant.settings or {}).get("onboarding")
    if stored is None:
        # Signed up before the wizard: finished by definition.
        return {"current_step": LAST_STEP, "completed_steps": [], "is_completed": True}
    return stored


class OnboardingWizardService:
    """Reads and advances one tenant's setup wizard."""

    def __init__(self, db: AsyncSession, tenant: Tenant, user: User):
        self.db = db
        self.tenant = tenant
        self.user = user
        self.settings = TenantSettingsService(db)

    def status(self) -> OnboardingStatusResponse:
        progress = _progress(self.tenant)
        return OnboardingStatusResponse(
            current_step=progress["current_step"],
            completed_steps=progress.get("completed_steps", []),
            is_completed=progress["is_completed"],
            step_data=progress.get("step_data"),
            tenant_id=self.tenant.id,
            tenant_name=self.tenant.name,
            tenant_type=self.tenant.tenant_type,
        )

    async def save_step1(self, data: OnboardingStep1Request) -> OnboardingStepResponse:
        if data.slug and data.slug != self.tenant.slug:
            taken = await self.db.execute(
                select(Tenant.id).where(Tenant.slug == data.slug, Tenant.id != self.tenant.id)
            )
            if taken.scalar_one_or_none():
                raise HTTPException(status.HTTP_409_CONFLICT, f"The address '{data.slug}' is taken")
            await self.db.execute(
                update(Tenant).where(Tenant.id == self.tenant.id).values(slug=data.slug)
            )
        await self.settings.update_tenant(
            self.tenant.id,
            TenantUpdate(name=data.business_name, description=data.business_description),
        )
        return await self._complete(1, data.model_dump(exclude_none=True))

    async def save_step2(self, data: OnboardingStep2Request) -> OnboardingStepResponse:
        """Set the kind of business, which decides labels, features and modules.

        Only while the wizard is open: afterwards the modules may hold data, and
        resetting them is not a setup step.
        """
        if _progress(self.tenant)["is_completed"]:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "The business type is set during setup only"
            )
        new_type = data.tenant_type.value
        if new_type != self.tenant.tenant_type:
            defaults = TenantSettings.for_tenant_type(data.tenant_type).model_dump()
            settings = dict(self.tenant.settings or {})
            for key in ("tenant_type", "labels", "features"):
                settings[key] = defaults[key]
            await self.db.execute(
                update(Tenant)
                .where(Tenant.id == self.tenant.id)
                .values(tenant_type=new_type, settings=settings)
            )
            await self.db.refresh(self.tenant)
            await TenantModuleService(db=self.db).reset_to_defaults(self.tenant.id)
            await self.db.commit()
            logger.info(f"Tenant {self.tenant.id} set its business type to {new_type}")
        return await self._complete(2, {"tenant_type": new_type})

    async def save_step3(self, data: OnboardingStep3Request) -> OnboardingStepResponse:
        if data.currency and data.currency != self.tenant.currency_code:
            # The books currency is monetary policy: record who chose it (T272).
            await record_operator_origins(
                self.db,
                self.tenant,
                entity_type="tenant",
                entity_id=self.tenant.id,
                fields=["currency_code"],
                user=self.user,
                role=await role_in_tenant(self.db, self.user.id, self.tenant.id),
            )
            await self.settings.update_tenant(
                self.tenant.id,
                TenantUpdate(currency_code=data.currency, currency_symbol=data.currency_symbol),
            )
        if data.shop_display_name:
            await self.settings.update_shop_settings(
                self.tenant.id, ShopSettingsUpdate(shop_name=data.shop_display_name)
            )
        if data.primary_color:
            await self.settings.update_branding_settings(
                self.tenant.id, BrandingSettingsUpdate(primary_color=data.primary_color)
            )
        if data.timezone:
            await self.db.refresh(self.tenant)
            settings = dict(self.tenant.settings or {})
            settings["localization"] = {
                **settings.get("localization", {}),
                "timezone": data.timezone,
            }
            await self._write_settings(settings)
        return await self._complete(3, data.model_dump(exclude_none=True))

    async def finish(self, step_data: Optional[dict[str, Any]] = None) -> OnboardingStepResponse:
        """Step 4: the first product (or its skip) has been dealt with."""
        return await self._complete(LAST_STEP, step_data or {})

    async def set_logo(self, logo_url: str) -> None:
        await self.settings.update_branding_settings(
            self.tenant.id, BrandingSettingsUpdate(logo_url=logo_url)
        )

    async def _complete(self, step: int, step_data: dict[str, Any]) -> OnboardingStepResponse:
        await self.db.refresh(self.tenant)
        progress = dict(_progress(self.tenant))
        progress["completed_steps"] = sorted(set(progress.get("completed_steps", [])) | {step})
        progress["step_data"] = {**progress.get("step_data", {}), f"step_{step}": step_data}
        finished = step == LAST_STEP or progress["is_completed"]
        progress["is_completed"] = finished
        progress["current_step"] = LAST_STEP if finished else step + 1
        settings = dict(self.tenant.settings or {})
        settings["onboarding"] = progress
        await self._write_settings(settings)
        return OnboardingStepResponse(
            message=f"Step {step} saved",
            step_completed=step,
            next_step=None if finished else step + 1,
            is_completed=finished,
        )

    async def _write_settings(self, settings: dict[str, Any]) -> None:
        await self.db.execute(
            update(Tenant).where(Tenant.id == self.tenant.id).values(settings=settings)
        )
        await self.db.commit()
        await self.db.refresh(self.tenant)
