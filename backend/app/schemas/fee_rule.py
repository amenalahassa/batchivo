"""Pydantic schemas for fee rules, actuals, shipping profiles and margin.

Every monetary field is :class:`~decimal.Decimal`. Pydantic will happily coerce
a JSON number into a float if the annotation says so, which is how binary
floating point gets into a money path through the front door; Constitution IV
and ``tests/unit/pricing/test_no_float_in_money_paths.py`` close the back door,
and these annotations close this one.
"""

from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

FeeBasis = Literal[
    "item_subtotal",
    "item_plus_shipping",
    "order_total",
    "per_listing",
    "per_order",
    "per_unit_sold",
    "per_month",
]

ClampApplied = Literal["min", "max"]

MarginBasis = Literal["customer_total", "item_price", "net_revenue"]

TaxRemitter = Literal["marketplace", "operator"]


# ---------------------------------------------------------------------------
# Fee rules
# ---------------------------------------------------------------------------


class FeeRuleBase(BaseModel):
    """The shape of one fee rule as an operator configures it."""

    name: str = Field(..., min_length=1, max_length=80, description="Fee category name")
    basis: FeeBasis = Field(..., description="What the fee is charged on (FR-021)")
    rate_pct: Decimal = Field(
        Decimal("0"), ge=0, le=100, description="Percentage of the basis (6.5 means 6.5%)"
    )
    fixed_amount: Decimal = Field(
        Decimal("0"), ge=0, description="Amount added once the rate is applied"
    )
    min_amount: Optional[Decimal] = Field(
        None, ge=0, description="Floor on the computed amount (FR-021b)"
    )
    max_amount: Optional[Decimal] = Field(
        None, ge=0, description="Cap on the computed amount (FR-021b)"
    )
    incidence_pct: Optional[Decimal] = Field(
        None,
        ge=0,
        le=100,
        description="Share of orders this fee lands on; a planning figure only (FR-029)",
    )
    sort_order: int = Field(0, ge=0, description="Evaluation and presentation order")
    applies_from: date = Field(..., description="First day this rule is charged (FR-022)")
    applies_to: Optional[date] = Field(
        None, description="Last day this rule is charged; null means it still is"
    )

    @model_validator(mode="after")
    def _clamps_must_be_satisfiable(self) -> "FeeRuleBase":
        """FR-021d, refused here as well as by the CHECK.

        Validating in the schema turns it into a ``422`` naming the field,
        rather than an ``IntegrityError`` naming a constraint the operator has
        never heard of.
        """
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError(
                "min_amount cannot exceed max_amount: a floor above a cap is a "
                "rule no amount can satisfy"
            )
        if self.applies_to is not None and self.applies_to < self.applies_from:
            raise ValueError("applies_to cannot be before applies_from")
        return self


class FeeRuleCreate(FeeRuleBase):
    """Schema for creating a fee rule."""


class FeeRuleUpdate(BaseModel):
    """Schema for updating a fee rule; absent fields are left alone."""

    name: Optional[str] = Field(None, min_length=1, max_length=80)
    basis: Optional[FeeBasis] = None
    rate_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    fixed_amount: Optional[Decimal] = Field(None, ge=0)
    min_amount: Optional[Decimal] = Field(None, ge=0)
    max_amount: Optional[Decimal] = Field(None, ge=0)
    incidence_pct: Optional[Decimal] = Field(None, ge=0, le=100)
    sort_order: Optional[int] = Field(None, ge=0)
    applies_from: Optional[date] = None
    applies_to: Optional[date] = None

    def changes(self) -> dict:
        """Only the fields the body actually carried."""
        return self.model_dump(exclude_unset=True)


class FeeRuleResponse(FeeRuleBase):
    """Schema for a fee rule response."""

    id: UUID
    tenant_id: UUID
    sales_channel_id: UUID

    model_config = ConfigDict(from_attributes=True)


class FeeRuleListResponse(BaseModel):
    """Fee rules in ``sort_order``, with the date they were read as at."""

    rules: list[FeeRuleResponse]
    total: int
    as_of: date


# ---------------------------------------------------------------------------
# The itemised stack
# ---------------------------------------------------------------------------


class FeeChargeResponse(BaseModel):
    """One fee as charged, with everything behind it (FR-018, FR-021c)."""

    name: str
    basis: FeeBasis
    amount: Decimal = Field(..., description="The amount, rounded to the cent")
    clamp_applied: Optional[ClampApplied] = Field(
        None, description="Set when a cap or floor changed the amount (FR-021c)"
    )
    is_expected: bool = Field(
        False, description="True when an incidence scaled this into an expectation (FR-029)"
    )
    rate_pct: Decimal = Field(Decimal("0"), description="The rate the rule charges")
    fixed_amount: Decimal = Field(Decimal("0"), description="The fixed amount the rule adds")
    basis_amount: Decimal = Field(
        Decimal("0"), description="The amount or count the rate was applied to"
    )
    incidence_pct: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class FeePreviewRequest(BaseModel):
    """A hypothetical order, for inspecting the stack without creating one."""

    item_subtotal: Decimal = Field(..., ge=0, description="Item lines, tax-exclusive")
    shipping_revenue: Decimal = Field(
        Decimal("0"), ge=0, description="Shipping revenue charged to the customer"
    )
    extras: Decimal = Field(Decimal("0"), ge=0, description="Gift wrap and the like")
    quantity: int = Field(1, ge=1, description="Units on the line")
    listings: int = Field(1, ge=0, description="Live listings, for the periodic view")
    sales_tax_collected: Decimal = Field(Decimal("0"), ge=0)
    amounts_are_tax_inclusive: bool = Field(
        False, description="Whether the amounts above include the tax (FR-028e)"
    )
    # Named `as_of` rather than `date`: a field called `date` shadows the
    # imported `date` type in its own annotation namespace, and pydantic then
    # resolves the annotation to the field's default instead of the type.
    as_of: Optional[date] = Field(None, description="Read the rules in effect on this date")


class FeePreviewResponse(BaseModel):
    """The itemised stack, plus the periodic rules that were not charged."""

    charges: list[FeeChargeResponse]
    total: Decimal
    periodic: list[FeeChargeResponse] = Field(
        default_factory=list,
        description="Per-listing and per-month rules, absorbed over a period instead (FR-025)",
    )
    periodic_total: Decimal = Decimal("0")
    bound_clamps: list[str] = Field(
        default_factory=list, description="Fees whose cap or floor bound (FR-032a)"
    )
    as_of: date
    revenue_tax_exclusive: Decimal
    tax_exclusive_derived: bool = False


# ---------------------------------------------------------------------------
# Shipping profiles
# ---------------------------------------------------------------------------


class ShippingProfileBase(BaseModel):
    """Postage the operator pays, by zone and weight bracket (FR-024)."""

    name: str = Field(..., min_length=1, max_length=100)
    destination_zone: str = Field(..., min_length=1, max_length=50)
    weight_bracket_min_grams: Decimal = Field(Decimal("0"), ge=0)
    weight_bracket_max_grams: Optional[Decimal] = Field(None, gt=0)
    postage_cost: Decimal = Field(..., ge=0, description="What one parcel costs to post")
    carrier: Optional[str] = Field(None, max_length=50)
    effective_from: date

    @model_validator(mode="after")
    def _bracket_must_be_ordered(self) -> "ShippingProfileBase":
        if (
            self.weight_bracket_max_grams is not None
            and self.weight_bracket_max_grams <= self.weight_bracket_min_grams
        ):
            raise ValueError("weight_bracket_max_grams must be above weight_bracket_min_grams")
        return self


class ShippingProfileCreate(ShippingProfileBase):
    """Schema for creating a shipping profile."""


class ShippingProfileUpdate(BaseModel):
    """Schema for updating a shipping profile."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    destination_zone: Optional[str] = Field(None, min_length=1, max_length=50)
    weight_bracket_min_grams: Optional[Decimal] = Field(None, ge=0)
    weight_bracket_max_grams: Optional[Decimal] = Field(None, gt=0)
    postage_cost: Optional[Decimal] = Field(None, ge=0)
    carrier: Optional[str] = Field(None, max_length=50)
    effective_from: Optional[date] = None

    def changes(self) -> dict:
        return self.model_dump(exclude_unset=True)


class ShippingProfileResponse(ShippingProfileBase):
    """Schema for a shipping profile response."""

    id: UUID
    tenant_id: UUID

    model_config = ConfigDict(from_attributes=True)


class ShippingProfileListResponse(BaseModel):
    profiles: list[ShippingProfileResponse]
    total: int


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Margin
# ---------------------------------------------------------------------------


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
