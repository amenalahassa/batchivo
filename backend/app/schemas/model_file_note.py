"""Schemas for notes pinned on model files (contracts/api.md, Notes; typed in spec 009)."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, Field

from app.schemas.model_file_version import PersonRef

Vector = tuple[float, float, float]

NoteSource = Literal["person", "preflight", "print"]
NoteSeverityValue = Literal["info", "warning", "failure"]

#: Preflight's own severity words (`SKILL.md` rule 4) and their Batchivo equivalent.
SEVERITY_ALIASES = {"attention": "warning", "échec": "failure", "echec": "failure"}


def normalise_severity(value: Any) -> Any:
    """Accept Preflight's `attention` / `échec`; the mapping is one-to-one (FR-012)."""
    if isinstance(value, str):
        return SEVERITY_ALIASES.get(value.strip().lower(), value)
    return value


NoteSeverity = Annotated[NoteSeverityValue, BeforeValidator(normalise_severity)]


class NoteTypeFields(BaseModel):
    """Spec 009 type fields; all optional so existing requests are unchanged."""

    source: Optional[NoteSource] = Field(None, description="Who raised it; defaults to person")
    rule_id: Optional[str] = Field(
        None, max_length=100, description="Preflight rule id, e.g. fit.slide.clearance"
    )
    severity: Optional[NoteSeverity] = Field(None, description="info, warning or failure")
    measured_value: Optional[Decimal] = None
    expected_value: Optional[Decimal] = None
    value_unit: Optional[str] = Field(None, max_length=20)


class NoteCreate(NoteTypeFields):
    position: Vector = Field(..., description="Point on the part, in the file's mm")
    normal: Vector = Field(..., description="Unit surface normal at that point")
    layer: Optional[int] = Field(None, ge=0, description="Layer, when placed on a sliced file")
    text: str = Field(..., min_length=1, max_length=2000)


class NoteUpdate(NoteTypeFields):
    text: Optional[str] = Field(None, min_length=1, max_length=2000)
    position: Optional[Vector] = None
    normal: Optional[Vector] = None
    status: Optional[Literal["open", "resolved", "dismissed"]] = None
    resolved_in_version_id: Optional[UUID] = None
    dismissal_reason: Optional[str] = Field(
        None, min_length=1, max_length=2000, description="Required to dismiss a note"
    )


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
    # Spec 009 typed notes
    source: str = "person"
    rule_id: Optional[str] = None
    severity: str = "info"
    measured_value: Optional[Decimal] = None
    expected_value: Optional[Decimal] = None
    value_unit: Optional[str] = None
    dismissal_reason: Optional[str] = None
    dismissed_at: Optional[datetime] = None
    dismissed_by: Optional[PersonRef] = None
