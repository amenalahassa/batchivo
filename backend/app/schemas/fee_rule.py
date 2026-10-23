"""Fee rules, and the itemised stack they produce.

A rule is what a channel charges, entered from its published fee schedule and
effective-dated (FR-021, FR-022). The stack is what those rules came to on one
order, itemised rather than totalled, because a single blended percentage
cannot represent a marketplace that also charges processing and a regulatory
fee (FR-018, FR-021c).

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

from app.schemas.pricing_literals import ClampApplied, FeeBasis


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
