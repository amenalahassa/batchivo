"""Response and request shapes for packaging suggestions and parcels.

Sizes, weights and volumes travel as decimal strings (Constitution IV).
Suggestions carry no cost of their own (FR-021): the packaging cost is the
cost breakdown's line for the accepted container.
"""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.dimensions import Tenth

if TYPE_CHECKING:
    from app.models.order_parcel import OrderParcel


class SizeOut(BaseModel):
    length_mm: Tenth
    width_mm: Tenth
    height_mm: Tenth


class ItemSizeOut(SizeOut):
    source: Optional[str] = None


class RoomOut(BaseModel):
    length: Tenth
    width: Tenth
    height: Tenth


class VoidFillOut(BaseModel):
    consumable_id: UUID
    name: str
    quantity: int


class WrapOut(BaseModel):
    consumable_id: UUID
    name: str


class SuggestionOut(BaseModel):
    consumable_id: UUID
    name: str
    kind: str
    in_stock: bool
    inner: SizeOut
    orientation: list[str] = Field(
        ..., description="For each of the container's axes, which of the item's lies along it"
    )
    room_mm: RoomOut = Field(..., description="Room left on each axis beyond the clearance")
    empty_volume_ml: Tenth
    void_fill: Optional[VoidFillOut] = None
    wrap: Optional[WrapOut] = None
    is_current: bool = False


class PackagingSuggestionsResponse(BaseModel):
    item: Optional[ItemSizeOut]
    clearance_mm: Tenth
    fragile: bool
    suggestions: list[SuggestionOut]
    minimum_inner: Optional[SizeOut] = None
    warnings: list[str] = Field(default_factory=list)


class AcceptPackagingRequest(BaseModel):
    consumable_id: UUID
    quantity: int = Field(1, ge=1)
    variant_id: Optional[UUID] = None


class AcceptPackagingResponse(BaseModel):
    consumable_id: UUID
    quantity: int
    variant_id: Optional[UUID] = None
    packaging_warnings: list[str] = Field(default_factory=list)


# ============================================
# Orders (Phase 2)
# ============================================


class ParcelContentOut(BaseModel):
    product_id: UUID
    sku: str
    quantity: int


class OrderParcelSuggestionOut(BaseModel):
    consumable_id: UUID
    name: str
    contents: list[ParcelContentOut]
    outer_mm: Optional[SizeOut] = None
    packed_weight_grams: Optional[Tenth] = None
    void_fill: Optional[VoidFillOut] = None
    notes: list[str] = Field(default_factory=list, description="What build_parcel assumed")


class EstimatedPostageOut(BaseModel):
    amount: Optional[Decimal] = None
    zone: Optional[str] = None
    reason: Optional[str] = None
    is_estimate: bool = True
    notes: list[str] = Field(default_factory=list)


class OrderWarningOut(BaseModel):
    code: str
    sku: Optional[str] = None


class OrderPackagingSuggestionsResponse(BaseModel):
    parcels: list[OrderParcelSuggestionOut]
    estimated_postage: EstimatedPostageOut
    warnings: list[OrderWarningOut] = Field(default_factory=list)


class ParcelItemIn(BaseModel):
    consumable_id: UUID
    quantity: int = Field(..., ge=1)


class ParcelContentIn(BaseModel):
    sku: str = Field(..., min_length=1)
    quantity: int = Field(..., ge=1)


class ParcelIn(BaseModel):
    items: list[ParcelItemIn] = Field(..., min_length=1)
    contents: Optional[list[ParcelContentIn]] = Field(
        None,
        description=(
            "Which of the order's units are in this parcel; needed only when there are "
            "several parcels, so each is weighed with its own contents"
        ),
    )


class ConfirmParcelsRequest(BaseModel):
    parcels: list[ParcelIn] = Field(..., min_length=1)


class ParcelItemOut(BaseModel):
    consumable_id: UUID
    name: Optional[str] = None
    quantity: int


class OrderParcelOut(BaseModel):
    id: UUID
    sequence: int
    outer_length_mm: Optional[Tenth] = None
    outer_width_mm: Optional[Tenth] = None
    outer_height_mm: Optional[Tenth] = None
    packed_weight_grams: Optional[Tenth] = None
    confirmed_at: datetime
    items: list[ParcelItemOut]

    @classmethod
    def of(cls, parcel: "OrderParcel") -> "OrderParcelOut":
        """A stored parcel as the API shows it, with each item's name."""
        return cls(
            id=parcel.id,
            sequence=parcel.sequence,
            outer_length_mm=parcel.outer_length_mm,
            outer_width_mm=parcel.outer_width_mm,
            outer_height_mm=parcel.outer_height_mm,
            packed_weight_grams=parcel.packed_weight_grams,
            confirmed_at=parcel.confirmed_at,
            items=[
                ParcelItemOut(
                    consumable_id=item.consumable_type_id,
                    name=item.consumable_type.name if item.consumable_type else None,
                    quantity=item.quantity,
                )
                for item in parcel.items
            ],
        )


class StockWarningOut(BaseModel):
    code: str = "stock_below_zero"
    consumable_id: UUID
    on_hand: int


class ConfirmParcelsResponse(BaseModel):
    parcels: list[OrderParcelOut]
    postage: EstimatedPostageOut
    warnings: list[StockWarningOut] = Field(default_factory=list)
