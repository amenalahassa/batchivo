"""`record_actual_unit_costs` — a realised cost, derived in the service (task T164).

Recording what a run actually consumed is one of the two deliberate
exceptions to "nothing derived is stored": it is evidence, not a figure the
engine can re-derive once a spool price moves. Deriving it in a route handler
was not an exception — Constitution III puts business logic in a service and
keeps route handlers thin.

The arithmetic matters as much as its home. The waste is distributed across
the *successful* units, because a plate that failed half its parts put its
filament into the parts that survived (FR-040).
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.production_run import ProductionRunService

ZERO = Decimal("0")


def _service() -> ProductionRunService:
    return ProductionRunService(db=None, tenant=None, user=None)  # type: ignore[arg-type]


def _run(*, items=None, plates=None, multi_plate=False) -> SimpleNamespace:
    return SimpleNamespace(
        is_multi_plate=multi_plate,
        plates=plates or [],
        items=items or [],
        cost_per_gram_actual=None,
        successful_weight_grams=None,
    )


def _unit(weight: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        model_weight_grams=Decimal(weight) if weight is not None else None,
        actual_cost_per_unit=None,
    )


class TestItemRuns:
    def test_each_unit_carries_its_share_of_what_was_consumed(self):
        items = [_unit("100"), _unit("50")]
        run = _run(items=items)

        _service().record_actual_unit_costs(
            run,
            total_material_cost=Decimal("4.50"),
            successful_weight=Decimal("150"),
        )

        assert run.successful_weight_grams == Decimal("150")
        assert run.cost_per_gram_actual == Decimal("0.03")
        assert items[0].actual_cost_per_unit == Decimal("3.00")
        assert items[1].actual_cost_per_unit == Decimal("1.50")

    def test_waste_lands_on_the_parts_that_survived(self):
        """200 g bought, 150 g of good parts: the good parts carry the 200."""
        items = [_unit("150")]
        run = _run(items=items)

        _service().record_actual_unit_costs(
            run,
            total_material_cost=Decimal("6.00"),  # 200 g at 0.03
            successful_weight=Decimal("150"),
        )

        assert items[0].actual_cost_per_unit == Decimal("6.00"), (
            "costing a surviving part at the per-gram price of a perfect run "
            "would understate what it cost"
        )

    def test_a_unit_with_no_recorded_weight_is_left_alone(self):
        items = [_unit("100"), _unit(None)]
        run = _run(items=items)

        _service().record_actual_unit_costs(
            run,
            total_material_cost=Decimal("3.00"),
            successful_weight=Decimal("100"),
        )

        assert items[0].actual_cost_per_unit == Decimal("3.00")
        assert items[1].actual_cost_per_unit is None


class TestPlateRuns:
    def test_plates_are_costed_when_the_run_is_multi_plate(self):
        plates = [_unit("80"), _unit("120")]
        run = _run(plates=plates, multi_plate=True)

        _service().record_actual_unit_costs(
            run,
            total_material_cost=Decimal("10.00"),
            successful_weight=Decimal("200"),
        )

        assert run.cost_per_gram_actual == Decimal("0.05")
        assert plates[0].actual_cost_per_unit == Decimal("4.00")
        assert plates[1].actual_cost_per_unit == Decimal("6.00")


class TestNothingSucceeded:
    def test_no_successful_weight_writes_nothing(self):
        """FR-019: a figure written as zero would read as a free run."""
        items = [_unit("100")]
        run = _run(items=items)

        _service().record_actual_unit_costs(
            run,
            total_material_cost=Decimal("3.00"),
            successful_weight=ZERO,
        )

        assert run.cost_per_gram_actual is None
        assert run.successful_weight_grams is None
        assert items[0].actual_cost_per_unit is None


class TestExactness:
    def test_the_per_gram_quotient_is_carried_unrounded_into_each_unit(self):
        """Constitution IV: round once, at the edge, never between steps.

        A third of a penny per gram over a 300 g part is a penny: rounding the
        quotient first and multiplying would lose it.
        """
        items = [_unit("300")]
        run = _run(items=items)

        _service().record_actual_unit_costs(
            run,
            total_material_cost=Decimal("1.00"),
            successful_weight=Decimal("300"),
        )

        assert items[0].actual_cost_per_unit == Decimal("1.00")
        assert isinstance(run.cost_per_gram_actual, Decimal)

    def test_no_figure_becomes_a_float(self):
        items = [_unit("100")]
        run = _run(items=items)

        _service().record_actual_unit_costs(
            run,
            total_material_cost=Decimal("3.33"),
            successful_weight=Decimal("100"),
        )

        assert isinstance(run.cost_per_gram_actual, Decimal)
        assert isinstance(items[0].actual_cost_per_unit, Decimal)


@pytest.mark.parametrize("weight", [Decimal("0"), Decimal("-1")])
def test_a_non_positive_weight_is_never_divided_by(weight: Decimal):
    run = _run(items=[_unit("100")])
    _service().record_actual_unit_costs(
        run, total_material_cost=Decimal("3.00"), successful_weight=weight
    )
    assert run.cost_per_gram_actual is None
