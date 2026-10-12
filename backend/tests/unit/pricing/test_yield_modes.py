"""What a yield figure means under each failure mode (research.md D3).

The stored yield is always a **per-part** success probability. The mode decides
how one part's failure propagates:

* ``per_part`` -- only that part is lost, so the at-risk portion is divided by
  ``y``.
* ``per_plate`` -- one failure condemns the plate, so plate survival is
  ``y**N`` for ``N`` prints per plate and the divisor is that.

Both reduce to ``y`` at one print per plate, which is why the spec asserts the
two modes agree there (edge case, SC-002b) and that per-plate is heavier once
batched. The naive reading -- dividing a plate's at-risk cost by a plate-level
yield -- is algebraically identical to the per-part formula, so it would have
produced two modes that always agree and a criterion that could never pass.
"""

from decimal import Decimal

import pytest

from app.services.costing import CostingService
from tests.fixtures import golden_case as golden
from tests.unit.pricing.conftest import make_model, make_policy, make_printer

CENT = Decimal("0.01")


def cost_of(**overrides) -> Decimal:
    model = make_model(**overrides)
    return CostingService.item_breakdown(
        model, policy=make_policy(), printer=make_printer()
    ).total_make_cost


def breakdown_of(**overrides):
    model = make_model(**overrides)
    return CostingService.item_breakdown(model, policy=make_policy(), printer=make_printer())


class TestAPerfectYieldIsANoOp:
    """Spec edge case: a yield of 100% must not change cost, under either mode."""

    @pytest.mark.parametrize("mode", ["per_part", "per_plate"])
    def test_no_premium_at_a_yield_of_one(self, mode: str) -> None:
        breakdown = breakdown_of(expected_yield=Decimal("1.0"), failure_mode=mode)
        assert breakdown.failure_premium == Decimal("0")
        assert breakdown.yield_applied == Decimal("1.0")

    @pytest.mark.parametrize("mode", ["per_part", "per_plate"])
    def test_the_total_is_exactly_the_two_subtotals(self, mode: str) -> None:
        breakdown = breakdown_of(expected_yield=Decimal("1.0"), failure_mode=mode)
        assert breakdown.total_make_cost == (
            breakdown.at_risk_subtotal + breakdown.not_at_risk_subtotal
        )

    @pytest.mark.parametrize("per_plate", [1, 4, 20])
    def test_a_perfect_yield_is_a_no_op_however_the_plate_is_batched(self, per_plate: int) -> None:
        """Under per-plate, ``1 ** N`` is 1 for every N, which must hold here too."""
        batched = breakdown_of(
            expected_yield=Decimal("1.0"),
            failure_mode="per_plate",
            prints_per_plate=per_plate,
        )
        assert batched.failure_premium == Decimal("0")


class TestTheTwoModesAgreeOnASinglePartPlate:
    """The boundary case that proves the formulas consistent (spec edge case)."""

    def test_the_modes_report_the_same_cost_at_one_print_per_plate(self) -> None:
        per_part = cost_of(failure_mode="per_part", prints_per_plate=1)
        per_plate = cost_of(failure_mode="per_plate", prints_per_plate=1)
        assert per_part == per_plate

    def test_the_premiums_are_identical_too(self) -> None:
        """Equal totals could hide two offsetting errors; the premiums must match."""
        per_part = breakdown_of(failure_mode="per_part", prints_per_plate=1)
        per_plate = breakdown_of(failure_mode="per_plate", prints_per_plate=1)
        assert per_part.failure_premium == per_plate.failure_premium
        assert per_part.at_risk_subtotal == per_plate.at_risk_subtotal

    def test_the_divisor_is_the_yield_itself_at_one_per_plate(self) -> None:
        breakdown = breakdown_of(failure_mode="per_plate", prints_per_plate=1)
        at_risk = breakdown.at_risk_subtotal
        assert breakdown.failure_premium == (at_risk / golden.EXPECTED_YIELD - at_risk).quantize(
            CENT
        )


class TestPerPlateIsHeavierOnceBatched:
    """SC-002b: the same yield figure costs more when a failure takes the plate."""

    @pytest.mark.parametrize("per_plate", [2, 4, 8, 20])
    def test_per_plate_is_strictly_higher_above_one_per_plate(self, per_plate: int) -> None:
        per_part = cost_of(failure_mode="per_part", prints_per_plate=per_plate)
        per_plate_cost = cost_of(failure_mode="per_plate", prints_per_plate=per_plate)
        assert per_plate_cost > per_part, (
            f"at {per_plate} per plate, per-plate reported {per_plate_cost} which is "
            f"not above per-part's {per_part}; the divisor is not y**N"
        )

    def test_the_divisor_is_the_yield_raised_to_the_plate_count(self) -> None:
        per_plate = 4
        breakdown = breakdown_of(failure_mode="per_plate", prints_per_plate=per_plate)
        at_risk = breakdown.at_risk_subtotal
        divisor = golden.EXPECTED_YIELD**per_plate
        assert breakdown.failure_premium == (at_risk / divisor - at_risk).quantize(CENT)

    def test_the_premium_grows_with_how_many_parts_the_plate_carries(self) -> None:
        """FR-015c: the premium must scale with the plate's output."""
        previous = None
        for per_plate in (1, 2, 4, 8, 16):
            breakdown = breakdown_of(failure_mode="per_plate", prints_per_plate=per_plate)
            # Expressed as a share of the at-risk cost, so the comparison is not
            # confounded by per-part costs falling as the plate fills.
            share = breakdown.failure_premium / breakdown.at_risk_subtotal
            if previous is not None:
                assert share > previous, (
                    f"the per-plate premium share did not grow at {per_plate} per plate"
                )
            previous = share

    def test_batching_still_lowers_the_per_part_cost_under_per_part_mode(self) -> None:
        """A sanity check on the fixture: more per plate is cheaper per part."""
        previous = None
        for per_plate in (1, 2, 4, 8):
            total = cost_of(failure_mode="per_part", prints_per_plate=per_plate)
            if previous is not None:
                assert total < previous
            previous = total


class TestAnImpossibleYieldIsReportedNotComputed:
    """A yield of zero is a configuration error, not an infinite cost."""

    @pytest.mark.parametrize("bad_yield", ["0", "-0.5"])
    def test_a_zero_or_negative_yield_is_reported(self, bad_yield: str) -> None:
        breakdown = breakdown_of(expected_yield=Decimal(bad_yield))
        assert breakdown.failure_premium == Decimal("0")
        assert any("yield" in reason for reason in breakdown.incomplete_reasons)

    def test_a_yield_above_one_is_reported(self) -> None:
        breakdown = breakdown_of(expected_yield=Decimal("1.5"))
        assert breakdown.failure_premium == Decimal("0")
        assert any("yield" in reason for reason in breakdown.incomplete_reasons)


class TestTheModeIsNamedAlongsideTheFigure:
    """FR-015e: the same yield means different things under each mode."""

    @pytest.mark.parametrize("mode", ["per_part", "per_plate"])
    def test_the_breakdown_names_the_mode_that_produced_its_premium(self, mode: str) -> None:
        assert breakdown_of(failure_mode=mode).failure_mode == mode

    def test_an_unknown_mode_falls_back_to_the_default_rather_than_guessing(self) -> None:
        """Per-part is the default (FR-015a); an unrecognised value is not a third mode."""
        assert breakdown_of(failure_mode="per_sausage").failure_mode == "per_part"
