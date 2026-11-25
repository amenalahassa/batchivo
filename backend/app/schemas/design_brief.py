"""Schemas for design briefs (spec 009, contracts/api.md "Design briefs")."""

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.model_file_version import PersonRef

StepName = Literal[
    "intent",
    "adopt",
    "clarify",
    "risk",
    "plan",
    "design",
    "check",
    "slice",
    "print",
    "test",
    "learn",
    "render",
    "ship",
    "quick",
]
StepStatus = Literal["not_started", "in_progress", "done", "skipped", "blocked"]
RiskClass = Literal["faible", "moyen", "élevé", "arrêt"]
RevisionPart = Literal["intent", "risk", "plan"]

MAX_TEXT = 100_000


class RiskPart(BaseModel):
    """The risk part of a brief, replaced as a whole (risk.md, class, triage JSON)."""

    risk_class: Optional[RiskClass] = Field(None, description="pf.py triage risk_class")
    risk_md: Optional[str] = Field(None, max_length=MAX_TEXT, description="risk.md as written")
    triage: Optional[dict[str, Any]] = Field(None, description="pf.py triage output as written")


class DesignBriefStart(BaseModel):
    """Optional first intent when starting a brief."""

    intent: Optional[dict[str, Any]] = None
    intent_yaml: Optional[str] = Field(None, max_length=MAX_TEXT * 3)

    @model_validator(mode="after")
    def _one_intent(self) -> "DesignBriefStart":
        if self.intent is not None and self.intent_yaml is not None:
            raise ValueError("Send the intent either as `intent` or as `intent_yaml`, not both")
        return self


class DesignBriefUpdate(DesignBriefStart):
    """Any subset of a brief's parts (at least one)."""

    risk: Optional[RiskPart] = None
    plan_md: Optional[str] = Field(None, max_length=MAX_TEXT)
    params: Optional[dict[str, Any]] = None
    params_yaml: Optional[str] = Field(None, max_length=MAX_TEXT * 3)
    steps: Optional[dict[StepName, StepStatus]] = None

    @model_validator(mode="after")
    def _something(self) -> "DesignBriefUpdate":
        if self.params is not None and self.params_yaml is not None:
            raise ValueError("Send the parameters either as `params` or as `params_yaml`, not both")
        if not self.model_fields_set:
            raise ValueError("Nothing to update")
        return self


class StepState(BaseModel):
    step: StepName
    status: StepStatus
    updated_at: Optional[datetime] = None
    updated_by: Optional[PersonRef] = None


class IntentValidation(BaseModel):
    """Same keys as `pf.py validate` (plus missing required keys)."""

    to_clarify: list[str] = []
    unconfirmed: list[dict[str, str]] = []
    missing: list[str] = []


class DesignBriefResponse(BaseModel):
    id: UUID
    idea_id: Optional[UUID] = None
    model_id: Optional[UUID] = None
    idea_title: Optional[str] = None
    model_name: Optional[str] = None
    intent: Optional[dict[str, Any]] = None
    intent_schema_version: Optional[int] = None
    risk_class: Optional[str] = None
    risk_md: Optional[str] = None
    triage: Optional[dict[str, Any]] = None
    plan_md: Optional[str] = None
    params: Optional[dict[str, Any]] = None
    params_updated_at: Optional[datetime] = None
    steps: list[StepState]
    validation: IntentValidation
    revision_counts: dict[str, int]
    created_by: Optional[PersonRef] = None
    updated_by: Optional[PersonRef] = None
    created_at: datetime
    updated_at: datetime


class DesignBriefUpdateResult(DesignBriefResponse):
    created_revisions: list[RevisionPart] = []


class DesignBriefRevisionResponse(BaseModel):
    id: UUID
    part: RevisionPart
    content: dict[str, Any]
    schema_version: Optional[int] = None
    author: Optional[PersonRef] = None
    created_at: datetime
