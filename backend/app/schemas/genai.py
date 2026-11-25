"""Request and response schemas of the generative AI API (spec 008, contracts/genai-api.md).

Money is US dollars (clarification Q1), serialised as decimal strings, never floats.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer
from typing_extensions import Annotated

Money = Annotated[Decimal, PlainSerializer(lambda v: format(v, "f"), return_type=str)]

TargetType = Literal["idea", "product", "model", "none"]


class JobTarget(BaseModel):
    type: TargetType = "none"
    id: Optional[uuid.UUID] = None


class GenerationJobCreate(BaseModel):
    """Start a generation: a capability, its inputs, and what it is for."""

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(..., min_length=1, max_length=40)
    inputs: dict[str, Any] = Field(default_factory=dict)
    target: JobTarget = Field(default_factory=JobTarget)


class PriceInfo(BaseModel):
    unit: str
    amount_usd: str
    source: str = "catalog"
    assumed: bool = False


class UserRef(BaseModel):
    id: uuid.UUID
    name: Optional[str] = None


class AdoptionInfo(BaseModel):
    owner_type: str
    owner_id: uuid.UUID
    idea_entry_id: Optional[uuid.UUID] = None
    product_image_id: Optional[uuid.UUID] = None
    model_file_id: Optional[uuid.UUID] = None
    warning_confirmed: bool = False
    created_at: datetime


class GenAIAssetResponse(BaseModel):
    id: uuid.UUID
    job_id: Optional[uuid.UUID] = None
    source: str
    kind: str
    content_type: str
    file_size: int
    width: Optional[int] = None
    height: Optional[int] = None
    position: int = 0
    original_filename: Optional[str] = None
    ai_generated: bool
    file_path: str
    thumbnail_path: Optional[str] = None
    adoptions: list[AdoptionInfo] = Field(default_factory=list)
    created_at: datetime


class GenerationJobResponse(BaseModel):
    id: uuid.UUID
    capability: str
    capability_label: str
    provider: str
    model_ref: str
    model_version: str
    model_version_ran: Optional[str] = None
    inputs: dict[str, Any]
    seed: int
    target: JobTarget
    status: str
    error: Optional[str] = None
    error_code: Optional[str] = None
    estimated_cost: Money
    cost: Optional[Money] = None
    cost_provenance: Optional[str] = None
    currency: str = "USD"
    price: PriceInfo
    shows_real_item: bool
    requested_by: Optional[UserRef] = None
    created_at: datetime
    submitted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    outputs: list[GenAIAssetResponse] = Field(default_factory=list)
    can_cancel: bool


class GenerationJobList(BaseModel):
    items: list[GenerationJobResponse]
    total: int


class CapabilityInfo(BaseModel):
    capability: str
    label: str
    output_kind: str
    model_ref: str
    model_version: str
    pinnable: bool
    overridden: bool
    price: PriceInfo
    #: per input field: required, min_length/max_length (text), min/max (numbers and
    #: image lists), values (choices), default; derived from the service's validation
    inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    max_count: int
    #: how many input images the operator may pick (concept_image: with references)
    max_inputs: int
    time_limit_s: int
    shows_real_item: bool


class CapabilitiesResponse(BaseModel):
    connected: bool
    token_source: str
    currency: str = "USD"
    capabilities: list[CapabilityInfo]


class EstimateResponse(BaseModel):
    estimated_cost: Money
    month_to_date: Money
    budget: Optional[Money] = None
    would_exceed_budget: bool
    currency: str = "USD"


class AdoptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: JobTarget
    confirm_not_real_item: bool = False
    alt_text: Optional[str] = Field(None, max_length=255)
    version_note: Optional[str] = Field(None, max_length=2000)


class AdoptResponse(BaseModel):
    adoption: AdoptionInfo
    idea_entry_id: Optional[uuid.UUID] = None
    product_image_id: Optional[uuid.UUID] = None
    model_file_id: Optional[uuid.UUID] = None
    model_file_version_id: Optional[uuid.UUID] = None


class PlatformGenaiSettings(BaseModel):
    tenant_id: uuid.UUID
    platform_token_allowed: bool
    platform_token_available: bool
    all_tenants: bool = False


class PlatformGenaiUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform_token_allowed: bool


__all__ = [
    "AdoptRequest",
    "AdoptResponse",
    "AdoptionInfo",
    "CapabilitiesResponse",
    "CapabilityInfo",
    "EstimateResponse",
    "GenAIAssetResponse",
    "GenerationJobCreate",
    "GenerationJobList",
    "GenerationJobResponse",
    "JobTarget",
    "Money",
    "PlatformGenaiSettings",
    "PlatformGenaiUpdate",
    "PriceInfo",
    "UserRef",
]
