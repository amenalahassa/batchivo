"""Request and response shapes for item dimensions and packaging settings.

Lengths cross the wire as decimal **strings** ("120.0"), like money
(Constitution IV): Pydantic serialises ``Decimal`` as a string in JSON.
"""

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Optional
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

#: A length in mm: positive, to 0.1 mm, below the Numeric(7, 1) ceiling.
_LENGTH = dict(gt=0, max_digits=7, decimal_places=1)


class DimensionsIn(BaseModel):
    """Dimensions to save: all three, or all null to clear them.

    With ``adopt_file_id`` the three figures come from that file's measurement
    instead (source ``measured``), and any given here are ignored.
    """

    length_mm: Optional[Decimal] = Field(None, **_LENGTH, description="Length in mm")
    width_mm: Optional[Decimal] = Field(None, **_LENGTH, description="Width in mm")
    height_mm: Optional[Decimal] = Field(None, **_LENGTH, description="Height in mm")
    adopt_file_id: Optional[UUID] = Field(
        None, description="Take the dimensions measured from this model file"
    )

    @model_validator(mode="after")
    def _all_or_none(self) -> "DimensionsIn":
        if self.adopt_file_id is not None:
            return self
        given = [v is not None for v in (self.length_mm, self.width_mm, self.height_mm)]
        if any(given) and not all(given):
            missing = [
                name
                for name, present in zip(("length_mm", "width_mm", "height_mm"), given)
                if not present
            ]
            raise ValueError(f"give all three dimensions or none; missing: {', '.join(missing)}")
        return self

    @property
    def clears(self) -> bool:
        return self.adopt_file_id is None and self.length_mm is None


class DimensionsOut(BaseModel):
    """An item's dimensions with where they came from (FR-002)."""

    length_mm: Optional[Decimal] = None
    width_mm: Optional[Decimal] = None
    height_mm: Optional[Decimal] = None
    source: Optional[str] = Field(None, description="'entered' | 'measured' | null")
    source_file_id: Optional[UUID] = None
    set_at: Optional[datetime] = None
    inherited: bool = Field(False, description="A variant showing its product's dimensions")

    model_config = ConfigDict(from_attributes=True)

    @field_validator("length_mm", "width_mm", "height_mm")
    @classmethod
    def _tenth(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        return tenth(value)


def tenth(value: Optional[Decimal]) -> Optional[Decimal]:
    """A length as stored: to 0.1 mm, so "120" always reads "120.0" on the wire."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


#: A length, weight or volume shown to 0.1, as every one of them is stored.
Tenth = Annotated[Decimal, AfterValidator(tenth)]


_CLEARANCE = dict(ge=0, max_digits=5, decimal_places=1)


class PackagingSettingsUpdate(BaseModel):
    """The clearance kept around an item on every side, in mm (FR-015)."""

    clearance_mm: Tenth = Field(..., **_CLEARANCE)
    fragile_clearance_mm: Tenth = Field(..., **_CLEARANCE)


class PackagingSettings(PackagingSettingsUpdate):
    """The settings in force; ``configured`` is false while they are the defaults (D8)."""

    configured: bool


__all__ = [
    "DimensionsIn",
    "DimensionsOut",
    "PackagingSettings",
    "PackagingSettingsUpdate",
]
