"""Pydantic schemas for Consumable Inventory API.

Every money field here is a ``Decimal``, which Pydantic puts on the wire as a
decimal **string**. They were ``float``, and that mattered beyond this file:
``current_cost_per_unit`` is read by ``app/services/costing.py`` when a
packaging consumable is linked, so a packaging cost entered as 0.07 reached the
engine as 0.070000000000000007 and the engine's exactness started from an
approximation (Constitution IV, FR-047). Tier 0's annotation sweep and the
float ban in ``tests/unit/pricing/test_no_float_in_money_paths.py`` both stopped
at ``app/services/``, which is why these survived (task T144).

A quantity stays an ``int`` and a lead time stays an ``int``; this is about
amounts of money, not about counting things.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

PackagingKind = Literal["box", "mailer", "void_fill", "wrap"]
#: An inner length in mm: positive, to 0.1 mm, within Numeric(7, 1).
_LENGTH = dict(gt=0, max_digits=7, decimal_places=1)
_INNER = ("inner_length_mm", "inner_width_mm", "inner_height_mm")


def _check_inner_all_or_none(values: BaseModel, given: set[str]) -> None:
    """The three inner dimensions are recorded together or not at all (D5)."""
    named = [name for name in _INNER if name in given]
    if not named:
        return
    present = [getattr(values, name) is not None for name in _INNER]
    if (len(named) != 3 and any(present)) or (any(present) and not all(present)):
        missing = [name for name, ok in zip(_INNER, present) if not ok]
        raise ValueError(f"give all three inner dimensions or none; missing: {', '.join(missing)}")


# =============================================================================
# ConsumableType Schemas
# =============================================================================


class ConsumableTypeBase(BaseModel):
    """Base consumable type schema with common fields."""

    sku: str = Field(..., min_length=1, max_length=50, description="Unique SKU within tenant")
    name: str = Field(..., min_length=1, max_length=200, description="Human-readable name")
    description: Optional[str] = Field(None, description="Detailed description")
    category: Optional[str] = Field(
        None,
        max_length=100,
        description="Category (magnets, inserts, hardware, finishing, packaging)",
    )

    # Unit information
    unit_of_measure: str = Field(
        "each",
        max_length=20,
        description="Unit of measure (each, ml, g, pack)",
    )

    # Current pricing
    current_cost_per_unit: Optional[Decimal] = Field(
        None, ge=0, description="Current cost per unit"
    )

    # Stock management
    quantity_on_hand: int = Field(0, ge=0, description="Current stock quantity")
    reorder_point: Optional[int] = Field(
        None, ge=0, description="Stock level that triggers reorder alert"
    )
    reorder_quantity: Optional[int] = Field(
        None, ge=0, description="Suggested quantity to order when reordering"
    )

    # Supplier information
    preferred_supplier: Optional[str] = Field(
        None, max_length=200, description="Preferred supplier/vendor name"
    )
    supplier_sku: Optional[str] = Field(
        None, max_length=100, description="Supplier's SKU/product code"
    )
    supplier_url: Optional[str] = Field(
        None,
        max_length=500,
        description="URL to purchase from supplier (e.g., Amazon product link)",
    )
    typical_lead_days: Optional[int] = Field(
        None, ge=0, description="Typical delivery time in days"
    )

    # Status
    is_active: bool = Field(True, description="Whether this consumable is active")

    # Packaging attributes (packaging advisor, research D5). All optional, so a
    # consumable that is not packaging is unaffected (FR-013).
    packaging_kind: Optional[PackagingKind] = Field(
        None, description="box, mailer, void_fill or wrap; null when not packaging"
    )
    inner_length_mm: Optional[Decimal] = Field(None, **_LENGTH, description="Inner length, mm")
    inner_width_mm: Optional[Decimal] = Field(None, **_LENGTH, description="Inner width, mm")
    inner_height_mm: Optional[Decimal] = Field(
        None, **_LENGTH, description="Inner height, mm (a mailer's maximum thickness)"
    )
    wall_mm: Optional[Decimal] = Field(
        None, ge=0, max_digits=5, decimal_places=1, description="Wall thickness, mm"
    )
    empty_weight_grams: Optional[Decimal] = Field(
        None, ge=0, max_digits=8, decimal_places=1, description="Weight of one empty unit, g"
    )
    fill_volume_ml: Optional[Decimal] = Field(
        None, ge=0, max_digits=10, decimal_places=1, description="Void fill: ml one unit fills"
    )

    @model_validator(mode="after")
    def _inner_all_or_none(self):
        _check_inner_all_or_none(self, self.model_fields_set)
        return self


class ConsumableTypeCreate(ConsumableTypeBase):
    """Schema for creating a new consumable type."""

    packaging_provenance: Optional["PackagingProvenanceIn"] = Field(
        None,
        description=(
            "How the inner size, wall and empty weight are known (FR-038); defaults to assumed"
        ),
    )


class ConsumableTypeUpdate(BaseModel):
    """Schema for updating a consumable type (all fields optional)."""

    sku: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    unit_of_measure: Optional[str] = Field(None, max_length=20)
    current_cost_per_unit: Optional[Decimal] = Field(None, ge=0)
    quantity_on_hand: Optional[int] = Field(None, ge=0)
    reorder_point: Optional[int] = Field(None, ge=0)
    reorder_quantity: Optional[int] = Field(None, ge=0)
    preferred_supplier: Optional[str] = Field(None, max_length=200)
    supplier_sku: Optional[str] = Field(None, max_length=100)
    supplier_url: Optional[str] = Field(None, max_length=500)
    typical_lead_days: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    packaging_kind: Optional[PackagingKind] = None
    inner_length_mm: Optional[Decimal] = Field(None, **_LENGTH)
    inner_width_mm: Optional[Decimal] = Field(None, **_LENGTH)
    inner_height_mm: Optional[Decimal] = Field(None, **_LENGTH)
    wall_mm: Optional[Decimal] = Field(None, ge=0, max_digits=5, decimal_places=1)
    empty_weight_grams: Optional[Decimal] = Field(None, ge=0, max_digits=8, decimal_places=1)
    fill_volume_ml: Optional[Decimal] = Field(None, ge=0, max_digits=10, decimal_places=1)
    packaging_provenance: Optional["PackagingProvenanceIn"] = Field(
        None, description="How the packaging figures being saved are known (FR-038)"
    )

    @model_validator(mode="after")
    def _inner_all_or_none(self):
        _check_inner_all_or_none(self, self.model_fields_set)
        return self


class PackagingProvenanceIn(BaseModel):
    """Where a container's size, wall and weight came from (FR-038).

    An operator measured them, or they are assumed (a catalogue figure, a
    guess). Never ``observed``: that word is for figures a machine recorded.
    """

    source: Literal["measured", "assumed"] = "assumed"


ConsumableTypeCreate.model_rebuild()
ConsumableTypeUpdate.model_rebuild()


class ConsumableTypeResponse(ConsumableTypeBase):
    """Schema for consumable type responses."""

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    # Computed fields
    is_low_stock: bool = Field(..., description="Whether stock is below reorder point")
    stock_value: Decimal = Field(..., description="Total value of stock on hand")
    # The purchase that prices the unit, when one does (T273, T277): the unit
    # cost is then read-only here and changes with a new purchase.
    priced_by_purchase_id: Optional[UUID] = Field(
        None, description="Purchase whose total and quantity price the unit, if any"
    )
    priced_by_purchase_date: Optional[date] = Field(
        None, description="Date of the purchase that prices the unit"
    )
    packaging_incomplete: bool = Field(
        False,
        description="A box or mailer missing an inner dimension: never suggested (D5)",
    )
    packaging_provenance: dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="Each packaging figure's provenance source, as recorded (FR-038)",
    )

    model_config = ConfigDict(from_attributes=True)


class ConsumableTypeListResponse(BaseModel):
    """Schema for paginated consumable type list."""

    total: int = Field(..., description="Total number of consumable types")
    consumables: list[ConsumableTypeResponse] = Field(..., description="List of consumable types")
    page: int = Field(1, ge=1, description="Current page number")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")


# =============================================================================
# ConsumablePurchase Schemas
# =============================================================================


class ConsumablePurchaseBase(BaseModel):
    """Base consumable purchase schema with common fields."""

    consumable_type_id: UUID = Field(..., description="Consumable type being purchased")
    quantity_purchased: int = Field(..., ge=1, description="Quantity purchased")
    total_cost: Decimal = Field(..., ge=0, description="Total cost of purchase")

    # Source
    supplier: Optional[str] = Field(None, max_length=200, description="Supplier/vendor name")
    order_reference: Optional[str] = Field(
        None, max_length=100, description="Order number or reference"
    )
    purchase_url: Optional[str] = Field(
        None, max_length=500, description="URL to purchase (e.g., Amazon product link)"
    )
    purchase_date: Optional[date] = Field(None, description="Date of purchase")

    notes: Optional[str] = Field(None, description="Additional notes")


class ConsumablePurchaseCreate(ConsumablePurchaseBase):
    """Schema for creating a new consumable purchase."""

    pass  # Inherits all fields from ConsumablePurchaseBase


class ConsumablePurchaseUpdate(BaseModel):
    """Schema for updating a consumable purchase (all fields optional)."""

    quantity_purchased: Optional[int] = Field(None, ge=1)
    total_cost: Optional[Decimal] = Field(None, ge=0)
    supplier: Optional[str] = Field(None, max_length=200)
    order_reference: Optional[str] = Field(None, max_length=100)
    purchase_url: Optional[str] = Field(None, max_length=500)
    purchase_date: Optional[date] = None
    notes: Optional[str] = None


class ConsumablePurchaseResponse(ConsumablePurchaseBase):
    """Schema for consumable purchase responses."""

    id: UUID
    tenant_id: UUID
    cost_per_unit: Decimal = Field(..., description="Cost per unit")
    quantity_remaining: int = Field(..., description="Remaining quantity from this purchase")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConsumablePurchaseWithType(ConsumablePurchaseResponse):
    """Schema for consumable purchase with nested type info."""

    consumable_sku: str = Field(..., description="Consumable SKU")
    consumable_name: str = Field(..., description="Consumable name")


class ConsumablePurchaseListResponse(BaseModel):
    """Schema for paginated consumable purchase list."""

    total: int = Field(..., description="Total number of purchases")
    purchases: list[ConsumablePurchaseWithType] = Field(..., description="List of purchases")
    page: int = Field(1, ge=1, description="Current page number")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")


# =============================================================================
# ConsumableUsage Schemas
# =============================================================================


class ConsumableUsageBase(BaseModel):
    """Base consumable usage schema with common fields."""

    consumable_type_id: UUID = Field(..., description="Consumable type used")
    quantity_used: int = Field(
        ..., description="Quantity used (positive) or adjusted (negative for returns)"
    )

    # Optional links
    production_run_id: Optional[UUID] = Field(
        None, description="Production run that used this consumable"
    )
    product_id: Optional[UUID] = Field(None, description="Product that used this consumable")

    # Context
    usage_type: str = Field(
        "production",
        max_length=50,
        description="Type of usage (production, adjustment, waste, return)",
    )
    notes: Optional[str] = Field(None, description="Usage notes or reason for adjustment")


class ConsumableUsageCreate(ConsumableUsageBase):
    """Schema for creating a new consumable usage record."""

    pass  # Inherits all fields from ConsumableUsageBase


class ConsumableUsageResponse(ConsumableUsageBase):
    """Schema for consumable usage responses."""

    id: UUID
    tenant_id: UUID
    cost_at_use: Optional[Decimal] = Field(None, description="Cost per unit at time of use")
    total_cost: Decimal = Field(..., description="Total cost of this usage")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConsumableUsageWithDetails(ConsumableUsageResponse):
    """Schema for consumable usage with nested details."""

    consumable_sku: str = Field(..., description="Consumable SKU")
    consumable_name: str = Field(..., description="Consumable name")


class ConsumableUsageListResponse(BaseModel):
    """Schema for paginated consumable usage list."""

    total: int = Field(..., description="Total number of usage records")
    usage: list[ConsumableUsageWithDetails] = Field(..., description="List of usage records")
    page: int = Field(1, ge=1, description="Current page number")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")


# =============================================================================
# Stock Adjustment Schema
# =============================================================================


class StockAdjustment(BaseModel):
    """Schema for adjusting stock levels."""

    quantity_adjustment: int = Field(
        ..., description="Quantity to add (positive) or remove (negative)"
    )
    reason: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Reason for adjustment",
    )
    notes: Optional[str] = Field(None, description="Additional notes")


# =============================================================================
# Low Stock Alert Schema
# =============================================================================


class LowStockAlert(BaseModel):
    """Schema for low stock alert."""

    consumable_id: UUID
    sku: str
    name: str
    quantity_on_hand: int
    reorder_point: int
    reorder_quantity: Optional[int]
    preferred_supplier: Optional[str]
    stock_value: Decimal
