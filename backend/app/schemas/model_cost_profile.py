"""The operational figures of a printed item, and how they are edited (T147).

Tier 1 gave `Model` a cost profile — purge waste, expected yield, the failure
mode and the four-way labor split — and the engine reads every one of them
(`app/services/costing.py`). Nothing could *write* them: `ModelCreate` and
`ModelUpdate` carried the deprecated `labor_hours` and nothing else, so every
item in every tenant sat at its migration defaults. A waste line of zero, a
yield of 1.0 and a labor split of zero are not neutral defaults — they are the
old model's answer, which is the answer this feature exists to replace.

It is its own resource rather than seven more fields on `ModelUpdate` because
the role boundary runs between them. These are *measurements* of a printed
item, editable by a member (FR-007b); the labor rate and overhead percentage
beside them on the same table are monetary *policy* and need an administrator
(FR-007a). One schema would have to pick one rule for both.

The same split is why a write here records provenance as `measured` and not as
`policy`: an operator timed the finishing, they did not decide it (FR-001).
"""

from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: How a yield figure is read when a plate holds more than one print (FR-015a).
FailureMode = Literal["per_part", "per_plate"]


class ModelCostProfileUpdate(BaseModel):
    """A change to one printed item's operational figures.

    Every field is optional and a field the body does not name is left alone,
    so recording the finishing time next week does not erase the purge weight
    measured today. Unknown keys are forbidden: a mistyped field that silently
    did nothing would leave the operator believing they had entered a yield.
    """

    print_time_minutes: Optional[int] = Field(
        None, ge=0, description="Machine occupancy for one plate, in minutes (FR-010)"
    )
    prints_per_plate: Optional[int] = Field(
        None, ge=1, description="How many parts share one plate; the batching quantity (FR-013)"
    )
    waste_grams: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Purge, priming and colour-change filament for one plate, costed separately (FR-009)",
    )
    expected_yield: Optional[Decimal] = Field(
        None,
        gt=0,
        le=1,
        description="Share of starts that reach a sellable part, in (0, 1]; 1.0 means no premium",
    )
    failure_mode: Optional[FailureMode] = Field(
        None,
        description=(
            "'per_part' where parts fail independently, 'per_plate' where one "
            "failure condemns the plate (FR-015a)"
        ),
    )
    labor_hours_per_plate: Optional[Decimal] = Field(
        None, ge=0, description="Preparation a plate needs once, divided across its output (FR-013)"
    )
    labor_hours_per_item: Optional[Decimal] = Field(
        None, ge=0, description="Handling per item, never divided across a plate (FR-013)"
    )
    finishing_hours_per_item: Optional[Decimal] = Field(
        None, ge=0, description="Finishing per item, charged at the finishing rate (FR-012)"
    )
    packing_hours_per_item: Optional[Decimal] = Field(
        None,
        ge=0,
        description="Packing per item — never exposed to the failure premium (FR-015, FR-016)",
    )

    model_config = ConfigDict(extra="forbid")


class CostProfileFieldOrigin(BaseModel):
    """Where one figure on the profile came from, and when (FR-001)."""

    field_name: str
    source: str = Field(..., description="policy | observed | measured | assumed")
    as_of: Optional[date] = Field(
        None, description="When the figure was set or last observed; null means never recorded"
    )
    is_stale: bool = Field(
        False,
        description=(
            "A measured figure past the tenant's staleness threshold. Still in "
            "use and still shown — FR-005 flags it rather than blanking it."
        ),
    )
    editable: bool = Field(
        True,
        description="False for an observed figure, which is refreshed from its source (FR-004)",
    )

    model_config = ConfigDict(from_attributes=True)


class ModelCostProfileResponse(BaseModel):
    """One printed item's operational figures, each with its provenance.

    ``origins`` is keyed by field name rather than folded into the values
    because a figure and its origin are different facts, and a screen that
    shows a cost shows how much of it is evidence (FR-001, FR-046).
    """

    model_id: UUID
    print_time_minutes: Optional[int] = None
    prints_per_plate: int
    waste_grams: Decimal
    expected_yield: Decimal
    failure_mode: FailureMode
    labor_hours_per_plate: Decimal
    labor_hours_per_item: Decimal
    finishing_hours_per_item: Decimal
    packing_hours_per_item: Decimal

    origins: list[CostProfileFieldOrigin] = Field(
        default_factory=list, description="One entry per numeric figure above (FR-001)"
    )
    incomplete_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Inputs the engine needs and does not have. FR-019 reports these "
            "rather than costing the line at zero."
        ),
    )

    model_config = ConfigDict(from_attributes=True)
