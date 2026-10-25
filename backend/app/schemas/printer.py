"""Pydantic schemas for Printer API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.schemas.model_cost_profile import CostProfileFieldOrigin


class PrinterBase(BaseModel):
    """Base printer schema with common fields."""

    name: str = Field(
        ..., min_length=1, max_length=100, description="Printer name (e.g., 'Bambu A1 Mini')"
    )
    manufacturer: Optional[str] = Field(None, max_length=100, description="Manufacturer name")
    model: Optional[str] = Field(None, max_length=100, description="Model name")

    # Bed size
    bed_size_x_mm: Optional[int] = Field(None, ge=1, description="Bed size X in millimeters")
    bed_size_y_mm: Optional[int] = Field(None, ge=1, description="Bed size Y in millimeters")
    bed_size_z_mm: Optional[int] = Field(None, ge=1, description="Bed size Z in millimeters")

    # Printer settings
    nozzle_diameter_mm: Optional[Decimal] = Field(
        Decimal("0.4"),
        ge=Decimal("0.1"),
        le=Decimal("2.0"),
        description="Nozzle diameter in millimeters",
    )
    default_bed_temp: Optional[int] = Field(
        None, ge=0, le=200, description="Default bed temperature in Celsius"
    )
    default_nozzle_temp: Optional[int] = Field(
        None, ge=0, le=500, description="Default nozzle temperature in Celsius"
    )

    # Capabilities
    capabilities: Optional[dict[str, Any]] = Field(
        default_factory=dict, description="Printer capabilities (AMS, materials, etc.)"
    )

    # Status
    is_active: bool = Field(True, description="Whether printer is active")

    # Notes
    notes: Optional[str] = Field(None, description="Additional notes")


class PrinterCreate(PrinterBase):
    """Schema for creating a new printer."""

    pass


class PrinterUpdate(BaseModel):
    """Schema for updating a printer (all fields optional)."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    manufacturer: Optional[str] = Field(None, max_length=100)
    model: Optional[str] = Field(None, max_length=100)

    bed_size_x_mm: Optional[int] = Field(None, ge=1)
    bed_size_y_mm: Optional[int] = Field(None, ge=1)
    bed_size_z_mm: Optional[int] = Field(None, ge=1)

    nozzle_diameter_mm: Optional[Decimal] = Field(None, ge=Decimal("0.1"), le=Decimal("2.0"))
    default_bed_temp: Optional[int] = Field(None, ge=0, le=200)
    default_nozzle_temp: Optional[int] = Field(None, ge=0, le=500)

    capabilities: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class PrinterResponse(PrinterBase):
    """Schema for printer responses."""

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def bed_size_str(self) -> Optional[str]:
        """Return bed size as formatted string (e.g., '180x180x180')."""
        if self.bed_size_x_mm and self.bed_size_y_mm and self.bed_size_z_mm:
            return f"{self.bed_size_x_mm}x{self.bed_size_y_mm}x{self.bed_size_z_mm}"
        return None


class PrinterSummary(BaseModel):
    """Lightweight printer summary for embedding in responses and dropdowns."""

    id: UUID
    name: str
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    is_active: bool = True

    model_config = ConfigDict(from_attributes=True)


class PrinterListResponse(BaseModel):
    """Schema for paginated printer list."""

    printers: list[PrinterResponse]
    total: int
    skip: int
    limit: int

    model_config = ConfigDict(from_attributes=True)


class PrinterModelResponse(BaseModel):
    """Schema for a known printer model from the registry."""

    model_key: str
    display_name: str
    manufacturer: str
    connection_type: str
    has_toolhead_changer: bool
    has_ams: bool


# ============================================================================
# Machine cost policy (task T046, FR-010, FR-011, FR-018)
# ============================================================================


class PrinterCostPolicyUpdate(BaseModel):
    """A change to a printer's machine cost policy.

    Unknown keys are forbidden: a mistyped field that silently did nothing
    would leave the operator believing they had entered a machine rate.
    """

    purchase_price: Optional[Decimal] = Field(
        None, ge=0, description="All-in acquisition cost, the numerator of depreciation"
    )
    expected_lifetime_hours: Optional[int] = Field(
        None, gt=0, description="Expected printing hours over the machine's life"
    )
    maintenance_reserve_total: Optional[Decimal] = Field(
        None, ge=0, description="Nozzles, belts, plates and AMS parts over the whole life"
    )
    measured_watts: Optional[Decimal] = Field(
        None, ge=0, description="Measured draw at the wall while printing, not the nameplate"
    )
    electricity_rate_per_kwh: Optional[Decimal] = Field(
        None, ge=0, description="Per-printer rate; falls back to the tenant pricing policy"
    )

    model_config = ConfigDict(extra="forbid")


class PrinterCostPolicyResponse(BaseModel):
    """A printer's machine cost policy, its derived rate and the rate's parts.

    ``machine_rate_per_hour`` is null when nothing could be derived — FR-019
    reports a missing figure rather than a zero, because a zero makes a
    40-hour print look free. ``components`` and ``missing`` are what let the
    rate be explained without recomputing it (FR-018).
    """

    printer_id: UUID
    purchase_price: Optional[Decimal] = None
    expected_lifetime_hours: Optional[int] = None
    maintenance_reserve_total: Optional[Decimal] = None
    measured_watts: Optional[Decimal] = None
    electricity_rate_per_kwh: Optional[Decimal] = Field(
        None, description="This printer's own rate; null when it uses the tenant policy's"
    )
    effective_electricity_rate_per_kwh: Optional[Decimal] = Field(
        None, description="The rate actually used, whether the printer's own or the tenant's"
    )

    machine_rate_per_hour: Optional[Decimal] = Field(
        None, description="Derived hourly occupancy cost, or null when unknowable"
    )
    components: dict[str, Decimal] = Field(
        default_factory=dict, description="The parts the rate is made of, each named"
    )
    missing: list[str] = Field(
        default_factory=list, description="Inputs the operator has not supplied yet"
    )
    origins: list[CostProfileFieldOrigin] = Field(
        default_factory=list,
        description=(
            "Where each policy figure came from; an observed draw is not editable (FR-004, T262)"
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class PowerReadingIn(BaseModel):
    """One smart-plug reading of a machine's draw (FR-042, task T159).

    ``source_id`` identifies the reading, not the plug: FR-042d compares
    proposals by the outcomes behind them, so a reading an operator already
    rejected must stay identifiable or the same question is asked again
    tomorrow.

    ``watts`` is a `Decimal`, because the engine multiplies it by an
    electricity rate to reach a machine cost (Constitution IV).
    """

    source_id: str = Field(..., min_length=1, max_length=120)
    watts: Decimal = Field(..., gt=0, le=Decimal("100000"))
    observed_on: Optional[date] = Field(
        None, description="The day the reading was taken; today when omitted"
    )


class PowerReadingBatch(BaseModel):
    """A set of readings for one machine."""

    readings: list[PowerReadingIn] = Field(..., min_length=1, max_length=500)


class PowerReadingResult(BaseModel):
    """What the readings did to the machine's recorded draw.

    A reading never simply overwrites the figure: it becomes a rolling average
    once enough agree (FR-042a), is held as a proposal beyond the operator's
    divergence threshold (FR-042b), and never touches a figure the operator
    set themselves (FR-042g). The reason is in words because each of those
    outcomes is something an operator will ask about.
    """

    printer_id: UUID
    readings_accepted: int
    applied: bool
    reason: str
    observed_value: Optional[Decimal] = None
    divergence_pct: Optional[Decimal] = None
    proposal_id: Optional[UUID] = None
    superseded_proposal_id: Optional[UUID] = None
    measured_watts: Optional[Decimal] = Field(
        None, description="The draw in force after the readings were considered"
    )
