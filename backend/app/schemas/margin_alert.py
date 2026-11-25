"""Realised-versus-planned margin, and the alert it raises (task T134).

In its own module rather than appended to `fee_rule.py`, which had already
accumulated seven resources' schemas (task T138).
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LineMovementResponse(BaseModel):
    """One cost line that came in different from plan (US7 scenario 3)."""

    key: str = Field(..., description="The breakdown line, or 'fees'")
    planned: Decimal = Field(..., description="What the snapshot costed it at")
    realised: Decimal = Field(..., description="What it actually came to")
    delta: Decimal = Field(..., description="Realised less planned; positive means dearer")

    model_config = ConfigDict(from_attributes=True)


class MarginDivergenceResponse(BaseModel):
    """What one settled line earned, beside the margin it was sold at."""

    order_id: UUID
    order_item_id: UUID
    product_id: Optional[UUID]
    product_name: Optional[str]
    sold_on: Optional[date]

    margin_basis: str = Field(..., description="The basis both percentages are on (FR-031b)")
    planned_margin_pct: Optional[Decimal] = Field(
        None, description="Null where fees consumed the whole basis, never zero"
    )
    realised_margin_pct: Optional[Decimal] = Field(
        None, description="Null where fees consumed the whole basis, never zero"
    )
    divergence_points: Optional[Decimal] = Field(
        None,
        description=(
            "Realised less planned, in percentage points. Negative is a shortfall. "
            "Null where either percentage is undefined -- that is unanswerable, "
            "not a divergence."
        ),
    )
    threshold_points: Decimal = Field(
        ..., description="The operator's own alert threshold, in points (FR-042)"
    )
    diverges: bool = Field(..., description="Whether this line is past that threshold")
    shortfall: bool = Field(..., description="True where it earned less than planned")

    planned_profit: Optional[Decimal] = Field(
        None, description="Null where the sale froze no exchange rate (T231)"
    )
    realised_profit: Optional[Decimal] = Field(
        None, description="Null where the sale froze no exchange rate (T231)"
    )
    fx_rate: Optional[Decimal] = Field(
        None, description="The rate frozen at sale, order currency to books"
    )
    fx_rate_date: Optional[date] = Field(None, description="The day that rate applies to")
    fx_rate_source: Optional[str] = Field(None, description="parity, service or manual (FR-028h)")
    snapshot_incomplete: list[str] = Field(
        default_factory=list, description="Why the snapshot was incomplete at sale"
    )

    movements: list[LineMovementResponse] = Field(
        default_factory=list, description="Which lines moved, heaviest first"
    )
    fees_source: str = Field(
        ...,
        description=(
            "'actual' where a statement was reconciled for this order, 'planned' "
            "otherwise. A planned fee is never presented as observed (FR-041e)."
        ),
    )
    substitutions: list[str] = Field(
        default_factory=list, description="Figures that came from an observation"
    )
    gaps: list[str] = Field(default_factory=list, description="Why a figure could not be realised")

    model_config = ConfigDict(from_attributes=True)


class MarginDivergenceListResponse(BaseModel):
    """Settled lines, worst shortfall first."""

    divergences: list[MarginDivergenceResponse]
    total: int
    alerting: int = Field(..., description="How many are past the threshold and should be acted on")
    threshold_points: Decimal
