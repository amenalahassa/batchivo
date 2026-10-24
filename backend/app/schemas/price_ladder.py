"""Margin across a range of prices, for the operator to choose from (FR-007).

No rung is marked as recommended, and there is deliberately no field in which
one could be: what a customer will pay is not derivable from any data this
system holds, so the choice stays with the person who knows the market.

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

from app.schemas.pricing_literals import MarginBasis


class PriceLadderRungResponse(BaseModel):
    """One price point and what it earns (FR-007).

    No rung is marked as recommended, and there is deliberately no field in
    which one could be: what a customer will pay is not derivable from any data
    this system holds, so the choice stays with the operator.
    """

    price: Decimal
    margin_pct: Optional[Decimal] = Field(
        None, description="Null where fees consume the whole basis, never zero"
    )
    profit: Decimal
    margin_basis: MarginBasis
    profit_per_machine_hour: Optional[Decimal] = Field(
        None, description="Null when the print time is unknown, never zero"
    )

    model_config = ConfigDict(from_attributes=True)


class PriceLadderResponse(BaseModel):
    """Margin across a range of prices, for the operator to choose from.

    The bounds are echoed back because they were the caller's: the ladder has
    no range of its own, since a default range's midpoint would function as a
    recommended price while resting on nothing (FR-007).
    """

    product_id: UUID
    sales_channel_id: UUID
    as_of: date

    price_from: Decimal
    price_to: Decimal
    step: Decimal

    margin_basis: MarginBasis
    margin_basis_label: str
    make_cost: Decimal
    postage_paid: Decimal
    incomplete_reasons: list[str] = Field(
        default_factory=list,
        description=(
            "Why the figures are less than certain: a cost line not recorded, a "
            "stale exchange rate, or no fee rule in force on the date (T231, T236)"
        ),
    )
    machine_hours: Optional[Decimal] = Field(
        None, description="Machine occupancy per unit; null when nobody has timed the print"
    )

    rungs: list[PriceLadderRungResponse]
