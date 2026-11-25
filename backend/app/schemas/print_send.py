"""Schemas for sending a print to a Bambu printer (spec 011, contracts/print-send-api.md).

The two-step API (prepare, then confirm) takes nothing browser-specific, so an
MCP client (spec 010) calls it exactly as the web app does.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

#: Grams travel as decimal strings (Constitution IV: never a binary float).
Grams = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.2f}", return_type=str)]


# ============================================
# Slot mapping (request)
# ============================================


class AmsSlot(BaseModel):
    """An AMS slot: unit 0-3, tray 0-3."""

    kind: Literal["ams"] = "ams"
    ams_id: int = Field(..., ge=0, le=3)
    tray_id: int = Field(..., ge=0, le=3)

    model_config = ConfigDict(extra="forbid")


class ExternalSlot(BaseModel):
    """The external spool holder."""

    kind: Literal["external"] = "external"

    model_config = ConfigDict(extra="forbid")


SlotRef = Annotated[Union[AmsSlot, ExternalSlot], Field(discriminator="kind")]


class AmsMappingEntry(BaseModel):
    """Which slot feeds one filament of the plate."""

    filament_id: int = Field(..., ge=1, description="Slicer filament number (1-based)")
    slot: SlotRef

    model_config = ConfigDict(extra="forbid")


class AmsMapping(BaseModel):
    """The full mapping sent with a prepare request."""

    entries: list[AmsMappingEntry] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> "AmsMapping":
        filaments = [e.filament_id for e in self.entries]
        if len(set(filaments)) != len(filaments):
            raise ValueError("Each filament can be mapped only once")
        slots = [(e.slot.ams_id, e.slot.tray_id) for e in self.entries if e.slot.kind == "ams"]
        if len(set(slots)) != len(slots):
            raise ValueError("Two filaments are mapped to the same AMS slot")
        return self


# ============================================
# Summary (responses)
# ============================================


class SlotView(BaseModel):
    """A mapped slot as shown on the summary."""

    kind: Literal["ams", "external"]
    ams_id: Optional[int] = None
    tray_id: Optional[int] = None
    label: str


class ExpectedFilament(BaseModel):
    """What the sliced plate expects for one filament."""

    type: Optional[str] = None
    color: Optional[str] = None
    grams: Optional[Grams] = None


class MappedSpool(BaseModel):
    """The spool Batchivo believes is loaded in the slot."""

    id: UUID
    spool_id: str
    material: Optional[str] = None
    color: Optional[str] = None
    current_weight: Optional[Grams] = None


class ReportedTray(BaseModel):
    """What the printer last reported in the slot."""

    type: Optional[str] = None
    color: Optional[str] = None
    present: bool


class PrintSendLine(BaseModel):
    """One filament of the plate, its slot, and what is loaded there."""

    filament_id: int
    expected: ExpectedFilament
    slot: SlotView
    mapped_spool: Optional[MappedSpool] = None
    reported: Optional[ReportedTray] = None
    warnings: list[str] = Field(default_factory=list)


class PrintSendWarning(BaseModel):
    """A warning (acknowledgeable) or a blocker (prevents confirmation)."""

    code: str
    message: str
    filament_id: Optional[int] = None


class PrinterRef(BaseModel):
    id: UUID
    name: str


class FileRef(BaseModel):
    name: str
    model_id: Optional[UUID] = None
    model_file_id: Optional[UUID] = None


class PlateView(BaseModel):
    index: int
    print_time_minutes: Optional[int] = None
    filament_weight_grams: Optional[Grams] = None


class UserRef(BaseModel):
    """Who took an action (FR-018)."""

    id: UUID
    name: str


class PrintJobRef(BaseModel):
    id: UUID
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ConsumptionLine(BaseModel):
    """One spool of the deduction proposal."""

    filament_id: int
    spool_id: Optional[UUID] = None
    proposed_grams: Grams
    accepted_grams: Optional[Grams] = None
    transaction_id: Optional[UUID] = None


class ConsumptionView(BaseModel):
    status: Literal["none", "pending", "accepted", "dismissed"]
    lines: list[ConsumptionLine] = Field(default_factory=list)
    decided_at: Optional[datetime] = None


class PrintSendSummary(BaseModel):
    """Fields shared by the prepare response and later reads."""

    id: UUID
    status: str
    expires_at: datetime
    printer: PrinterRef
    file: FileRef
    plate: PlateView
    lines: list[PrintSendLine]
    warnings: list[PrintSendWarning]
    blockers: list[PrintSendWarning]
    requires_acknowledgement: bool


class PrintSendPrepared(PrintSendSummary):
    """Prepare response: the summary plus the confirmation token, shown once."""

    confirmation_token: str


class PrintSendResponse(PrintSendSummary):
    """A send as read later (never carries the token)."""

    created_at: datetime
    confirmed_at: Optional[datetime] = None
    confirmed_by: Optional[UserRef] = None
    warnings_acknowledged: bool = False
    error_message: Optional[str] = None
    print_job: Optional[PrintJobRef] = None
    consumption: ConsumptionView


class PrintSendListResponse(BaseModel):
    items: list[PrintSendResponse]


# ============================================
# Requests
# ============================================


class PrintSendConfirm(BaseModel):
    """Confirmation of a prepared summary.

    ``extra="forbid"``: a confirmation cannot change the file, plate or
    mapping of what was shown (FR-007); a different send needs a new prepare.
    """

    confirmation_token: str = Field(..., min_length=20, max_length=200)
    acknowledge_warnings: bool = False

    model_config = ConfigDict(extra="forbid")


class ConsumptionAcceptLine(BaseModel):
    filament_id: int = Field(..., ge=1)
    spool_id: UUID
    grams: Decimal = Field(..., gt=0, le=Decimal("99999.99"), decimal_places=2)

    model_config = ConfigDict(extra="forbid")


class ConsumptionAccept(BaseModel):
    lines: list[ConsumptionAcceptLine] = Field(..., min_length=1)

    model_config = ConfigDict(extra="forbid")


class FileTransferTestResult(BaseModel):
    ok: bool
    message: str
