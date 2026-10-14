"""Pydantic schemas for Sales Channel API."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.fee_rule import TaxRemitter


class SalesChannelBase(BaseModel):
    """Base sales channel schema."""

    name: str = Field(..., min_length=1, max_length=100, description="Channel name")
    platform_type: str = Field(
        ..., description="Platform type: fair, online_shop, shopify, ebay, etsy, amazon, other"
    )
    monthly_cost: Decimal = Field(Decimal("0"), ge=0, description="Monthly subscription/booth fee")
    is_active: bool = Field(True, description="Whether channel is active")

    # ------------------------------------------------------------------
    # Channel economics (Tier 2). A channel's fees are its `fee_rules`
    # (FR-020); the blended `fee_percentage`/`fee_fixed` pair this schema used
    # to carry was dropped with the columns behind it (task T123).
    # ------------------------------------------------------------------
    tax_remitter: TaxRemitter = Field(
        "operator", description="Who remits sales tax on this channel's sales (FR-028b)"
    )
    expected_discount_pct: Decimal = Field(
        Decimal("0"),
        ge=0,
        le=100,
        description="Expected discount share, reducing planned net revenue (FR-026)",
    )
    expected_refund_pct: Decimal = Field(
        Decimal("0"),
        ge=0,
        le=100,
        description="Expected refund share, held as a reserve against revenue (FR-026)",
    )
    free_shipping_threshold: Optional[Decimal] = Field(
        None, ge=0, description="Order value at which shipping is free (FR-033)"
    )
    rounding_rule: Optional[str] = Field(
        None, max_length=20, description="How a solved price is rounded, e.g. 'psychological_99'"
    )
    currency_code: str = Field(
        "GBP", min_length=3, max_length=3, description="Channel display currency (FR-028)"
    )
    offsite_ads_opt_in: bool = Field(
        False, description="Whether the operator opted into marketplace offsite advertising"
    )


class SalesChannelCreate(SalesChannelBase):
    """Schema for creating a sales channel."""

    pass


class SalesChannelUpdate(BaseModel):
    """Schema for updating a sales channel."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    platform_type: Optional[str] = None
    monthly_cost: Optional[Decimal] = Field(None, ge=0)
    is_active: Optional[bool] = None

    # Channel economics (Tier 2); absent fields are left alone.
    tax_remitter: Optional[TaxRemitter] = None
    expected_discount_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    expected_refund_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    free_shipping_threshold: Optional[Decimal] = Field(None, ge=0)
    rounding_rule: Optional[str] = Field(None, max_length=20)
    currency_code: Optional[str] = Field(None, min_length=3, max_length=3)
    offsite_ads_opt_in: Optional[bool] = None


class SalesChannelResponse(SalesChannelBase):
    """Schema for sales channel response."""

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SalesChannelListResponse(BaseModel):
    """Schema for paginated sales channel list."""

    channels: list[SalesChannelResponse]
    total: int

    model_config = ConfigDict(from_attributes=True)
