"""Schemas for fit calibrations (spec 009, contracts/api.md "Calibrations").

``value_mm`` is exact: it is read as a ``Decimal`` (from a JSON number or a
string) and returned as a decimal string, except in the ``atelier.yaml`` export,
which writes a number because that is what ``pf.py clearance`` reads.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.model_file_version import PersonRef

FitType = Literal["slide", "press", "snap", "print-in-place"]
Orientation = Literal["vertical", "horizontal"]
Provenance = Literal["measured", "assumed"]


class MaterialRef(BaseModel):
    """A material by id, or by its code as Preflight names it (``PLA``)."""

    material_type_id: Optional[UUID] = None
    material: Optional[str] = Field(None, max_length=20, description="Material code, e.g. PLA")

    @model_validator(mode="after")
    def _not_both(self) -> "MaterialRef":
        if self.material_type_id is not None and self.material is not None:
            raise ValueError("Give the material either by `material_type_id` or by `material`")
        return self


class CalibrationCreate(MaterialRef):
    filament_type_id: Optional[UUID] = Field(None, description="Refines the material")
    orientation: Orientation
    fit_type: FitType
    value_mm: Decimal = Field(..., ge=0, le=2, description="Clearance per side, in mm")
    provenance: Provenance
    source_print_job_id: Optional[UUID] = None
    source_test_result_id: Optional[UUID] = None
    measured_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=2000)

    @field_validator("value_mm")
    @classmethod
    def _three_decimals(cls, value: Decimal) -> Decimal:
        if value.as_tuple().exponent < -3 and value != value.quantize(Decimal("0.001")):
            raise ValueError("value_mm has at most 3 decimals")
        return value.quantize(Decimal("0.001"))

    @model_validator(mode="after")
    def _material_given(self) -> "CalibrationCreate":
        if self.material_type_id is None and self.material is None:
            raise ValueError("Give the material (`material` code or `material_type_id`)")
        return self


class CalibrationResponse(BaseModel):
    id: UUID
    printer_id: UUID
    printer_name: Optional[str] = None
    material_type_id: UUID
    material_code: Optional[str] = None
    filament_type_id: Optional[UUID] = None
    filament_label: Optional[str] = None
    orientation: str
    fit_type: str
    value_mm: Decimal
    provenance: str
    source_print_job_id: Optional[UUID] = None
    source_test_result_id: Optional[UUID] = None
    measured_at: datetime
    notes: Optional[str] = None
    recorded_by: Optional[PersonRef] = None
    superseded_by_id: Optional[UUID] = None
    superseded_at: Optional[datetime] = None
    is_current: bool
    created_at: datetime


class CalibrationLookup(BaseModel):
    found: bool
    calibration: Optional[CalibrationResponse] = None
    matched_on: Optional[Literal["filament", "material"]] = None


class AtelierCalibration(BaseModel):
    """One item of Preflight's ``atelier.yaml`` ``calibrations:`` list."""

    id: UUID
    printer: str
    printer_id: UUID
    material: str
    filament: Optional[str] = None
    orientation: str
    fit: str
    value_mm: Decimal
    provenance: str
    measured_at: str
    source_print_job_id: Optional[UUID] = None


class AtelierCalibrations(BaseModel):
    calibrations: list[AtelierCalibration]
