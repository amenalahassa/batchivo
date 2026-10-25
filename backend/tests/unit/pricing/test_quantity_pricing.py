"""A quantity is priced as a whole line on the margin, the solver and the ladder (T258).

The defect: the context carried one unit's price and one unit's make-cost but
``quantity=3``, so a per-unit fee was charged three times against one unit's
revenue. Every tiered margin and every solved tier price was wrong.
"""

from datetime import date
from decimal import Decimal

from app.services import pricing_solver
from tests.unit.pricing.conftest import make_channel, make_fee_rule, make_policy

AS_OF = date(2026, 6, 1)
ZERO = Decimal("0")


def _channel():
    return make_channel(
        expected_discount_pct=ZERO,
        expected_refund_pct=ZERO,
        fee_rules=[
            make_fee_rule("Per unit", "per_unit_sold", fixed_amount=Decimal("0.50")),
            make_fee_rule("Per order", "per_order", fixed_amount=Decimal("1.00")),
        ],
    )


def _margin(price: str, quantity: int):
    return pricing_solver.margin_at(
        Decimal(price),
        channel=_channel(),
        make_cost=Decimal("4.00"),
        as_of=AS_OF,
        quantity=quantity,
        policy=make_policy(),
        margin_basis="item_price",
    )


class TestTheMarginIsTheLines:
    def test_quantity_one(self) -> None:
        result = _margin("10.00", 1)
        # 10.00 - 4.00 - 0.50 - 1.00
        assert result.profit == Decimal("4.50")

    def test_quantity_three_charges_each_unit_once_against_each_units_revenue(self) -> None:
        result = _margin("10.00", 3)
        # 30.00 - 12.00 - 3 x 0.50 - 1.00: the per-order fee once, per-unit thrice.
        assert result.profit == Decimal("15.50")
        assert result.margin_pct is not None
        assert result.margin_pct > _margin("10.00", 1).margin_pct, (
            "a per-order fee spread over three units must leave a better margin"
        )


class TestTheSolverAgreesWithTheMargin:
    def test_the_solved_tier_price_earns_its_target_at_that_quantity(self) -> None:
        solved = pricing_solver.solve(
            channel=_channel(),
            make_cost=Decimal("4.00"),
            target_margin_pct=Decimal("40"),
            as_of=AS_OF,
            quantity=3,
            policy=make_policy(),
            margin_basis="item_price",
            rounding_rule="none",
        )
        assert solved.achievable
        # Line: 0.6 P_line = 12.00 + 1.50 + 1.00, so P_line = 24.1666..., a unit 8.0555...
        assert solved.raw_price.quantize(Decimal("0.01")) == Decimal("8.06")
        at_price = _margin(str(solved.raw_price), 3)
        assert abs(at_price.margin_pct - Decimal("40")) < Decimal("0.01")


class TestTheLadderIsPerUnitPriceAtTheQuantity:
    def test_each_rung_is_the_margin_endpoint_at_that_price_and_quantity(self) -> None:
        rungs = pricing_solver.ladder(
            channel=_channel(),
            make_cost=Decimal("4.00"),
            start=Decimal("10.00"),
            stop=Decimal("10.00"),
            step=Decimal("1.00"),
            as_of=AS_OF,
            quantity=3,
            policy=make_policy(),
            margin_basis="item_price",
        )
        assert rungs[0].profit == _margin("10.00", 3).profit
