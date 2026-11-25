"""Schemas for print test results (spec 009, contracts/api.md "Print test results")."""

import json
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.calibration import MaterialRef, Orientation
from app.schemas.model_file_version import PersonRef

PrintTestKind = Literal["clearance_grid", "critical_zone", "full_part"]
PrintTestOutcome = Literal["pass", "fail", "partial"]

MAX_MEASUREMENTS = 200
MAX_MEASUREMENTS_BYTES = 64 * 1024


def _check_measurements(value: Optional[list[dict[str, Any]]]) -> Optional[list[dict[str, Any]]]:
    if value is None:
        return value
    if len(value) > MAX_MEASUREMENTS:
        raise ValueError(f"At most {MAX_MEASUREMENTS} measurements")
    if len(json.dumps(value, ensure_ascii=False, default=str).encode()) > MAX_MEASUREMENTS_BYTES:
        raise ValueError("Measurements are larger than 64 KB")
    return value


class PrintTestResultCreate(MaterialRef):
    """A test print's result; stored as written (measurements included)."""

    kind: PrintTestKind
    outcome: PrintTestOutcome
    model_id: Optional[UUID] = None
    model_file_version_id: Optional[UUID] = None
    print_job_id: Optional[UUID] = None
    printer_id: Optional[UUID] = None
    filament_type_id: Optional[UUID] = None
    orientation: Optional[Orientation] = None
    measurements: list[dict[str, Any]] = Field(
        default_factory=list, description="Each {name, value, unit?, expected?, ...}"
    )
    failure_mode: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=10_000)

    _measurements = field_validator("measurements")(_check_measurements)


class PrintTestResultUpdate(BaseModel):
    outcome: Optional[PrintTestOutcome] = None
    measurements: Optional[list[dict[str, Any]]] = None
    failure_mode: Optional[str] = Field(None, max_length=2000)
    notes: Optional[str] = Field(None, max_length=10_000)

    _measurements = field_validator("measurements")(_check_measurements)


class PrintTestResultResponse(BaseModel):
    id: UUID
    kind: str
    outcome: str
    model_id: Optional[UUID] = None
    model_name: Optional[str] = None
    model_file_version_id: Optional[UUID] = None
    version_label: Optional[str] = None
    print_job_id: Optional[UUID] = None
    printer_id: Optional[UUID] = None
    material_type_id: Optional[UUID] = None
    material_code: Optional[str] = None
    filament_type_id: Optional[UUID] = None
    orientation: Optional[str] = None
    measurements: list[dict[str, Any]]
    failure_mode: Optional[str] = None
    notes: Optional[str] = None
    photo_available: bool
    recorded_by: Optional[PersonRef] = None
    updated_by: Optional[PersonRef] = None
    created_at: datetime
    updated_at: datetime


class PrintTestResultList(BaseModel):
    items: list[PrintTestResultResponse]
    total: int
