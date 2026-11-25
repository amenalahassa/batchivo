"""Which costs the failure premium reaches, and which it must never touch.

FR-015 and US2 scenario 3 draw the line: the premium is applied to material,
waste, machine, overhead and pre-packing labor, and **not** to packaging
materials or packing labor. The reason is physical -- packaging is consumed
after the part is known good, so a failed print never used any.

Finishing labor sits on the at-risk side. research.md D3 flags that as a
modelling choice rather than a physical truth (strictly, a part that failed was
never finished) and it is defensible as modelling the rework. It is also what
reproduces the golden case's CA$20.30, so it is asserted here deliberately
rather than inherited by accident.

The test works by moving the yield and watching which lines respond. A line
that changes when only the yield changes is at risk; one that does not, is not.
That is stronger than reading the ``risk_class`` field, because it tests the
arithmetic rather than the label -- though both are checked, since the label is
what the operator reads.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.model_component import ModelComponent
from app.services.costing import AT_RISK_KEYS, CostingService
from tests.unit.pricing.conftest import make_model, make_policy, make_printer, make_product

PERFECT = Decimal("1.0")
IMPERFECT = Decimal("0.80")


def _product_breakdown(expected_yield: Decimal):
    """The golden product, so packaging materials are in scope alongside packing."""
    model = make_model(
        expected_yield=expected_yield,
        # Put time on every labor component, so none of them is silently absent
        # from the comparison below.
        labor_hours_per_plate=Decimal("0.2"),
        labor_hours_per_item=Decimal("0.25"),
        finishing_hours_per_item=Decimal("0.1"),
        packing_hours_per_item=Decimal("0.0833"),
    )
    model.components = [
        ModelComponent(
            id=uuid4(),
            model_id=model.id,
            component_name="Magnet",
            quantity=Decimal("2"),
            unit_cost=Decimal("0.75"),
        )
    ]
    return CostingService.product_breakdown(
        make_product(model),
        policy=make_policy(),
        printer_for_model={model.id: make_printer()},
    )


@pytest.fixture
def perfect():
    return _product_breakdown(PERFECT)


@pytest.fixture
def imperfect():
    return _product_breakdown(IMPERFECT)


def _amounts(breakdown) -> dict[str, Decimal]:
    return {line.key: line.amount for line in breakdown.lines}


class TestThePremiumReachesTheWorkAtRisk:
    """US2 scenario 3, line by line."""

    @pytest.mark.parametrize(
        "key",
        ["material", "waste", "machine", "overhead", "labor_handling", "labor_finishing"],
    )
    def test_the_line_is_labelled_at_risk(self, key: str, imperfect) -> None:
        line = next(line for line in imperfect.lines if line.key == key)
        assert line.risk_class == "at_risk", f"{key} is not labelled as exposed to failure"

    @pytest.mark.parametrize(
        "key",
        ["material", "waste", "machine", "overhead", "labor_handling", "labor_finishing"],
    )
    def test_the_line_is_inside_the_at_risk_subtotal(self, key: str, imperfect) -> None:
        amounts = _amounts(imperfect)
        at_risk_lines = sum(
            (line.amount for line in imperfect.lines if line.risk_class == "at_risk"),
            Decimal("0"),
        )
        assert amounts[key] <= at_risk_lines
        assert imperfect.at_risk_subtotal == at_risk_lines

    def test_the_premium_is_exactly_what_the_yield_implies_of_that_subtotal(
        self, imperfect
    ) -> None:
        at_risk = imperfect.at_risk_subtotal
        expected = (at_risk / IMPERFECT - at_risk).quantize(Decimal("0.01"))
        assert imperfect.failure_premium == expected


class TestThePremiumNeverReachesWorkOnAGoodPart:
    """FR-015: packaging materials and packing labor carry no premium."""

    @pytest.mark.parametrize("key", ["packaging", "labor_packing"])
    def test_the_line_is_labelled_not_at_risk(self, key: str, imperfect) -> None:
        line = next(line for line in imperfect.lines if line.key == key)
        assert line.risk_class == "not_at_risk"

    @pytest.mark.parametrize("key", ["packaging", "labor_packing"])
    def test_the_line_does_not_move_when_the_yield_falls(
        self, key: str, perfect, imperfect
    ) -> None:
        assert _amounts(perfect)[key] == _amounts(imperfect)[key], (
            f"{key} changed when only the yield changed, so the premium is "
            f"reaching work done on a part already known good (FR-015)"
        )

    def test_the_not_at_risk_subtotal_is_identical_at_both_yields(self, perfect, imperfect) -> None:
        assert perfect.not_at_risk_subtotal == imperfect.not_at_risk_subtotal

    def test_the_whole_difference_between_the_two_is_the_premium(self, perfect, imperfect) -> None:
        """Nothing else may move: a premium that leaks into a line is invisible."""
        assert perfect.at_risk_subtotal == imperfect.at_risk_subtotal
        assert imperfect.total_make_cost - perfect.total_make_cost == imperfect.failure_premium


class TestTheRiskClassificationIsExhaustive:
    def test_every_line_is_classified_one_way_or_the_other(self, imperfect) -> None:
        for line in imperfect.lines:
            assert line.risk_class in ("at_risk", "not_at_risk")

    def test_the_subtotals_account_for_every_line(self, imperfect) -> None:
        total_lines = sum((line.amount for line in imperfect.lines), Decimal("0"))
        assert imperfect.at_risk_subtotal + imperfect.not_at_risk_subtotal == total_lines

    def test_the_at_risk_key_set_matches_what_the_lines_report(self, imperfect) -> None:
        """The engine's one source of truth for the split, and the lines, agree."""
        for line in imperfect.lines:
            expected = "at_risk" if line.key in AT_RISK_KEYS else "not_at_risk"
            assert line.risk_class == expected

    def test_packaging_and_packing_are_not_in_the_at_risk_set(self) -> None:
        assert "packaging" not in AT_RISK_KEYS
        assert "labor_packing" not in AT_RISK_KEYS

    def test_finishing_is_in_the_at_risk_set_deliberately(self) -> None:
        """Documents research.md D3's flagged modelling choice, so it stays visible."""
        assert "labor_finishing" in AT_RISK_KEYS


class TestPerPlateLaborIsDividedAndPerItemLaborIsNot:
    """US2 scenario 4: a plate of 20 and a plate of 1."""

    def _handling(self, prints_per_plate: int) -> Decimal:
        model = make_model(
            prints_per_plate=prints_per_plate,
            labor_hours_per_plate=Decimal("0.5"),
            labor_hours_per_item=Decimal("0.1"),
            expected_yield=PERFECT,
        )
        breakdown = CostingService.item_breakdown(
            model, policy=make_policy(), printer=make_printer()
        )
        return next(line.amount for line in breakdown.lines if line.key == "labor_handling")

    def test_per_plate_preparation_is_divided_across_the_plates_output(self) -> None:
        one = self._handling(1)
        twenty = self._handling(20)
        assert twenty < one, "per-plate preparation was not divided across the plate"

    def test_per_item_labor_survives_the_division(self) -> None:
        """At 20 per plate the per-item component must still be charged in full."""
        rate = make_policy().print_labor_rate
        twenty = self._handling(20)
        per_item_only = Decimal("0.1") * rate
        expected = (Decimal("0.5") / Decimal("20") + Decimal("0.1")) * rate
        assert twenty == expected.quantize(Decimal("0.01"))
        assert twenty > per_item_only
