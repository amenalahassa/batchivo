"""One channel over one period: plan against statement (FR-041d, FR-025).

The reconciliation names each fee category's planned and actual amounts rather
than one difference, because "fees were nine pounds over" sends an operator
hunting while "the transaction fee was six over and offsite ads three" is
something they can act on.

A periodic cost over a period with no orders is reported as **unabsorbed**
rather than divided by zero: a channel that sold nothing has not become free.

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

from pydantic import BaseModel, Field

from app.schemas.pricing_literals import MarginBasis


class CategoryReconciliationResponse(BaseModel):
    """Plan against statement for one fee category (FR-041d)."""

    category: str
    planned: Decimal
    actual_period: Optional[Decimal]
    actual_order_scoped: Decimal
    unallocated_remainder: Optional[Decimal]
    actual_total: Optional[Decimal]
    difference: Optional[Decimal]
    difference_pct_of_fee: Optional[Decimal]


class AbsorbedCostResponse(BaseModel):
    """A periodic cost spread over the period's order volume (FR-025)."""

    key: str
    label: str
    total: Decimal
    order_count: int
    per_order: Optional[Decimal] = Field(
        None, description="Null when there were no orders to absorb it over"
    )
    is_unabsorbed: bool


class ChannelPnLResponse(BaseModel):
    """One channel over one period."""

    channel_id: UUID
    period_start: date
    period_end: date
    order_count: int

    revenue_tax_exclusive: Decimal
    sales_tax_collected: Decimal = Field(
        ..., description="Shown as a liability below, never as revenue (FR-028c)"
    )
    sales_tax_liability: Decimal

    postage_paid: Decimal
    shipping_revenue: Decimal
    shipping_net: Decimal

    planned_fee_total: Decimal
    actual_fee_total: Optional[Decimal]
    unallocated_remainder: Decimal
    fee_difference: Optional[Decimal]
    reconciliation: list[CategoryReconciliationResponse]

    absorbed_costs: list[AbsorbedCostResponse]
    unabsorbed_total: Decimal

    make_cost_total: Decimal
    profit: Decimal
    margin_pct: Optional[Decimal]
    margin_basis: MarginBasis
    margin_basis_label: str
