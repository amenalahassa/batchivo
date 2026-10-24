"""Shipping profiles: the postage the operator pays (FR-024).

Postage is a cost, not a reduction of shipping revenue, and the two are
reported separately so the difference between what the customer was charged and
what the parcel cost is visible rather than netted away.

Every monetary field is :class:`~decimal.Decimal`. Pydantic will happily
coerce a JSON number into a float if the annotation says so, which is how
binary floating point gets into a money path through the front door;
Constitution IV and ``tests/unit/pricing/test_no_float_in_money_paths.py``
close the back door, and these annotations close this one.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ShippingProfileBase(BaseModel):
    """Postage the operator pays, by zone and weight bracket (FR-024)."""

    name: str = Field(..., min_length=1, max_length=100)
    destination_zone: str = Field(..., min_length=1, max_length=50)
    weight_bracket_min_grams: Decimal = Field(Decimal("0"), ge=0)
    weight_bracket_max_grams: Optional[Decimal] = Field(None, gt=0)
    postage_cost: Decimal = Field(..., ge=0, description="What one parcel costs to post")
    carrier: Optional[str] = Field(None, max_length=50)
    effective_from: date

    @model_validator(mode="after")
    def _bracket_must_be_ordered(self) -> "ShippingProfileBase":
        if (
            self.weight_bracket_max_grams is not None
            and self.weight_bracket_max_grams <= self.weight_bracket_min_grams
        ):
            raise ValueError("weight_bracket_max_grams must be above weight_bracket_min_grams")
        return self


class ShippingProfileCreate(ShippingProfileBase):
    """Schema for creating a shipping profile."""


class ShippingProfileUpdate(BaseModel):
    """Schema for updating a shipping profile."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    destination_zone: Optional[str] = Field(None, min_length=1, max_length=50)
    weight_bracket_min_grams: Optional[Decimal] = Field(None, ge=0)
    weight_bracket_max_grams: Optional[Decimal] = Field(None, gt=0)
    postage_cost: Optional[Decimal] = Field(None, ge=0)
    carrier: Optional[str] = Field(None, max_length=50)
    # When the postage, a bracket or the zone changes, the profile is
    # superseded (task T233) and this is the first day the new figures apply,
    # today by default. Otherwise it corrects the profile's own start date.
    effective_from: Optional[date] = None

    def changes(self) -> dict:
        return self.model_dump(exclude_unset=True)


class ShippingProfileResponse(ShippingProfileBase):
    """Schema for a shipping profile response."""

    id: UUID
    tenant_id: UUID
    effective_to: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)


class ShippingProfileListResponse(BaseModel):
    profiles: list[ShippingProfileResponse]
    total: int
