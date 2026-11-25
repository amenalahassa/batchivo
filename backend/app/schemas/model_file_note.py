"""Schemas for notes pinned on model files (contracts/api.md, Notes)."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.model_file_version import PersonRef

Vector = tuple[float, float, float]


class NoteCreate(BaseModel):
    position: Vector = Field(..., description="Point on the part, in the file's mm")
    normal: Vector = Field(..., description="Unit surface normal at that point")
    layer: Optional[int] = Field(None, ge=0, description="Layer, when placed on a sliced file")
    text: str = Field(..., min_length=1, max_length=2000)


class NoteUpdate(BaseModel):
    text: Optional[str] = Field(None, min_length=1, max_length=2000)
    position: Optional[Vector] = None
    normal: Optional[Vector] = None
    status: Optional[Literal["open", "resolved"]] = None
    resolved_in_version_id: Optional[UUID] = None


class CarryForwardRequest(BaseModel):
    target_file_id: UUID = Field(..., description="A file of a newer version")


class NoteResponse(BaseModel):
    id: UUID
    number: int
    model_file_id: Optional[UUID] = None
    version_id: UUID
    position: Vector
    normal: Vector
    layer: Optional[int] = None
    text: str
    status: str
    resolved_in_version_id: Optional[UUID] = None
    carried_to_version_id: Optional[UUID] = None
    carried_from_note_id: Optional[UUID] = None
    author: Optional[PersonRef] = None
    created_at: datetime
    archived_at: Optional[datetime] = None
    ghost: bool = Field(False, description="An open note of an earlier version, shown faded")
