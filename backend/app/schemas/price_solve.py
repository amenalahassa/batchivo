"""The target-margin solver's request and answer (FR-032 -- FR-035).

Field names follow contracts/pricing-api.md: ``required_price_raw`` and
``required_price_rounded`` rather than one ``price``, because the pair is the
point. The raw figure is what the arithmetic produced and the rounded one is
what the operator would charge, and an interface showing only the second cannot
be checked against the first (FR-033, FR-034).

The answer is a **proposal**. Nothing is published to any channel; applying it
is a separate write on the price (US4 scenario 5).

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

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.fee_rule import FeeChargeResponse
from app.schemas.pricing_literals import MarginBasis


class PriceSolveRequest(BaseModel):
    """A target margin, and the sale it should be achieved on (FR-032).

    ``margin_basis`` is normally left unset so the operator's own policy
    decides (FR-031); passing one is for a screen comparing the same target
    across bases, which is a read rather than a change of policy.
    """

    target_margin_pct: Decimal = Field(
        ...,
        ge=0,
        lt=100,
        description="The margin to achieve, on the basis in effect (FR-032)",
    )
    quantity: int = Field(1, ge=1, description="Units on the hypothetical line")
    shipping_revenue: Decimal = Field(
        Decimal("0"), ge=0, description="Shipping revenue charged to the customer"
    )
    extras: Decimal = Field(Decimal("0"), ge=0, description="Gift wrap and the like")
    margin_basis: Optional[MarginBasis] = Field(
        None, description="Overrides the operator's policy for this read only"
    )
    apply_rounding: bool = Field(
        True, description="Apply the operator's rounding rule to the answer (FR-033)"
    )
    rounding_rule: Optional[str] = Field(
        None,
        max_length=30,
        description="Overrides the channel's rounding rule for this read (FR-033)",
    )
    snap_to_free_shipping: bool = Field(
        True,
        description=(
            "Lift the price to the channel's free-shipping threshold where it "
            "falls short of one (FR-033). Safe as a default because the result "
            "is a proposal that publishes nothing"
        ),
    )
    as_of: Optional[date] = Field(
        None, description="Read the fee rules and policy in effect on this date"
    )


class PriceAdjustmentResponse(BaseModel):
    """One deliberate move away from the solved price, named (FR-033)."""

    key: str
    label: str
    from_price: Decimal
    to_price: Decimal
    delta: Decimal

    model_config = ConfigDict(from_attributes=True)


class PriceSolveResponse(BaseModel):
    """The price, what moved it, and everything behind it (FR-032 -- FR-035).

    Served with ``200`` when a price exists. Where none does the endpoint
    answers ``422`` instead, carrying this same shape in ``detail`` with
    ``reason = "unachievable"`` and every price field null -- a very large
    number would read as an answer, which is what FR-035 exists to prevent.

    The result is a **proposal**. Nothing is published to any channel; applying
    it is a separate write on the price (US4 scenario 5).
    """

    product_id: UUID
    sales_channel_id: UUID
    as_of: date

    achievable: bool
    reason: Optional[str] = Field(None, description='"unachievable" when no price exists (FR-035)')
    binding_constraint: Optional[str] = Field(
        None, description="Which constraint made it unachievable, in words (FR-035)"
    )

    target_margin_pct: Decimal
    margin_basis: MarginBasis
    margin_basis_label: str

    required_price_raw: Optional[Decimal] = Field(
        None, description="The closed-form answer, before any rounding or snap"
    )
    required_price_rounded: Optional[Decimal] = Field(
        None, description="The price to charge: the raw price with every adjustment applied"
    )
    adjustments: list[PriceAdjustmentResponse] = Field(
        default_factory=list, description="In the order they were applied (FR-033)"
    )
    binding_clamps: list[str] = Field(
        default_factory=list,
        description="Fees whose cap or floor bound at the price returned (FR-032a)",
    )

    margin_pct_at_price: Optional[Decimal] = Field(
        None,
        description=(
            "The margin actually achieved. It exceeds the target by whatever "
            "the rounding moved, since every rounding rule rounds up"
        ),
    )
    profit_at_price: Optional[Decimal] = None

    make_cost: Decimal
    postage_paid: Decimal
    incomplete_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Why the figures are less than certain: a cost line not recorded, a "
            "stale exchange rate, or no fee rule in force on the date (T231, T236)"
        ),
    )
    fees: list[FeeChargeResponse] = Field(
        default_factory=list, description="The stack as charged at the price returned"
    )

    inputs: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Every figure the answer was computed from, rendered as strings so "
            "no monetary value crosses the wire as a JSON number (FR-034)"
        ),
    )
    passes: int = Field(0, description="Closed-form solves it took; one when no clamp bound")

    is_proposal: bool = Field(
        True,
        description=(
            "Always true, and present so a client cannot mistake this for a "
            "published price: applying it is a separate write (US4 scenario 5)"
        ),
    )
