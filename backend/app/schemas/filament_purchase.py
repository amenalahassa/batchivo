"""Schemas for filament purchases and their per-spool landed cost (task T048).

The allocation is the reason this resource exists (FR-008a, FR-008b), so it is
part of the response rather than something a caller recomputes. Each spool
entry carries its derivation, because a per-gram cost nobody can explain six
months later is the figure this feature set out to remove (FR-008f).
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SpoolLandedCostResponse(BaseModel):
    """One spool's share of a purchase, and what a usable gram cost."""

    spool_id: UUID
    spool_label: Optional[str] = Field(
        None, description="The operator-facing spool identifier, for the label on screen"
    )
    purchase_price: Optional[Decimal] = None
    allocated_shipping: Decimal = Field(
        ..., description="This spool's share of the purchase's inbound shipping, by weight"
    )
    allocated_tax: Decimal = Field(
        ..., description="Allocated non-recoverable tax; zero where the tax is recoverable"
    )
    tax_recoverable: bool
    nominal_weight_grams: Decimal
    unusable_remainder_grams: Decimal
    usable_weight_grams: Decimal = Field(
        ..., description="Nominal weight less the unusable remainder (FR-008d)"
    )
    total_landed_cost: Optional[Decimal] = None
    cost_per_gram: Optional[Decimal] = Field(
        None, description="Landed cost per *usable* gram, or null when it cannot be derived"
    )
    even_split_fallback: bool = Field(
        False, description="True when weights were unusable and shipping was split evenly"
    )
    incomplete_reasons: list[str] = Field(default_factory=list)
    derivation: list[str] = Field(
        default_factory=list, description="How the figure was arrived at, in order (FR-008f)"
    )

    model_config = ConfigDict(from_attributes=True)


class FilamentPurchaseBase(BaseModel):
    """The fields an operator records about a buying event."""

    supplier: Optional[str] = Field(None, max_length=200, description="Supplier or vendor name")
    purchase_date: date = Field(
        ..., description="When the purchase was made; the as-of date of its landed costs"
    )
    inbound_shipping_cost: Decimal = Field(
        Decimal("0"), ge=0, description="Total inbound shipping, allocated across spools by weight"
    )
    tax_amount: Decimal = Field(Decimal("0"), ge=0, description="Sales tax on the purchase")
    tax_recoverable: bool = Field(
        False, description="Recoverable tax is excluded from landed cost (FR-008c)"
    )
    order_reference: Optional[str] = Field(
        None, max_length=100, description="Supplier order number, for reconciling the invoice"
    )
    notes: Optional[str] = None


class FilamentPurchaseCreate(FilamentPurchaseBase):
    """Schema for recording a purchase."""

    model_config = ConfigDict(extra="forbid")


class FilamentPurchaseUpdate(BaseModel):
    """Schema for correcting a purchase. Unnamed fields are left alone."""

    supplier: Optional[str] = Field(None, max_length=200)
    purchase_date: Optional[date] = None
    inbound_shipping_cost: Optional[Decimal] = Field(None, ge=0)
    tax_amount: Optional[Decimal] = Field(None, ge=0)
    tax_recoverable: Optional[bool] = None
    order_reference: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class FilamentPurchaseResponse(FilamentPurchaseBase):
    """A purchase with the landed cost it implies for each of its spools."""

    id: UUID
    spools: list[SpoolLandedCostResponse] = Field(
        default_factory=list, description="Per-spool allocation, derived on read"
    )
    allocation_notes: list[str] = Field(
        default_factory=list,
        description="Why any fallback was taken, in words the operator can read",
    )

    model_config = ConfigDict(from_attributes=True)


class FilamentPurchaseListResponse(BaseModel):
    """Paginated purchases."""

    purchases: list[FilamentPurchaseResponse]
    total: int
    skip: int
    limit: int

    model_config = ConfigDict(from_attributes=True)
