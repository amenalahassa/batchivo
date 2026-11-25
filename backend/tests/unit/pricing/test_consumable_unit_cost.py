"""A consumable's unit cost is derived from its purchases on read (task T273).

The quotient `total_cost / quantity_purchased` used to be stored at four places
on the consumable and multiplied back up on every packaging line -- three boxes
for 10.00 packed as 9.9999 -- and it outlived the purchase it came from.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.costing import consumable_unit_cost

CENT = Decimal("0.01")


def _purchase(total: str, quantity: int, on: date, created: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        total_cost=Decimal(total),
        quantity_purchased=quantity,
        purchase_date=on,
        created_at=datetime(2026, 1, 1, 0, 0, created, tzinfo=timezone.utc),
    )


def _consumable(typed: str | None, *purchases: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        current_cost_per_unit=Decimal(typed) if typed is not None else None,
        purchases=list(purchases),
    )


class TestTheUnitCostComesFromThePurchase:
    def test_the_quotient_is_not_rounded_before_it_is_multiplied(self) -> None:
        # Seven for 1.00, valued over a thousand units: rounded once at the edge
        # that is 142.86; the stored four-place 0.1429 made it 142.90.
        unit = consumable_unit_cost(_consumable(None, _purchase("1.00", 7, date(2026, 5, 1))))
        assert (unit * 1000).quantize(CENT) == Decimal("142.86")

    def test_three_for_ten_packs_three_at_ten(self) -> None:
        unit = consumable_unit_cost(_consumable("9.99", _purchase("10.00", 3, date(2026, 5, 1))))
        assert (unit * 3).quantize(CENT) == Decimal("10.00")

    def test_the_latest_purchase_prices_the_unit(self) -> None:
        unit = consumable_unit_cost(
            _consumable(
                None,
                _purchase("10.00", 10, date(2026, 6, 1)),
                _purchase("12.00", 10, date(2026, 3, 1)),
            )
        )
        assert unit == Decimal("1")

    def test_two_purchases_the_same_day_take_the_later_recorded(self) -> None:
        unit = consumable_unit_cost(
            _consumable(
                None,
                _purchase("10.00", 10, date(2026, 6, 1), created=1),
                _purchase("20.00", 10, date(2026, 6, 1), created=2),
            )
        )
        assert unit == Decimal("2")

    def test_a_purchase_of_nothing_prices_nothing(self) -> None:
        unit = consumable_unit_cost(_consumable("0.50", _purchase("10.00", 0, date(2026, 6, 1))))
        assert unit == Decimal("0.50")


class TestWithoutAPurchaseTheTypedFigureStands:
    def test_the_operators_figure_is_used(self) -> None:
        assert consumable_unit_cost(_consumable("0.4500")) == Decimal("0.4500")

    def test_no_figure_at_all_is_zero(self) -> None:
        assert consumable_unit_cost(_consumable(None)) == Decimal("0")


class TestThePackagingLineIsDatedByItsPurchase:
    """Task T277: a deleted purchase's date does not outlive it on the line."""

    def test_the_line_takes_the_date_of_the_purchase_that_prices_it(self) -> None:
        from app.services.costing import _packaging_cost

        consumable = _consumable(
            "0.50",
            _purchase("10.00", 10, date(2026, 6, 1)),
            _purchase("12.00", 10, date(2026, 3, 1)),
        )
        consumable.id = None
        product = SimpleNamespace(id=None, packaging_consumable=consumable, packaging_quantity=2)

        amount, origin = _packaging_cost(product, None)

        assert amount == Decimal("2")
        assert origin.as_of == date(2026, 6, 1)

    def test_without_a_purchase_the_typed_figures_origin_stands(self) -> None:
        from app.services.costing import _packaging_cost

        consumable = _consumable("0.50")
        consumable.id = None
        product = SimpleNamespace(id=None, packaging_consumable=consumable, packaging_quantity=2)

        amount, origin = _packaging_cost(product, None)

        assert amount == Decimal("1.00")
        assert origin.as_of is None
