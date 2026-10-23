"""Pydantic schemas for Model API (printed items)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# Risk class: whether a cost is exposed to print failure. The failure premium
# reaches only the at-risk portion — packaging materials and packing labor are
# spent on a part already known good, so they never carry it.
RiskClass = Literal["at_risk", "not_at_risk"]

# Where a figure came from, so a reader knows how much to trust it
# (Constitution VI). See research.md D1.
ProvenanceSource = Literal["policy", "observed", "measured", "assumed"]

# How a yield figure is read when a plate holds more than one print
# (research.md D3).
FailureMode = Literal["per_part", "per_plate"]


class CostLine(BaseModel):
    """One line of a cost breakdown, with its risk class and its provenance.

    Every line carries where its inputs came from and when they were set or
    observed, which is what makes the observed share computable from the
    breakdown alone rather than from a database aggregate.
    """

    key: str = Field(
        ...,
        min_length=1,
        description=(
            "Stable line identifier: material, waste, machine, overhead, "
            "labor_handling, labor_finishing, labor_packing, packaging, "
            "components, child_products"
        ),
    )
    label: str = Field(..., min_length=1, description="Human-readable line name")
    amount: Decimal = Field(..., description="Line amount in the tenant's currency")
    risk_class: RiskClass = Field(..., description="Whether this cost is exposed to print failure")
    source: ProvenanceSource = Field(..., description="Where the inputs behind this line came from")
    as_of: Optional[date] = Field(
        None, description="When the figure was set or observed; null if never recorded"
    )
    has_pending_revision: bool = Field(
        False,
        description=(
            "An observation disputing one of this line's inputs is held for "
            "review (FR-042e). The amount is still the figure in force -- "
            "telemetry proposes and never reprices -- but the line says so "
            "rather than letting the operator read a number the evidence "
            "already contradicts."
        ),
    )

    model_config = ConfigDict(from_attributes=True)


class CostBreakdown(BaseModel):
    """A full make-cost breakdown (data-model.md, 'Cost breakdown shape').

    Recomputed on demand and never stored as an authoritative figure
    (Constitution V); the one exception is the once-written snapshot on a
    settled order line (Constitution VI).

    An incomplete breakdown reports what was missing in ``incomplete_reasons``
    rather than costing the gap at zero (FR-019) — a zero is indistinguishable
    from a real figure, which is the failure this field exists to prevent.
    """

    lines: list[CostLine] = Field(
        default_factory=list, description="Cost lines, in presentation order"
    )

    at_risk_subtotal: Decimal = Field(
        ..., description="Sum of lines exposed to print failure, before the premium"
    )
    not_at_risk_subtotal: Decimal = Field(
        ..., description="Sum of lines spent on a part already known good"
    )

    yield_applied: Decimal = Field(
        ..., gt=0, le=1, description="The yield figure actually applied, a fraction in (0, 1]"
    )
    failure_mode: FailureMode = Field(..., description="How the yield figure was interpreted")
    failure_premium: Decimal = Field(
        ..., description="What the yield figure added to the at-risk subtotal"
    )

    total_make_cost: Decimal = Field(..., description="Total cost to make one sellable unit")

    machine_hours: Optional[Decimal] = Field(
        None,
        description=(
            "Machine occupancy for one sellable unit, bundles included. Null "
            "when no print time is recorded anywhere below it — never zero, "
            "which would read as an item that occupies no machine (FR-019)"
        ),
    )

    observed_share: Decimal = Field(
        ..., ge=0, le=1, description="Share of the cost whose inputs are observed or measured"
    )
    assumed_share: Decimal = Field(
        ..., ge=0, le=1, description="Share of the cost still resting on assumptions"
    )

    incomplete_reasons: list[str] = Field(
        default_factory=list,
        description="What was missing, if anything; empty means fully costed",
    )

    model_config = ConfigDict(from_attributes=True)


class ModelCostBreakdown(BaseModel):
    """The flat model cost breakdown served by the existing endpoints.

    Superseded by :class:`CostBreakdown` once Tier 1 lands (tasks T043, T049).
    Kept, under its own name, so existing routes keep their response shape
    while the structured breakdown is built beside it. It is not a second
    implementation — nothing computes it except the one authoritative engine.
    """

    material_cost: Decimal = Field(..., description="Total material cost from BOM")
    component_cost: Decimal = Field(..., description="Total component cost")
    labor_cost: Decimal = Field(..., description="Labor cost (hours × rate)")
    overhead_cost: Decimal = Field(..., description="Overhead cost")
    total_cost: Decimal = Field(..., description="Total model cost")
    #: What the engine could not cost, in the operator's words.
    #:
    #: Carried here so the flat shape is as honest as the itemised one: a
    #: screen reading this breakdown must be able to tell a cost from a floor
    #: (FR-019). It is projected from the same engine pass as the amounts
    #: above, never recomputed.
    incomplete_reasons: list[str] = Field(
        default_factory=list,
        description="What the engine could not cost; non-empty means the total is a floor",
    )

    model_config = ConfigDict(from_attributes=True)


# Model Material (BOM) schemas
class ModelMaterialBase(BaseModel):
    """Base schema for model materials (BOM entry)."""

    spool_id: UUID = Field(..., description="Spool ID (material type + color + brand)")
    weight_grams: Decimal = Field(..., gt=0, description="Weight of material used in grams")
    cost_per_gram: Decimal = Field(..., ge=0, description="Cost per gram (snapshot)")


class ModelMaterialCreate(ModelMaterialBase):
    """Schema for adding material to model."""

    pass


class ModelMaterialResponse(ModelMaterialBase):
    """Schema for material in model response."""

    id: UUID
    model_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Model Component schemas
class ModelComponentBase(BaseModel):
    """Base schema for model components."""

    component_name: str = Field(..., min_length=1, max_length=200, description="Component name")
    quantity: int = Field(..., gt=0, description="Quantity of this component")
    unit_cost: Decimal = Field(..., ge=0, description="Cost per unit")
    supplier: Optional[str] = Field(None, max_length=200, description="Supplier name")


class ModelComponentCreate(ModelComponentBase):
    """Schema for adding component to model."""

    pass


class ModelComponentResponse(ModelComponentBase):
    """Schema for component in model response."""

    id: UUID
    model_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# Model schemas
class ModelBase(BaseModel):
    """Base model schema with common fields."""

    sku: str = Field(..., min_length=1, max_length=100, description="Stock Keeping Unit")
    name: str = Field(..., min_length=1, max_length=200, description="Model name")
    description: Optional[str] = Field(None, description="Model description")
    category: Optional[str] = Field(None, max_length=100, description="Model category")
    image_url: Optional[str] = Field(None, max_length=500, description="Model image URL")
    labor_hours: Decimal = Field(Decimal("0"), ge=0, description="Labor hours required")
    labor_rate_override: Optional[Decimal] = Field(
        None, ge=0, description="Override labor rate (£/hour)"
    )
    overhead_percentage: Decimal = Field(
        Decimal("0"), ge=0, le=100, description="Overhead percentage (0-100)"
    )
    is_active: bool = Field(True, description="Whether model is active")
    # Metadata fields
    designer: Optional[str] = Field(None, max_length=200, description="Model designer name")
    source: Optional[str] = Field(None, max_length=200, description="Model source platform")
    print_time_minutes: Optional[int] = Field(
        None, ge=0, description="Print time in minutes (for full plate)"
    )
    prints_per_plate: int = Field(
        1,
        ge=1,
        description="Number of items per plate (material weight and print time are divided by this)",
    )
    machine: Optional[str] = Field(None, max_length=100, description="Printer/machine used")
    last_printed_date: Optional[datetime] = Field(
        None, description="Last time this model was printed"
    )
    units_in_stock: Optional[int] = Field(
        0, ge=0, description="Number of printed units in inventory"
    )


class ModelCreate(ModelBase):
    """Schema for creating a new model."""

    pass


class ModelUpdate(BaseModel):
    """Schema for updating a model (all fields optional)."""

    sku: Optional[str] = Field(None, min_length=1, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    image_url: Optional[str] = Field(None, max_length=500)
    labor_hours: Optional[Decimal] = Field(None, ge=0)
    labor_rate_override: Optional[Decimal] = Field(None, ge=0)
    overhead_percentage: Optional[Decimal] = Field(None, ge=0, le=100)
    is_active: Optional[bool] = None
    # Metadata fields
    designer: Optional[str] = Field(None, max_length=200)
    source: Optional[str] = Field(None, max_length=200)
    print_time_minutes: Optional[int] = Field(None, ge=0)
    prints_per_plate: Optional[int] = Field(None, ge=1)
    machine: Optional[str] = Field(None, max_length=100)
    last_printed_date: Optional[datetime] = None
    units_in_stock: Optional[int] = Field(None, ge=0)


class ModelResponse(ModelBase):
    """Schema for model responses (without BOM/components)."""

    id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime
    # Computed cost (included when materials/components are loaded)
    total_cost: Optional[Decimal] = Field(None, description="Total build cost (computed)")
    #: What the engine could not cost, in the operator's words.
    #:
    #: A list screen is where a product is picked, so it is where an item that
    #: is missing its print time or its machine rate must say so rather than
    #: show a finished-looking figure built from a zero. `total_make_cost`
    #: above is still the cost of the lines the engine could resolve; this is
    #: the part it could not, and a non-empty list means the figure is a floor,
    #: not a cost (FR-019).
    incomplete_reasons: list[str] = Field(
        default_factory=list,
        description="What the engine could not cost; non-empty means the cost is a floor (FR-019)",
    )
    # Production cost tracking (Phase 2)
    actual_production_cost: Optional[Decimal] = Field(
        None, description="Rolling average actual production cost per unit from completed runs"
    )
    production_cost_count: int = Field(
        0, description="Number of completed production runs included in rolling average"
    )
    production_cost_updated_at: Optional[datetime] = Field(
        None, description="Last time actual_production_cost was updated"
    )

    model_config = ConfigDict(from_attributes=True)


class ModelDetailResponse(ModelResponse):
    """Schema for detailed model response (with BOM, components, and cost)."""

    materials: list[ModelMaterialResponse] = Field(
        default_factory=list, description="Bill of Materials"
    )
    components: list[ModelComponentResponse] = Field(
        default_factory=list, description="Model components"
    )
    cost_breakdown: ModelCostBreakdown = Field(..., description="Cost breakdown")

    model_config = ConfigDict(from_attributes=True)


# Production Defaults schemas (for auto-populating production runs)
class BOMSpoolSuggestion(BaseModel):
    """Spool suggestion from model BOM with current inventory info."""

    spool_id: UUID = Field(..., description="Spool ID")
    spool_name: str = Field(..., description="Spool name (Brand - Material - Color)")
    material_type_code: str = Field(..., description="Material type code (e.g., PLA, PETG)")
    color: str = Field(..., description="Spool color name")
    color_hex: Optional[str] = Field(None, description="Hex color code")
    weight_grams: Decimal = Field(..., description="Weight from model BOM (grams)")
    cost_per_gram: Decimal = Field(..., description="Cost per gram snapshot")
    current_weight: Decimal = Field(..., description="Current spool weight available (grams)")
    is_active: bool = Field(..., description="Whether spool is active")

    model_config = ConfigDict(from_attributes=True)


class ModelProductionDefaults(BaseModel):
    """Production defaults for a model (BOM, printer, print time)."""

    model_id: UUID = Field(..., description="Model ID")
    sku: str = Field(..., description="Model SKU")
    name: str = Field(..., description="Model name")
    machine: Optional[str] = Field(None, description="Suggested printer/machine")
    print_time_minutes: Optional[int] = Field(
        None, description="Print time for full plate (minutes)"
    )
    prints_per_plate: int = Field(..., description="Number of items per plate")
    bom_materials: list[BOMSpoolSuggestion] = Field(
        default_factory=list, description="Bill of Materials with current inventory"
    )

    model_config = ConfigDict(from_attributes=True)


class ModelListResponse(BaseModel):
    """Schema for paginated model list."""

    models: list[ModelResponse]
    total: int
    skip: int
    limit: int

    model_config = ConfigDict(from_attributes=True)
