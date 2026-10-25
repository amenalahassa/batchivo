"""Self-service tenant onboarding API endpoints."""

import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import products as products_api
from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB

from app.core.rate_limit import limiter
from app.database import get_db
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.onboarding import (
    OnboardingLogoResponse,
    OnboardingStatusResponse,
    OnboardingStep1Request,
    OnboardingStep2Request,
    OnboardingStep3Request,
    OnboardingStep4Request,
    OnboardingStepResponse,
    EmailVerificationRequest,
    EmailVerificationResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    TenantRegistrationRequest,
    TenantRegistrationResponse,
)
from app.schemas.product import ProductCreate, ProductPricingCreate
from app.services.image_storage import ImageStorage, ImageStorageError, get_image_storage
from app.services.onboarding_wizard import OnboardingWizardService
from app.services.onboarding_service import (
    EmailAlreadyRegisteredError,
    InvalidTokenError,
    get_onboarding_service,
)

router = APIRouter()

# Rate limits for registration endpoints
REGISTER_RATE_LIMIT = "5/minute"
VERIFY_RATE_LIMIT = "10/minute"
RESEND_RATE_LIMIT = "3/minute"


@router.post(
    "/register",
    response_model=TenantRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new tenant",
    description="Start the tenant registration process. Sends verification email.",
)
@limiter.limit(REGISTER_RATE_LIMIT)
async def register_tenant(
    request: Request,
    registration: TenantRegistrationRequest,
    db: AsyncSession = Depends(get_db),
) -> TenantRegistrationResponse:
    """
    Register a new tenant with email verification.

    This endpoint:
    1. Validates the registration request
    2. Creates a verification token
    3. Sends verification email
    4. Returns success message (tenant/user created on verification)

    Rate limited to prevent abuse.
    """
    service = get_onboarding_service(db)

    try:
        return await service.register_tenant(registration)
    except EmailAlreadyRegisteredError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed. Please try again later.",
        )


@router.post(
    "/verify-email",
    response_model=EmailVerificationResponse,
    summary="Verify email and complete registration",
    description="Verify email address and complete tenant/user creation.",
)
@limiter.limit(VERIFY_RATE_LIMIT)
async def verify_email(
    request: Request,
    verification: EmailVerificationRequest,
    db: AsyncSession = Depends(get_db),
) -> EmailVerificationResponse:
    """
    Verify email and complete registration.

    This endpoint:
    1. Validates the verification token
    2. Creates the tenant with appropriate settings
    3. Creates the user as tenant owner
    4. Returns JWT tokens for immediate login

    The token is single-use and expires after 24 hours.
    """
    service = get_onboarding_service(db)

    try:
        return await service.verify_email(verification.token)
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except EmailAlreadyRegisteredError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Verification failed. Please try again.",
        )


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    summary="Resend verification email",
    description="Resend verification email for pending registration.",
)
@limiter.limit(RESEND_RATE_LIMIT)
async def resend_verification(
    request: Request,
    resend_request: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
) -> ResendVerificationResponse:
    """
    Resend verification email.

    This endpoint is rate-limited and always returns success to prevent
    email enumeration attacks.

    If an unverified registration exists:
    - Old token is invalidated
    - New verification email is sent

    If no pending registration or email is already verified:
    - Returns success (doesn't reveal email status)
    """
    service = get_onboarding_service(db)

    await service.resend_verification(resend_request.email)

    return ResendVerificationResponse(
        message="If an unverified account exists for this email, a verification link has been sent."
    )


# =============================================================================
# Setup wizard (after email verification)
# =============================================================================
#
# The owner (or an admin) runs it on the tenant-scoped session. Each step writes
# through the same path as the settings screen it stands in for.


def _wizard(db: AsyncSession, tenant: Tenant, user: User) -> OnboardingWizardService:
    return OnboardingWizardService(db, tenant, user)


@router.get("/wizard/status", response_model=OnboardingStatusResponse)
async def get_wizard_status(
    user: CurrentUser, tenant: CurrentTenant, _admin: RequireAdmin, db: TenantDB
) -> OnboardingStatusResponse:
    """Where this tenant stands in the setup wizard."""
    return _wizard(db, tenant, user).status()


@router.put("/wizard/step/1", response_model=OnboardingStepResponse)
async def save_wizard_step1(
    data: OnboardingStep1Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> OnboardingStepResponse:
    """Step 1: the business name, address and description."""
    return await _wizard(db, tenant, user).save_step1(data)


@router.put("/wizard/step/2", response_model=OnboardingStepResponse)
async def save_wizard_step2(
    data: OnboardingStep2Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> OnboardingStepResponse:
    """Step 2: the kind of craft business, which decides the modules."""
    return await _wizard(db, tenant, user).save_step2(data)


@router.put("/wizard/step/3", response_model=OnboardingStepResponse)
async def save_wizard_step3(
    data: OnboardingStep3Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> OnboardingStepResponse:
    """Step 3: shop name, books currency, timezone and brand colour."""
    return await _wizard(db, tenant, user).save_step3(data)


@router.put("/wizard/step/4", response_model=OnboardingStepResponse)
async def save_wizard_step4(
    data: OnboardingStep4Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> OnboardingStepResponse:
    """Step 4: an optional first product, then the wizard is finished.

    The product is created by the product route itself, so the wizard keeps no
    second copy of how a product is made. A typed price becomes a list price on
    the tenant's first active sales channel; with no channel it is not stored,
    because a price without a channel is not a figure the engine can read.
    """
    wizard = _wizard(db, tenant, user)
    if data.skip:
        return await wizard.finish({"skipped": True})
    if not data.product_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Name the product, or skip this step",
        )

    product = await products_api.create_product(
        ProductCreate(
            sku=_first_product_sku(data.product_name),
            name=data.product_name,
            description=data.product_description,
        ),
        user=user,
        tenant=tenant,
        _=True,
        db=db,
    )
    price_stored = False
    if data.product_price is not None:
        channel_id = (
            await db.execute(
                select(SalesChannel.id)
                .where(SalesChannel.tenant_id == tenant.id, SalesChannel.is_active.is_(True))
                .order_by(SalesChannel.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if channel_id is not None:
            await products_api.add_product_pricing(
                product.id,
                ProductPricingCreate(sales_channel_id=channel_id, list_price=data.product_price),
                user=user,
                tenant=tenant,
                _member=True,
                db=db,
            )
            price_stored = True
    return await wizard.finish({"product_id": str(product.id), "price_stored": price_stored})


def _first_product_sku(name: str) -> str:
    stem = re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-")[:40] or "PRODUCT"
    return f"{stem}-{uuid.uuid4().hex[:6].upper()}"


@router.post("/wizard/logo", response_model=OnboardingLogoResponse)
async def upload_wizard_logo(
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
    file: UploadFile = File(...),
    image_storage: ImageStorage = Depends(get_image_storage),
) -> OnboardingLogoResponse:
    """Upload the shop logo and set it as the brand logo."""
    content = await file.read()
    try:
        stored = await image_storage.save_image(
            file_content=content,
            content_type=file.content_type or "application/octet-stream",
            product_id=f"tenant-logo-{tenant.id}",
            original_filename=file.filename,
        )
    except ImageStorageError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await _wizard(db, tenant, user).set_logo(stored["image_url"])
    return OnboardingLogoResponse(message="Logo uploaded", logo_url=stored["image_url"])
