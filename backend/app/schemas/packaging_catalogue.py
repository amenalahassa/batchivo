"""Schemas for the standard packaging catalogue and the seeding notice (spec 006)."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CatalogueItemOut(BaseModel):
    """One catalogue entry, as the Packaging page offers it."""

    key: str
    name: str
    kind: str
    inner_length_mm: Optional[Decimal] = None
    inner_width_mm: Optional[Decimal] = None
    inner_height_mm: Optional[Decimal] = None
    wall_mm: Optional[Decimal] = None
    empty_weight_grams: Optional[Decimal] = None
    fill_volume_ml: Optional[Decimal] = None
    unit_of_measure: str
    typical_cost: Optional[Decimal] = Field(
        None, description="Typical unit cost in the tenant's currency, or null"
    )
    source: str
    present: bool = Field(..., description="A row of this tenant carries this key")
    present_as: Optional[UUID] = Field(None, description="That row's id")
    previously_removed: bool = Field(
        False, description="Seeded once for this tenant and since deleted"
    )


class PackagingCatalogueOut(BaseModel):
    version: int
    as_of: date
    currency: str
    items: list[CatalogueItemOut]


class CatalogueApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keys: Optional[list[str]] = Field(
        None, description="Catalogue keys to add; empty or absent adds every item"
    )


class AddedItem(BaseModel):
    key: str
    id: UUID


class SkippedItem(BaseModel):
    key: str
    reason: Literal["already_present", "name_in_use"]


class CatalogueApplyResponse(BaseModel):
    added: list[AddedItem]
    skipped: list[SkippedItem]


class AcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part: Literal["packaging", "postage"]


class CatalogueNoticeOut(BaseModel):
    """The unacknowledged parts of ``settings.catalogue_seed`` (``{}`` when none)."""

    packaging: Optional[dict[str, Any]] = None
    postage: Optional[dict[str, Any]] = None


__all__ = [
    "AcknowledgeRequest",
    "AddedItem",
    "CatalogueApplyRequest",
    "CatalogueApplyResponse",
    "CatalogueItemOut",
    "CatalogueNoticeOut",
    "PackagingCatalogueOut",
    "SkippedItem",
]
