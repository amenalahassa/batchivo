"""What one unit earns on one channel (FR-018, FR-031).

The margin percentage always arrives with the basis that produced it (FR-031b),
and it is null rather than zero where the basis is zero -- net revenue after
fees, with the fees consuming the whole amount. Zero would read as a sale that
broke even.

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

from app.schemas.fee_rule import FeeChargeResponse
from app.schemas.pricing_literals import MarginBasis, TaxRemitter


class RevenueDeductionResponse(BaseModel):
    """A reserve held against revenue: not a fee and not a cost (FR-026)."""

    key: str
    label: str
    amount: Decimal
    rate_pct: Decimal
    basis_amount: Decimal


class ProductMarginResponse(BaseModel):
    """What one unit earns on one channel at the price in effect.

    The margin percentage always arrives with the basis that produced it
    (FR-031b), and ``margin_pct`` is null rather than zero where the basis is
    zero -- net revenue after fees, with fees consuming the whole amount.
    """

    product_id: UUID
    sales_channel_id: UUID
    as_of: date

    list_price: Decimal
    shipping_revenue: Decimal
    postage_paid: Decimal
    shipping_net: Decimal

    make_cost: Decimal
    fees: list[FeeChargeResponse]
    fee_total: Decimal
    deductions: list[RevenueDeductionResponse]
    deduction_total: Decimal

    net_revenue: Decimal
    profit: Decimal
    margin_pct: Optional[Decimal]
    margin_basis: MarginBasis
    margin_basis_label: str
    margin_basis_amount: Decimal

    #: FR-043. Null where the unit occupies no machine time, never zero: a
    #: hand-assembled item has no figure here, and zero would rank it as the
    #: least profitable use of a printer it never touches.
    profit_per_machine_hour: Optional[Decimal] = Field(
        None, description="Profit divided by the machine hours the unit occupies (FR-043)"
    )
    machine_hours: Optional[Decimal] = Field(
        None, description="The hours the figure above was divided by"
    )

    sales_tax_collected: Decimal
    sales_tax_liability: Decimal
    tax_remitter: TaxRemitter
    tax_exclusive_derived: bool
    revenue_tax_exclusive: Decimal

    observed_share: Optional[Decimal] = Field(
        None, description="Share of the make-cost whose inputs are observed or measured"
    )
    assumed_share: Optional[Decimal] = None
    incomplete_reasons: list[str] = Field(default_factory=list)
