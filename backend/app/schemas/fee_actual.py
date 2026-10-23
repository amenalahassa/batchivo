"""Recorded fees: what a statement actually charged (FR-041).

A planned fee and a reconciled one are different figures and must never be
presented as the same thing, which is why ``source`` is on the response and
says ``entered`` -- a figure a human typed from a statement is not an
observation (FR-041e).

Every monetary field is :class:`~decimal.Decimal`. Pydantic will happily
coerce a JSON number into a float if the annotation says so, which is how
binary floating point gets into a money path through the front door;
Constitution IV and ``tests/unit/pricing/test_no_float_in_money_paths.py``
close the back door, and these annotations close this one.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FeeActualCreate(BaseModel):
    """A recorded fee: exactly one of a period scope or an order scope.

    FR-041a and FR-041b. The exclusivity is checked here so the operator gets a
    ``422`` naming both scopes rather than a CHECK violation.
    """

    sales_channel_id: UUID
    fee_category: str = Field(..., min_length=1, max_length=80)
    amount: Decimal = Field(..., description="The amount the statement charged")
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    order_id: Optional[UUID] = None

    @model_validator(mode="after")
    def _exactly_one_scope(self) -> "FeeActualCreate":
        has_period = self.period_start is not None or self.period_end is not None
        has_order = self.order_id is not None

        if has_period and has_order:
            raise ValueError(
                "a recorded fee belongs either to a statement period or to one "
                "order, never to both: a row with both would be counted twice"
            )
        if not has_period and not has_order:
            raise ValueError(
                "a recorded fee needs a scope: either period_start and period_end, or order_id"
            )
        if has_period and (self.period_start is None or self.period_end is None):
            raise ValueError("a period scope needs both period_start and period_end")
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end < self.period_start
        ):
            raise ValueError("period_end cannot be before period_start")
        return self


class FeeActualResponse(BaseModel):
    """Schema for a recorded fee response."""

    id: UUID
    tenant_id: UUID
    sales_channel_id: UUID
    fee_category: str
    amount: Decimal
    period_start: Optional[date]
    period_end: Optional[date]
    order_id: Optional[UUID]
    source: str = Field(
        ..., description="'entered' by a human, never presented as observed (FR-041e)"
    )

    model_config = ConfigDict(from_attributes=True)
