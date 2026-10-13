"""Request and response shapes for provenance and estimate proposals (T105, T106).

Two screens read these: the cost breakdown, which labels every line with where
its figure came from, and the review list, which shows proposals waiting on a
decision.

**Every numeric figure crosses the wire as a decimal string** (Constitution IV).
A JSON number is a binary float the moment anything parses it, and these
carry an estimate, an observation and a divergence that an operator compares
against a threshold they set. A figure that drifts in the last place on the way
to the screen is a figure that cannot be reconciled with the one on the server.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.models.pricing_input_provenance import PROVENANCE_SOURCES


class FieldOriginResponse(BaseModel):
    """Where one figure came from."""

    field_name: str
    source: str = Field(
        ...,
        description=f"One of {PROVENANCE_SOURCES}: how this figure came to be what it is",
    )
    as_of: Optional[date] = Field(
        None,
        description=(
            "The day the figure was established. Null where nothing has been "
            "recorded, which is not the same as today"
        ),
    )
    confidence: Optional[Decimal] = None
    is_default: bool = Field(
        ...,
        description=(
            "True when nothing was recorded and the registry's default applied, "
            "so a reader can tell 'assumed, and we know it' from 'assumed by "
            "omission' (FR-001)"
        ),
    )
    is_stale: bool = Field(
        ...,
        description=(
            "True for a hand-measured figure older than the tenant's staleness "
            "threshold. Only measured figures go stale: a decision does not "
            "expire and an observed figure is refreshed from its source (FR-005)"
        ),
    )
    editable: bool = Field(
        ...,
        description=(
            "False where an operator may not write this origin -- an observed "
            "figure is read-only and refreshed only from its source (FR-004)"
        ),
    )
    has_pending_revision: bool = Field(
        False,
        description=(
            "True where an observation diverges beyond the threshold and is "
            "held for review. Pricing keeps using the current figure (FR-042e)"
        ),
    )
    description: str = Field(..., description="What this input is, in words")

    @field_serializer("confidence")
    def _serialise_confidence(self, value: Optional[Decimal]) -> Optional[str]:
        return None if value is None else str(value)


class EntityProvenanceResponse(BaseModel):
    """Every recorded origin for one entity's numeric fields."""

    entity_type: str
    entity_id: UUID
    fields: list[FieldOriginResponse]
    observed_count: int = Field(
        ..., description="How many of these fields rest on evidence rather than a guess"
    )
    total_count: int
    stale_count: int = Field(
        ..., description="How many hand-measured figures are past the threshold"
    )
    staleness_threshold_days: int = Field(
        ..., description="The tenant's own threshold, so the count can be judged"
    )


class ProvenanceWriteRequest(BaseModel):
    """Record where a figure came from.

    ``source`` is restricted to what an operator can legitimately claim.
    ``observed`` is absent on purpose: an observed figure is written by the
    process that observed it, and letting an operator declare one by hand would
    make the label meaningless (FR-004).
    """

    source: str = Field(
        ...,
        description="'measured' for a hand measurement, 'policy' for a decision, "
        "'assumed' to mark a figure as a guess again",
    )
    as_of: Optional[date] = Field(
        None, description="The day it was measured or decided; defaults to today"
    )
    confidence: Optional[Decimal] = Field(
        None,
        gt=0,
        le=1,
        description=(
            "Optional confidence as a fraction between 0 and 1, matching the "
            "column's CHECK. Bounded here rather than only at the database so "
            "a figure out of range is a 422 naming the field, not a 500 from "
            "an integrity error"
        ),
    )

    @field_serializer("confidence")
    def _serialise_confidence(self, value: Optional[Decimal]) -> Optional[str]:
        return None if value is None else str(value)


class EstimateRevisionResponse(BaseModel):
    """A proposal, with everything FR-042c requires it to state."""

    id: UUID
    entity_type: str
    entity_id: UUID
    field_name: str
    current_value: Decimal = Field(..., description="The estimate this would change")
    observed_value: Decimal = Field(..., description="What the outcomes average to")
    divergence_pct: Decimal = Field(..., description="How far apart they were when this was raised")
    derived_from_run_ids: list[str] = Field(
        ..., description="The outcomes behind it, so a reviewer can check them"
    )
    state: str
    observed_as_of: date
    reviewed_by_user_id: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("current_value", "observed_value", "divergence_pct")
    def _serialise_money(self, value: Decimal) -> str:
        return str(value)


class EstimateRevisionListResponse(BaseModel):
    revisions: list[EstimateRevisionResponse]
    total: int
    pending_count: int
