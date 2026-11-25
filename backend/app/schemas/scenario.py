"""Request and response shapes for catalogue-wide scenarios (FR-044).

Money and percentages cross the wire as decimal **strings**, never as JSON
numbers (Constitution IV): a margin that arrives as a float has already lost
the exactness the engine computed it with.

The request is deliberately small. A scenario asks one question -- "if these
figures moved, what stops paying?" -- and every lever it offers is a relative
percentage change, because "filament up 25%" is a question about a catalogue
of two hundred products where "cost per gram = 0.04" is not a question about
anything.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioShockRequest(BaseModel):
    """The overrides to apply, each a relative percentage change.

    Floored at -100%, which is where a cost reaches zero. Below that the sweep
    would price a catalogue against negative costs and present the result as
    analysis.
    """

    material_cost_pct: Decimal = Field(
        Decimal("0"), ge=-100, description="Relative change to every material's cost per gram"
    )
    labor_rate_pct: Decimal = Field(
        Decimal("0"), ge=-100, description="Relative change to the labor rates in the policy"
    )
    fee_rate_pct: Decimal = Field(
        Decimal("0"), ge=-100, description="Relative change to every channel fee rate"
    )
    electricity_rate_pct: Decimal = Field(
        Decimal("0"), ge=-100, description="Relative change to the electricity rate"
    )

    @model_validator(mode="after")
    def _must_change_something(self) -> "ScenarioShockRequest":
        if all(
            value == Decimal("0")
            for value in (
                self.material_cost_pct,
                self.labor_rate_pct,
                self.fee_rate_pct,
                self.electricity_rate_pct,
            )
        ):
            # A shock of zero is the margin report, which one request already
            # answers. Queueing a catalogue sweep for it would be a second way
            # to ask an answered question, and the result would read as a
            # forecast while being a restatement (Constitution III).
            raise ValueError("a scenario must change at least one figure")
        return self


class ScenarioRunRequest(BaseModel):
    """A shock, and the margin below which a product should be reported."""

    shock: ScenarioShockRequest
    margin_floor_pct: Decimal = Field(
        ...,
        ge=-100,
        le=100,
        description="Report products whose shocked margin falls below this (FR-044)",
    )
    sales_channel_id: Optional[UUID] = Field(
        None, description="Limit the sweep to one channel; omitted, every listed channel"
    )


class ScenarioRunResponse(BaseModel):
    """One run: its state, what it was asked, and what it found.

    ``result`` is null until the run finishes, which is the honest reading of a
    queued job: nothing has been found yet, as against nothing being wrong.
    ``error_text`` is set only for a failure, and a failure always has one --
    a job that stops without a reason is the one outcome FR-044b forbids.
    """

    id: UUID
    state: str
    shock: dict[str, Any]
    margin_floor_pct: Decimal
    inputs: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    error_text: Optional[str] = None

    requested_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def of(cls, run: Any) -> "ScenarioRunResponse":
        """Built explicitly rather than by attribute name.

        The column is ``shock_json`` and the field is ``shock``: the suffix is
        a storage detail and does not belong in the contract.
        """
        return cls(
            id=run.id,
            state=run.state,
            shock=run.shock_json or {},
            margin_floor_pct=run.margin_floor_pct,
            inputs=run.inputs_json,
            result=run.result_json,
            error_text=run.error_text,
            requested_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )


class ScenarioRunListResponse(BaseModel):
    """A tenant's scenario history, newest first."""

    runs: list[ScenarioRunResponse]
    total: int
