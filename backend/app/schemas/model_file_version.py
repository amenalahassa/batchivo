"""Schemas for model file versions and the activation review (contracts/api.md)."""

from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.model_file import ModelFileResponse


class PersonRef(BaseModel):
    """Who did something, as the screens name them."""

    id: UUID
    name: str


class FileVersionCreate(BaseModel):
    """A new version; created inactive unless the model has none yet."""

    label: Optional[str] = Field(
        None, min_length=1, max_length=50, description="Defaults to the next number"
    )
    note: Optional[str] = Field(None, max_length=2000, description="What changed")


class FileVersionUpdate(BaseModel):
    """Rename a version, edit its note, or choose an inactive version's print file."""

    label: Optional[str] = Field(None, min_length=1, max_length=50)
    note: Optional[str] = Field(None, max_length=2000)
    print_file_id: Optional[UUID] = None


class FileVersionResponse(BaseModel):
    id: UUID
    model_id: UUID
    sequence: int
    label: str
    note: Optional[str] = None
    is_active: bool
    print_file_id: Optional[UUID] = None
    created_by: Optional[PersonRef] = None
    created_at: datetime
    files: list[ModelFileResponse] = Field(default_factory=list)
    has_measurable_file: bool = Field(
        False, description="Whether any file of the version has a measurement (FR-013)"
    )
    open_note_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ActivationRow(BaseModel):
    """One figure that would change: from what, to what, and where it is written."""

    field: str = Field(
        ..., description="print_time_minutes | prints_per_plate | weight_grams | dimensions"
    )
    target: str = Field(
        ..., description="model | model_printer_config | model_material | dimensions"
    )
    current: Union[str, dict, None] = None
    proposed: Union[str, dict, None] = None
    selectable: bool = True
    reason: Optional[str] = Field(None, description="Why a row cannot be applied")
    source_file_id: Optional[UUID] = Field(None, description="The file dimensions come from")


class ActivationPreview(BaseModel):
    version_id: UUID
    print_file_id: Optional[UUID] = None
    dimension_file_id: Optional[UUID] = None
    dimension_file_name: Optional[str] = None
    rows: list[ActivationRow] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)


class ActivateRequest(BaseModel):
    apply: list[str] = Field(default_factory=list, description="The figures to write")
    print_file_id: Optional[UUID] = Field(None, description="Choose this print file as well")
