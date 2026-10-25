"""Pydantic schemas for tenant onboarding and registration."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError, field_validator

from app.schemas.tenant_settings import TenantType, TenantUpdate


class TenantRegistrationRequest(BaseModel):
    """Schema for new tenant registration request."""

    # User details
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., min_length=8, max_length=128, description="User password")
    full_name: str = Field(..., min_length=1, max_length=255, description="User's full name")

    # Business details
    business_name: str = Field(
        ..., min_length=2, max_length=100, description="Business/workspace name"
    )
    tenant_type: TenantType = Field(
        default=TenantType.GENERIC,
        description="Type of business (determines features)",
    )

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Validate password strength."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class TenantRegistrationResponse(BaseModel):
    """Schema for registration response (before email verification)."""

    message: str = Field(
        default="Registration successful. Please check your email to verify your account.",
        description="Success message",
    )
    email: str = Field(..., description="Email address verification was sent to")


class EmailVerificationRequest(BaseModel):
    """Schema for email verification request."""

    token: str = Field(..., min_length=1, description="Email verification token")


class EmailVerificationResponse(BaseModel):
    """Schema for successful email verification."""

    model_config = ConfigDict(from_attributes=True)

    message: str = Field(default="Email verified successfully", description="Success message")
    tenant_id: UUID = Field(..., description="Created tenant ID")
    tenant_name: str = Field(..., description="Tenant name")
    tenant_slug: str = Field(..., description="Tenant URL slug")
    user_id: UUID = Field(..., description="Created user ID")
    access_token: str = Field(..., description="JWT access token")
    refresh_token: str = Field(..., description="JWT refresh token")
    token_type: str = Field(default="bearer", description="Token type")


class ResendVerificationRequest(BaseModel):
    """Schema for resending verification email."""

    email: EmailStr = Field(..., description="Email address to resend verification to")


class ResendVerificationResponse(BaseModel):
    """Schema for resend verification response."""

    message: str = Field(
        default="If an unverified account exists for this email, a verification link has been sent.",
        description="Response message",
    )


class RegistrationStatusResponse(BaseModel):
    """Schema for checking registration status."""

    email: str = Field(..., description="Email address")
    is_registered: bool = Field(..., description="Whether email is registered")
    is_verified: bool = Field(..., description="Whether email is verified")
    tenant_name: Optional[str] = Field(None, description="Tenant name if registered")


class OnboardingUserResponse(BaseModel):
    """User details in onboarding response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    full_name: str = Field(..., description="User's full name")
    is_active: bool = Field(..., description="Whether user is active")


class OnboardingTenantResponse(BaseModel):
    """Tenant details in onboarding response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Tenant ID")
    name: str = Field(..., description="Tenant name")
    slug: str = Field(..., description="Tenant URL slug")
    tenant_type: str = Field(..., description="Tenant type")
    is_active: bool = Field(..., description="Whether tenant is active")
    created_at: datetime = Field(..., description="Creation timestamp")


# =============================================================================
# Setup wizard (after email verification)
# =============================================================================


class OnboardingStatusResponse(BaseModel):
    """Where a tenant stands in the setup wizard."""

    current_step: int = Field(..., ge=1, le=4, description="The step to show next")
    completed_steps: list[int] = Field(default_factory=list, description="Steps saved so far")
    is_completed: bool = Field(..., description="Whether the wizard is finished")
    step_data: Optional[dict] = Field(None, description="What each saved step recorded")
    tenant_id: UUID
    tenant_name: str
    tenant_type: str


class OnboardingStepResponse(BaseModel):
    """The outcome of saving one wizard step."""

    message: str
    step_completed: int
    next_step: Optional[int] = Field(None, description="None once the wizard is finished")
    is_completed: bool


class OnboardingStep1Request(BaseModel):
    """Step 1: the business."""

    business_name: str = Field(..., min_length=1, max_length=100)
    slug: Optional[str] = Field(
        None, min_length=3, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    )
    business_description: Optional[str] = Field(None, max_length=500)


class OnboardingStep2Request(BaseModel):
    """Step 2: the kind of craft business, which decides the modules."""

    tenant_type: TenantType


class OnboardingStep3Request(BaseModel):
    """Step 3: the shop and its books currency."""

    shop_display_name: Optional[str] = Field(None, max_length=100)
    currency: Optional[str] = Field(None, pattern=r"^[A-Z]{3}$", description="ISO 4217 code")
    currency_symbol: Optional[str] = Field(None, min_length=1, max_length=5)
    timezone: Optional[str] = Field(None, max_length=64, description="IANA timezone")
    primary_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("currency")
    @classmethod
    def _books_currency(cls, value: Optional[str]) -> Optional[str]:
        # The settings screen's rule, not a copy of it: a currency the books
        # cannot be kept in is refused here as it is there.
        if value is None:
            return None
        try:
            return TenantUpdate(currency_code=value).currency_code
        except ValidationError as e:
            raise ValueError(e.errors()[0]["msg"].removeprefix("Value error, ")) from e


class OnboardingStep4Request(BaseModel):
    """Step 4: an optional first product.

    The price is a list price on a sales channel, never a stored cost, so it is
    kept only where the tenant has a channel to put it on.
    """

    skip: bool = False
    product_name: Optional[str] = Field(None, min_length=1, max_length=200)
    product_description: Optional[str] = None
    product_price: Optional[Decimal] = Field(None, ge=0, description="Decimal string")

    @field_validator("product_name")
    @classmethod
    def _strip(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value else value


class OnboardingLogoResponse(BaseModel):
    """Where the uploaded logo now lives."""

    message: str
    logo_url: str
