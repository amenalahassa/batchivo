"""A missing input is reported as missing, never costed as zero (FR-019).

This is the quietest failure a costing engine can have. A zero reads exactly
like a real figure: a printer with no cost policy makes a 40-hour print look
free, and the queue gets ordered backwards by a number nobody doubted. So the
engine reports what was missing and the operator sees an incomplete cost rather
than a confident wrong one.

The two cases the task names -- a printer with no cost policy, and an item with
no print time -- are the two the spec's edge cases name too. Each is asserted
three ways: the line is absent rather than zero, the reason is reported, and
the rest of the cost is still computed, because an incomplete cost is more
useful than no cost at all.
"""

from decimal import Decimal

import pytest

from app.services.costing import CostingService
from app.services.pricing_policy import CostPolicy
from tests.unit.pricing.conftest import make_model, make_policy, make_printer


def breakdown_for(model=None, *, policy=None, printer="default"):
    return CostingService.item_breakdown(
        model if model is not None else make_model(),
        policy=policy if policy is not None else make_policy(),
        printer=make_printer() if printer == "default" else printer,
    )


def keys(breakdown) -> set[str]:
    return {line.key for line in breakdown.lines}


class TestAPrinterWithNoCostPolicy:
    """FR-011 and FR-019: no machine rate means no machine line."""

    @pytest.fixture
    def bare_printer(self):
        return make_printer(
            purchase_price=None,
            expected_lifetime_hours=None,
            maintenance_reserve_total=None,
            measured_watts=None,
            electricity_rate_per_kwh=None,
        )

    def test_no_machine_line_is_produced(self, bare_printer) -> None:
        assert "machine" not in keys(breakdown_for(printer=bare_printer))

    def test_the_missing_policy_is_reported_by_name(self, bare_printer) -> None:
        reasons = breakdown_for(printer=bare_printer).incomplete_reasons
        assert any("machine cost policy" in reason for reason in reasons)
        assert any(bare_printer.name in reason for reason in reasons)

    def test_the_machine_cost_is_not_quietly_zero(self, bare_printer) -> None:
        """The distinction that matters: absent and flagged, not present at zero."""
        breakdown = breakdown_for(printer=bare_printer)
        assert not any(
            line.key == "machine" and line.amount == Decimal("0") for line in breakdown.lines
        )
        assert breakdown.incomplete_reasons

    def test_the_rest_of_the_cost_is_still_computed(self, bare_printer) -> None:
        breakdown = breakdown_for(printer=bare_printer)
        assert {"material", "waste", "labor_handling"} <= keys(breakdown)
        assert breakdown.total_make_cost > Decimal("0")

    def test_a_partial_policy_is_reported_as_partial(self) -> None:
        """A machine with a price but no measured draw is costed, and said to be partial."""
        printer = make_printer(measured_watts=None, electricity_rate_per_kwh=None)
        breakdown = breakdown_for(printer=printer)
        assert "machine" in keys(breakdown)
        assert any("partial machine cost policy" in r for r in breakdown.incomplete_reasons)
        assert any("measured_watts" in r for r in breakdown.incomplete_reasons)

    def test_the_tenant_electricity_rate_completes_a_printer_that_has_none(self) -> None:
        """FR-011: the printer's own rate wins, and the policy's fills the gap."""
        printer = make_printer(electricity_rate_per_kwh=None)
        breakdown = breakdown_for(printer=printer)
        assert "machine" in keys(breakdown)
        assert not any("electricity" in r for r in breakdown.incomplete_reasons)

    def test_no_printer_and_no_default_rate_is_reported(self) -> None:
        breakdown = breakdown_for(printer=None)
        assert "machine" not in keys(breakdown)
        assert any("no machine rate is available" in r for r in breakdown.incomplete_reasons)

    def test_the_policy_default_rate_is_used_when_no_printer_is_assigned(self) -> None:
        """FR-011: fall back to a default rate, not to nothing."""
        policy = make_policy(default_machine_rate_per_hour=Decimal("0.25"))
        breakdown = breakdown_for(policy=policy, printer=None)
        assert "machine" in keys(breakdown)
        assert not any("no machine rate" in r for r in breakdown.incomplete_reasons)


class TestAnItemWithNoPrintTime:
    """Spec edge case: zero-hour or missing print time."""

    @pytest.mark.parametrize("minutes", [None, 0])
    def test_neither_machine_nor_hourly_overhead_is_charged(self, minutes) -> None:
        breakdown = breakdown_for(make_model(print_time_minutes=minutes))
        assert "machine" not in keys(breakdown)
        assert "overhead" not in keys(breakdown)

    @pytest.mark.parametrize("minutes", [None, 0])
    def test_the_item_is_flagged_as_incompletely_costed(self, minutes) -> None:
        reasons = breakdown_for(make_model(print_time_minutes=minutes)).incomplete_reasons
        assert any("no print time" in reason for reason in reasons)

    def test_the_material_and_labor_are_still_costed(self) -> None:
        breakdown = breakdown_for(make_model(print_time_minutes=None))
        assert {"material", "labor_handling", "labor_packing"} <= keys(breakdown)
        assert breakdown.total_make_cost > Decimal("0")

    def test_the_failure_premium_still_applies_to_what_is_known(self) -> None:
        """An incomplete cost is still a cost; the yield is not suspended."""
        breakdown = breakdown_for(make_model(print_time_minutes=None))
        assert breakdown.failure_premium > Decimal("0")


class TestOverheadThatCannotBeAbsorbed:
    """Spec edge case: expected capacity of zero, and a pool nobody declared."""

    def test_a_policy_with_no_pool_reports_rather_than_charging_nothing(self) -> None:
        policy = CostPolicy(
            print_labor_rate=Decimal("25"),
            finishing_labor_rate=Decimal("25"),
            overhead_method="per_machine_hour",
            overhead_monthly_pool=None,
            expected_monthly_machine_hours=Decimal("600"),
        )
        breakdown = breakdown_for(policy=policy)
        assert "overhead" not in keys(breakdown)
        assert any("no pool and capacity" in r for r in breakdown.incomplete_reasons)

    def test_zero_capacity_is_not_divided_by(self) -> None:
        policy = CostPolicy(
            print_labor_rate=Decimal("25"),
            finishing_labor_rate=Decimal("25"),
            overhead_method="per_machine_hour",
            overhead_monthly_pool=Decimal("180"),
            expected_monthly_machine_hours=Decimal("0"),
        )
        breakdown = breakdown_for(policy=policy)
        assert policy.overhead_rate_per_machine_hour is None
        assert "overhead" not in keys(breakdown)
        assert breakdown.incomplete_reasons

    def test_the_percentage_method_remains_available(self) -> None:
        """FR-014: an option, not a removal."""
        policy = CostPolicy(
            print_labor_rate=Decimal("25"),
            finishing_labor_rate=Decimal("25"),
            overhead_method="percentage",
            overhead_percentage=Decimal("10"),
        )
        breakdown = breakdown_for(policy=policy)
        assert "overhead" in keys(breakdown)
        assert not any("overhead" in r for r in breakdown.incomplete_reasons)


class TestWasteWithNoPerGramCost:
    def test_recorded_purge_with_an_empty_bill_of_materials_is_reported(self) -> None:
        model = make_model()
        model.materials = []
        breakdown = breakdown_for(model)
        assert "waste" not in keys(breakdown)
        assert any("per-gram cost" in r for r in breakdown.incomplete_reasons)


class TestReasonsAreUsefulToRead:
    def test_each_reason_is_reported_once(self) -> None:
        """A breakdown repeating one reason five times is noise, not information."""
        model = make_model(print_time_minutes=None)
        reasons = breakdown_for(model, printer=None).incomplete_reasons
        assert len(reasons) == len(set(reasons))

    def test_a_complete_item_reports_nothing(self) -> None:
        assert breakdown_for().incomplete_reasons == []

    def test_reasons_name_the_requirement_or_the_field(self) -> None:
        """A reason an operator cannot act on is not worth reporting."""
        model = make_model(print_time_minutes=None)
        for reason in breakdown_for(model, printer=None).incomplete_reasons:
            assert len(reason) > 20, f"{reason!r} is too terse to act on"
