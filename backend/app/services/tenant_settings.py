"""Service for managing tenant settings with secure credential storage."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from square import Square
from square.core.api_error import ApiError

from app.core.encryption import encrypt_value, mask_credential, safe_decrypt
from app.models.tenant import Tenant
from app.services.square_payment import get_square_environment
from app.schemas.tenant_settings import (
    BrandingSettingsResponse,
    BrandingSettingsUpdate,
    EtsyConnectionTest,
    EtsySettingsResponse,
    EtsySettingsUpdate,
    ShopSettingsResponse,
    ShopSettingsUpdate,
    SquareConnectionTest,
    SquareSettingsResponse,
    SquareSettingsUpdate,
    ReplicateConnectionTest,
    ReplicateSettingsResponse,
    ReplicateSettingsUpdate,
    ReplicateUsageMonth,
    ReplicateUsageResponse,
    TenantResponse,
    TenantUpdate,
)


class TenantSettingsService:
    """Service for managing tenant settings."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # Square Settings
    # =========================================================================

    async def get_square_settings(self, tenant_id: UUID) -> SquareSettingsResponse:
        """Get Square payment settings for a tenant (with masked credentials).

        Args:
            tenant_id: The tenant's UUID

        Returns:
            SquareSettingsResponse with masked credentials
        """
        tenant = await self._get_tenant(tenant_id)
        square_config = tenant.settings.get("square", {})

        # Decrypt and mask credentials
        access_token = safe_decrypt(square_config.get("access_token_encrypted", ""))
        location_id = safe_decrypt(square_config.get("location_id_encrypted", ""))

        # Check if configured
        is_configured = bool(access_token and location_id)

        return SquareSettingsResponse(
            enabled=square_config.get("enabled", False),
            environment=square_config.get("environment", "sandbox"),
            is_configured=is_configured,
            access_token_masked=mask_credential(access_token) if access_token else None,
            app_id=square_config.get("app_id"),
            location_id_masked=mask_credential(location_id) if location_id else None,
            updated_at=square_config.get("updated_at"),
        )

    async def update_square_settings(
        self, tenant_id: UUID, data: SquareSettingsUpdate
    ) -> SquareSettingsResponse:
        """Update Square payment settings for a tenant.

        Args:
            tenant_id: The tenant's UUID
            data: The settings update data

        Returns:
            Updated SquareSettingsResponse
        """
        tenant = await self._get_tenant(tenant_id)

        # Get existing settings or create new
        current_settings = dict(tenant.settings)
        square_config = dict(current_settings.get("square", {}))

        # Update provided fields
        if data.enabled is not None:
            square_config["enabled"] = data.enabled

        if data.environment is not None:
            square_config["environment"] = data.environment

        if data.app_id is not None:
            square_config["app_id"] = data.app_id

        # Encrypt sensitive credentials
        if data.access_token is not None:
            square_config["access_token_encrypted"] = encrypt_value(data.access_token)

        if data.location_id is not None:
            square_config["location_id_encrypted"] = encrypt_value(data.location_id)

        # Update timestamp
        square_config["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Save to database
        current_settings["square"] = square_config
        await self._update_tenant_settings(tenant_id, current_settings)

        return await self.get_square_settings(tenant_id)

    async def test_square_connection(self, tenant_id: UUID) -> SquareConnectionTest:
        """Test the Square connection using tenant's credentials.

        Args:
            tenant_id: The tenant's UUID

        Returns:
            SquareConnectionTest with result details
        """
        tenant = await self._get_tenant(tenant_id)
        square_config = tenant.settings.get("square", {})

        # Get decrypted credentials
        access_token = safe_decrypt(square_config.get("access_token_encrypted", ""))
        location_id = safe_decrypt(square_config.get("location_id_encrypted", ""))
        environment = square_config.get("environment", "sandbox")

        if not access_token or not location_id:
            return SquareConnectionTest(
                success=False,
                message="Square credentials are not configured",
                environment=environment,
            )

        try:
            # Initialize Square client
            client = Square(
                token=access_token,
                environment=get_square_environment(environment),
            )

            # Test by fetching the location
            result = client.locations.get(location_id=location_id)
            location = result.location

            return SquareConnectionTest(
                success=True,
                message="Successfully connected to Square",
                environment=environment,
                location_name=location.name if location else None,
            )

        except ApiError as e:
            errors = e.errors or []
            error_msg = errors[0].detail if errors else "Unknown error"
            return SquareConnectionTest(
                success=False,
                message=f"Square API error: {error_msg}",
                environment=environment,
            )

        except Exception as e:
            return SquareConnectionTest(
                success=False,
                message=f"Connection failed: {str(e)}",
                environment=environment,
            )

    def get_square_credentials_for_payment(
        self, tenant_settings: dict
    ) -> tuple[str, str, str] | None:
        """Get decrypted Square credentials for payment processing.

        This method is used by the payment service to get credentials
        without an async context.

        Args:
            tenant_settings: The tenant's settings dict

        Returns:
            Tuple of (access_token, location_id, environment) or None if not configured
        """
        square_config = tenant_settings.get("square", {})

        if not square_config.get("enabled", False):
            return None

        access_token = safe_decrypt(square_config.get("access_token_encrypted", ""))
        location_id = safe_decrypt(square_config.get("location_id_encrypted", ""))
        environment = square_config.get("environment", "sandbox")

        if not access_token or not location_id:
            return None

        return (access_token, location_id, environment)

    # =========================================================================
    # Etsy Settings
    # =========================================================================

    async def get_etsy_settings(self, tenant_id: UUID) -> EtsySettingsResponse:
        """Get Etsy marketplace settings for a tenant (with masked credentials).

        Args:
            tenant_id: The tenant's UUID

        Returns:
            EtsySettingsResponse with masked credentials
        """
        tenant = await self._get_tenant(tenant_id)
        etsy_config = tenant.settings.get("etsy", {})

        # Decrypt and mask credentials
        api_key = safe_decrypt(etsy_config.get("api_key_encrypted", ""))
        shared_secret = safe_decrypt(etsy_config.get("shared_secret_encrypted", ""))
        access_token = safe_decrypt(etsy_config.get("access_token_encrypted", ""))
        refresh_token = safe_decrypt(etsy_config.get("refresh_token_encrypted", ""))

        # Check if configured (need at least api_key, access_token, and shop_id)
        shop_id = etsy_config.get("shop_id")
        is_configured = bool(api_key and access_token and shop_id)

        return EtsySettingsResponse(
            enabled=etsy_config.get("enabled", False),
            is_configured=is_configured,
            api_key_masked=mask_credential(api_key) if api_key else None,
            shared_secret_masked=mask_credential(shared_secret) if shared_secret else None,
            access_token_masked=mask_credential(access_token) if access_token else None,
            refresh_token_set=bool(refresh_token),
            shop_id=shop_id,
            shop_name=etsy_config.get("shop_name"),
            updated_at=etsy_config.get("updated_at"),
        )

    async def update_etsy_settings(
        self, tenant_id: UUID, data: EtsySettingsUpdate
    ) -> EtsySettingsResponse:
        """Update Etsy marketplace settings for a tenant.

        Args:
            tenant_id: The tenant's UUID
            data: The settings update data

        Returns:
            Updated EtsySettingsResponse
        """
        tenant = await self._get_tenant(tenant_id)

        # Get existing settings or create new
        current_settings = dict(tenant.settings)
        etsy_config = dict(current_settings.get("etsy", {}))

        # Update provided fields
        if data.enabled is not None:
            etsy_config["enabled"] = data.enabled

        if data.shop_id is not None:
            etsy_config["shop_id"] = data.shop_id

        # Encrypt sensitive credentials
        if data.api_key is not None:
            etsy_config["api_key_encrypted"] = encrypt_value(data.api_key)

        if data.shared_secret is not None:
            etsy_config["shared_secret_encrypted"] = encrypt_value(data.shared_secret)

        if data.access_token is not None:
            etsy_config["access_token_encrypted"] = encrypt_value(data.access_token)

        if data.refresh_token is not None:
            etsy_config["refresh_token_encrypted"] = encrypt_value(data.refresh_token)

        # Update timestamp
        etsy_config["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Save to database
        current_settings["etsy"] = etsy_config
        await self._update_tenant_settings(tenant_id, current_settings)

        return await self.get_etsy_settings(tenant_id)

    async def test_etsy_connection(self, tenant_id: UUID) -> EtsyConnectionTest:
        """Test the Etsy connection using tenant's credentials.

        Args:
            tenant_id: The tenant's UUID

        Returns:
            EtsyConnectionTest with result details
        """
        tenant = await self._get_tenant(tenant_id)
        etsy_config = tenant.settings.get("etsy", {})

        # Get decrypted credentials
        api_key = safe_decrypt(etsy_config.get("api_key_encrypted", ""))
        access_token = safe_decrypt(etsy_config.get("access_token_encrypted", ""))
        shop_id = etsy_config.get("shop_id")

        if not api_key or not access_token:
            return EtsyConnectionTest(
                success=False,
                message="Etsy API credentials are not configured",
            )

        if not shop_id:
            return EtsyConnectionTest(
                success=False,
                message="Etsy shop ID is not configured",
            )

        try:
            # Use etsyv3 client to test connection
            from etsyv3 import EtsyAPI

            # Create API client - etsyv3 needs keystring and token
            api = EtsyAPI(
                keystring=api_key,
                token=access_token,
                refresh_token=None,  # Not needed for connection test
                expiry=None,  # Not needed for connection test
            )

            # Get shop info to verify connection
            shop = api.get_shop(shop_id=int(shop_id))

            if shop:
                shop_name = shop.shop_name if hasattr(shop, "shop_name") else str(shop_id)
                shop_url = f"https://www.etsy.com/shop/{shop_name}"

                # Save shop name for display
                current_settings = dict(tenant.settings)
                etsy_config = dict(current_settings.get("etsy", {}))
                etsy_config["shop_name"] = shop_name
                current_settings["etsy"] = etsy_config
                await self._update_tenant_settings(tenant_id, current_settings)

                return EtsyConnectionTest(
                    success=True,
                    message="Successfully connected to Etsy",
                    shop_name=shop_name,
                    shop_url=shop_url,
                )
            else:
                return EtsyConnectionTest(
                    success=False,
                    message="Could not retrieve shop information",
                )

        except Exception as e:
            return EtsyConnectionTest(
                success=False,
                message=f"Connection failed: {str(e)}",
            )

    def get_etsy_credentials(self, tenant_settings: dict) -> dict | None:
        """Get decrypted Etsy credentials for API calls.

        This method is used by EtsySyncService to get credentials
        without an async context.

        Args:
            tenant_settings: The tenant's settings dict

        Returns:
            Dict with api_key, access_token, refresh_token, shop_id or None if not configured
        """
        etsy_config = tenant_settings.get("etsy", {})

        if not etsy_config.get("enabled", False):
            return None

        api_key = safe_decrypt(etsy_config.get("api_key_encrypted", ""))
        shared_secret = safe_decrypt(etsy_config.get("shared_secret_encrypted", ""))
        access_token = safe_decrypt(etsy_config.get("access_token_encrypted", ""))
        refresh_token = safe_decrypt(etsy_config.get("refresh_token_encrypted", ""))
        shop_id = etsy_config.get("shop_id")

        if not api_key or not access_token or not shop_id:
            return None

        return {
            "api_key": api_key,
            "shared_secret": shared_secret,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "shop_id": shop_id,
        }

    # =========================================================================
    # Shop Settings
    # =========================================================================

    async def get_shop_settings(self, tenant_id: UUID) -> ShopSettingsResponse:
        """Get shop settings for a tenant.

        Args:
            tenant_id: The tenant's UUID

        Returns:
            ShopSettingsResponse with current shop configuration
        """
        tenant = await self._get_tenant(tenant_id)
        shop_config = tenant.settings.get("shop", {})

        return ShopSettingsResponse(
            enabled=shop_config.get("enabled", False),
            shop_name=shop_config.get("shop_name"),
            shop_url_slug=shop_config.get("shop_url_slug"),
            custom_domain=shop_config.get("custom_domain"),
            custom_domain_verified=shop_config.get("custom_domain_verified", False),
            order_prefix=shop_config.get("order_prefix"),
            tagline=shop_config.get("tagline"),
            logo_url=shop_config.get("logo_url"),
            favicon_url=shop_config.get("favicon_url"),
            contact_email=shop_config.get("contact_email"),
            contact_phone=shop_config.get("contact_phone"),
            social_instagram=shop_config.get("social_instagram"),
            social_facebook=shop_config.get("social_facebook"),
            social_twitter=shop_config.get("social_twitter"),
            show_reviews=shop_config.get("show_reviews", True),
            allow_guest_checkout=shop_config.get("allow_guest_checkout", True),
            currency=shop_config.get("currency", "GBP"),
            updated_at=shop_config.get("updated_at"),
        )

    async def update_shop_settings(
        self, tenant_id: UUID, data: ShopSettingsUpdate
    ) -> ShopSettingsResponse:
        """Update shop settings for a tenant.

        Args:
            tenant_id: The tenant's UUID
            data: The settings update data

        Returns:
            Updated ShopSettingsResponse
        """
        tenant = await self._get_tenant(tenant_id)

        # Get existing settings or create new
        current_settings = dict(tenant.settings)
        shop_config = dict(current_settings.get("shop", {}))

        # Update provided fields (only non-None values)
        update_fields = [
            "enabled",
            "shop_name",
            "shop_url_slug",
            "custom_domain",
            "order_prefix",
            "tagline",
            "logo_url",
            "favicon_url",
            "contact_email",
            "contact_phone",
            "social_instagram",
            "social_facebook",
            "social_twitter",
            "show_reviews",
            "allow_guest_checkout",
            "currency",
        ]

        for field in update_fields:
            value = getattr(data, field, None)
            if value is not None:
                shop_config[field] = value

        # Update timestamp
        shop_config["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Save to database
        current_settings["shop"] = shop_config
        await self._update_tenant_settings(tenant_id, current_settings)

        return await self.get_shop_settings(tenant_id)

    # =========================================================================
    # Branding Settings
    # =========================================================================

    async def get_branding_settings(self, tenant_id: UUID) -> BrandingSettingsResponse:
        """Get branding settings for a tenant.

        Args:
            tenant_id: The tenant's UUID

        Returns:
            BrandingSettingsResponse with current branding configuration
        """
        tenant = await self._get_tenant(tenant_id)
        branding_config = tenant.settings.get("branding", {})

        return BrandingSettingsResponse(
            logo_url=branding_config.get("logo_url"),
            favicon_url=branding_config.get("favicon_url"),
            primary_color=branding_config.get("primary_color", "#3B82F6"),
            accent_color=branding_config.get("accent_color", "#10B981"),
            font_family=branding_config.get("font_family"),
            updated_at=branding_config.get("updated_at"),
        )

    async def update_branding_settings(
        self, tenant_id: UUID, data: BrandingSettingsUpdate
    ) -> BrandingSettingsResponse:
        """Update branding settings for a tenant.

        Args:
            tenant_id: The tenant's UUID
            data: The settings update data

        Returns:
            Updated BrandingSettingsResponse
        """
        tenant = await self._get_tenant(tenant_id)

        # Get existing settings or create new
        current_settings = dict(tenant.settings)
        branding_config = dict(current_settings.get("branding", {}))

        # Update provided fields (only non-None values)
        update_fields = [
            "logo_url",
            "favicon_url",
            "primary_color",
            "accent_color",
            "font_family",
        ]

        for field in update_fields:
            value = getattr(data, field, None)
            if value is not None:
                branding_config[field] = value

        # Update timestamp
        branding_config["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Save to database
        current_settings["branding"] = branding_config
        await self._update_tenant_settings(tenant_id, current_settings)

        return await self.get_branding_settings(tenant_id)

    # =========================================================================
    # Tenant Details
    # =========================================================================

    async def get_tenant(self, tenant_id: UUID) -> TenantResponse:
        """Get tenant details.

        Args:
            tenant_id: The tenant's UUID

        Returns:
            TenantResponse with tenant details
        """
        tenant = await self._get_tenant(tenant_id)
        return TenantResponse.model_validate(tenant)

    async def update_tenant(self, tenant_id: UUID, data: TenantUpdate) -> TenantResponse:
        """Update tenant details.

        Args:
            tenant_id: The tenant's UUID
            data: The update data

        Returns:
            Updated TenantResponse
        """
        tenant = await self._get_tenant(tenant_id)

        # Build update dict
        updates = {}
        if data.name is not None:
            updates["name"] = data.name
        if data.description is not None:
            updates["description"] = data.description
        if data.currency_code is not None:
            updates["currency_code"] = data.currency_code
        if data.currency_symbol is not None:
            updates["currency_symbol"] = data.currency_symbol
        if "country_code" in data.model_fields_set:
            # Null clears it; changing it seeds and supersedes nothing (D7).
            updates["country_code"] = data.country_code

        if updates:
            updates["updated_at"] = datetime.now(timezone.utc)
            stmt = update(Tenant).where(Tenant.id == tenant_id).values(**updates)
            await self.db.execute(stmt)
            await self.db.commit()

        # Refresh and return
        await self.db.refresh(tenant)
        return TenantResponse.model_validate(tenant)

    # =========================================================================
    # Replicate (generative AI) Settings -- spec 008
    # =========================================================================

    async def get_replicate_settings(self, tenant_id: UUID) -> ReplicateSettingsResponse:
        """Replicate settings with the token masked, budget and month-to-date usage (USD)."""
        from sqlalchemy import func

        from app.config import get_settings
        from app.models.generation_job import ACTIVE_STATUSES, GenerationJob
        from app.services.genai import credentials
        from app.services.genai.costs import GenAICostService

        tenant = await self._get_tenant(tenant_id)
        config = credentials.replicate_config(tenant)
        own = safe_decrypt(config.get("api_token_encrypted", ""))
        resolved = credentials.resolve(tenant)
        mtd, jobs = await GenAICostService().month_to_date(self.db, tenant.id)
        active = await self.db.scalar(
            select(func.count(GenerationJob.id)).where(
                GenerationJob.tenant_id == tenant.id, GenerationJob.status.in_(ACTIVE_STATUSES)
            )
        )
        budget = config.get("monthly_budget_usd")
        return ReplicateSettingsResponse(
            is_configured=bool(own),
            token_masked=mask_credential(own) if own else None,
            token_source=resolved.source,
            platform_token_available=credentials.platform_token() is not None,
            platform_token_allowed=credentials.platform_allowed(tenant),
            monthly_budget=str(budget) if budget not in (None, "") else None,
            month_to_date=format(mtd, "f"),
            jobs_this_month=jobs,
            active_jobs=int(active or 0),
            concurrency_limit=get_settings().genai_max_concurrent_jobs,
            model_overrides=dict(config.get("model_overrides") or {}),
            updated_at=config.get("updated_at"),
        )

    async def update_replicate_settings(
        self, tenant_id: UUID, data: ReplicateSettingsUpdate
    ) -> ReplicateSettingsResponse:
        """Save the token (encrypted), budget and model overrides.

        ``platform_token_allowed`` is never written here: only a platform admin
        grants the platform token (clarification Q2).
        """
        tenant = await self._get_tenant(tenant_id)
        current = dict(tenant.settings or {})
        config = dict(current.get("replicate") or {})
        if data.api_token is not None:
            token = data.api_token.strip()
            if token:
                config["api_token_encrypted"] = encrypt_value(token)
            else:
                config.pop("api_token_encrypted", None)
            # A new or removed token invalidates the cached webhook secret.
            config.pop("webhook_secret_encrypted", None)
            config.pop("webhook_secret_token_fingerprint", None)
        if data.clear_budget:
            config.pop("monthly_budget_usd", None)
        elif data.monthly_budget is not None:
            config["monthly_budget_usd"] = format(
                data.monthly_budget.quantize(Decimal("0.01")), "f"
            )
        if data.model_overrides is not None:
            overrides = dict(config.get("model_overrides") or {})
            for capability, override in data.model_overrides.items():
                if override is None:
                    overrides.pop(capability, None)
                else:
                    item = override.model_dump(mode="json", exclude_none=True)
                    if override.price_usd is not None:
                        item["price_usd"] = format(override.price_usd, "f")
                    overrides[capability] = item
            config["model_overrides"] = overrides
        config["updated_at"] = datetime.now(timezone.utc).isoformat()
        current["replicate"] = config
        await self._update_tenant_settings(tenant_id, current)
        return await self.get_replicate_settings(tenant_id)

    async def test_replicate_connection(self, tenant_id: UUID) -> ReplicateConnectionTest:
        """Ask the provider who the token in use belongs to; the token never appears."""
        from app.services.genai import credentials
        from app.services.genai.base import ProviderError
        from app.services.genai.logging import redact
        from app.services.genai.runner import make_provider

        tenant = await self._get_tenant(tenant_id)
        resolved = credentials.resolve(tenant)
        if not resolved.token:
            return ReplicateConnectionTest(
                success=False,
                message="No Replicate token is configured",
                token_source=resolved.source,
            )
        provider = make_provider("replicate", resolved.token)
        try:
            account = await provider.account()
        except ProviderError as exc:
            return ReplicateConnectionTest(
                success=False, message=redact(str(exc)), token_source=resolved.source
            )
        finally:
            await provider.aclose()
        return ReplicateConnectionTest(
            success=True,
            message="Connected to Replicate",
            account=account.username or account.name,
            token_source=resolved.source,
        )

    async def replicate_usage(self, tenant_id: UUID, months: int = 6) -> ReplicateUsageResponse:
        """Spend and job count per calendar month (UTC), newest first."""
        from app.services.genai.costs import GenAICostService

        tenant = await self._get_tenant(tenant_id)
        rows = await GenAICostService().usage_by_month(self.db, tenant.id, months)
        return ReplicateUsageResponse(
            months=[
                ReplicateUsageMonth(month=r["month"], cost=format(r["cost"], "f"), jobs=r["jobs"])
                for r in rows
            ]
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    async def _get_tenant(self, tenant_id: UUID) -> Tenant:
        """Get a tenant by ID.

        Args:
            tenant_id: The tenant's UUID

        Returns:
            The Tenant object

        Raises:
            ValueError: If tenant not found
        """
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await self.db.execute(stmt)
        tenant = result.scalar_one_or_none()

        if not tenant:
            raise ValueError(f"Tenant not found: {tenant_id}")

        return tenant

    async def write_settings_part(
        self, tenant: Tenant, key: str, value: Any, *, commit: bool = False
    ) -> None:
        """Replace one top-level part of ``tenant.settings`` (e.g. ``postage``).

        Written through the ORM and, by default, not committed: the catalogue
        seeding writes its notice in the same savepoint as the rows it adds, so
        a failure leaves neither (spec 006, FR-015).
        """
        settings = dict(tenant.settings or {})
        settings[key] = value
        tenant.settings = settings
        tenant.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        if commit:
            await self.db.commit()

    async def _update_tenant_settings(self, tenant_id: UUID, settings: dict[str, Any]) -> None:
        """Update tenant settings JSON field.

        Args:
            tenant_id: The tenant's UUID
            settings: The new settings dict
        """
        stmt = (
            update(Tenant)
            .where(Tenant.id == tenant_id)
            .values(settings=settings, updated_at=datetime.now(timezone.utc))
        )
        await self.db.execute(stmt)
        await self.db.commit()


# Factory function for dependency injection
async def get_tenant_settings_service(db: AsyncSession) -> TenantSettingsService:
    """Create a TenantSettingsService instance."""
    return TenantSettingsService(db)
