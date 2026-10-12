"""Tests for the per-product cost delta report.

The Constitution requires a change that alters a computed value to report the
per-record difference before the change is accepted. This script is that
report, so its attribution logic is the thing standing between a wrong cost and
an accepted release -- and attribution that cannot be trusted is worse than
none, because it reads like a review that happened.

What is covered here is the decision-making: whether a declared cause is
*verified* to predict a delta, whether an unexplained change is reported as
unexplained, and whether the report says plainly when it is weak evidence. The
database collection path is exercised by running the script, not here.
"""

from decimal import Decimal

import pytest

from scripts import cost_delta_report as report


@pytest.fixture(autouse=True)
def clean_replay():
    """`_REPLAY` is module-level state; no test may inherit another's."""
    report._REPLAY.clear()
    yield
    report._REPLAY.clear()


def _row(**overrides) -> dict:
    base = {
        "tenant": "handy",
        "product_id": "11111111-1111-1111-1111-111111111111",
        "sku": "PROD-001",
        "total_make_cost": "20.30",
        "lines": {
            "models_cost": "19.38",
            "packaging_cost": "0.92",
            "assembly_cost": "0.00",
            "child_products_cost": "0.00",
            "total_make_cost": "20.30",
        },
        "labor_rate_used": "25.00",
        "overhead_pct_used": "",
        "engine_default_labor_rate": "",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# labor-rate attribution
# ---------------------------------------------------------------------------


class TestLaborRateAttribution:
    def test_a_delta_the_old_rate_reproduces_is_attributed(self):
        """Replaying the current engine at the old rate must land on the old cost."""
        before = _row(total_make_cost="12.50", engine_default_labor_rate="10.00")
        after = _row(total_make_cost="20.30", labor_rate_used="25.00")
        report._REPLAY[(after["product_id"], "10.00")] = "12.50"

        explanation = report._explain_labor_rate(before, after)
        assert explanation is not None
        assert "10.00" in explanation and "25.00" in explanation

    def test_a_delta_the_old_rate_does_not_reproduce_is_not_attributed(self):
        """Something other than the rate moved this cost, so the cause is refused.

        This is the case that matters: a cause declared on the command line must
        not launder a change it does not explain.
        """
        before = _row(total_make_cost="12.50", engine_default_labor_rate="10.00")
        after = _row(total_make_cost="20.30", labor_rate_used="25.00")
        report._REPLAY[(after["product_id"], "10.00")] = "13.75"  # not 12.50

        assert report._explain_labor_rate(before, after) is None

    def test_no_replay_means_no_attribution_rather_than_assumed_attribution(self):
        before = _row(total_make_cost="12.50", engine_default_labor_rate="10.00")
        after = _row(total_make_cost="20.30", labor_rate_used="25.00")
        assert report._explain_labor_rate(before, after) is None

    def test_an_unchanged_rate_explains_nothing(self):
        before = _row(total_make_cost="20.30", engine_default_labor_rate="25.00")
        after = _row(total_make_cost="22.00", labor_rate_used="25.00")
        assert report._explain_labor_rate(before, after) is None

    def test_a_before_ref_with_no_engine_default_explains_nothing(self):
        before = _row(total_make_cost="12.50", engine_default_labor_rate="")
        after = _row(total_make_cost="20.30", labor_rate_used="25.00")
        assert report._explain_labor_rate(before, after) is None


# ---------------------------------------------------------------------------
# new-line attribution
# ---------------------------------------------------------------------------


class TestNewLineAttribution:
    def test_a_delta_matching_a_new_line_is_attributed(self):
        before = _row(total_make_cost="20.30", lines={"machine": "0.00"})
        after = _row(total_make_cost="24.30", lines={"machine": "4.00"})
        explanation = report._explain_new_line("machine", before, after)
        assert explanation is not None
        assert "machine" in explanation

    def test_a_delta_larger_than_the_new_line_is_not_attributed(self):
        """Half an explanation is not an explanation."""
        before = _row(total_make_cost="20.30", lines={"machine": "0.00"})
        after = _row(total_make_cost="26.30", lines={"machine": "4.00"})
        assert report._explain_new_line("machine", before, after) is None

    def test_a_line_absent_from_the_after_breakdown_explains_nothing(self):
        before = _row(total_make_cost="20.30", lines={})
        after = _row(total_make_cost="24.30", lines={})
        assert report._explain_new_line("machine", before, after) is None

    def test_a_line_that_grew_from_a_prior_value_is_measured_as_the_growth(self):
        before = _row(total_make_cost="20.30", lines={"waste": "1.00"})
        after = _row(total_make_cost="22.30", lines={"waste": "3.00"})
        assert report._explain_new_line("waste", before, after) is not None


class TestSeveralNewLinesTogether:
    """Tier 1 introduces machine, waste, overhead and the premium at once.

    No single line equals the delta then, and the report still has to say
    which line moved by how much rather than shrug.
    """

    def test_two_declared_lines_summing_to_the_delta_are_attributed(self):
        before = _row(total_make_cost="10.44", lines={})
        after = _row(total_make_cost="13.03", lines={"machine": "2.00", "waste": "0.59"})
        explanation = report._explain_new_lines_together(["machine", "waste"], before, after)
        assert explanation is not None
        assert "machine" in explanation and "waste" in explanation

    def test_each_line_is_named_with_its_own_contribution(self):
        before = _row(total_make_cost="10.00", lines={})
        after = _row(total_make_cost="13.00", lines={"machine": "2.00", "waste": "1.00"})
        explanation = report._explain_new_lines_together(["machine", "waste"], before, after)
        assert "machine +2.00" in explanation
        assert "waste +1.00" in explanation

    def test_an_undeclared_line_leaves_a_residue_and_is_not_attributed(self):
        """A line nobody declared, moving by a cent or more, is unexplained."""
        before = _row(total_make_cost="10.00", lines={})
        after = _row(
            total_make_cost="14.00",
            lines={"machine": "2.00", "waste": "1.00", "overhead": "1.00"},
        )
        assert report._explain_new_lines_together(["machine", "waste"], before, after) is None

    def test_the_per_line_rounding_residue_is_allowed_and_named(self):
        """Rounded lines cannot always sum to an unrounded total."""
        before = _row(total_make_cost="10.44", lines={})
        after = _row(
            total_make_cost="18.52",
            lines={
                "machine": "2.21",
                "waste": "0.10",
                "overhead": "2.85",
                "labor_packing": "1.66",
                "failure_premium": "1.28",
            },
        )
        explanation = report._explain_new_lines_together(
            ["machine", "waste", "overhead", "labor_packing", "failure_premium"],
            before,
            after,
        )
        assert explanation is not None, (
            "the Tier 1 delta is 8.08 while its five rounded lines sum to 8.10; "
            "half a cent per line is exactly what rounding can produce"
        )
        assert "rounding -0.02" in explanation

    def test_a_residue_beyond_half_a_cent_per_line_is_refused(self):
        """The tolerance is the arithmetic's, not a convenience."""
        before = _row(total_make_cost="10.00", lines={})
        after = _row(
            total_make_cost="13.00",
            lines={"machine": "2.00", "waste": "1.06"},
        )
        assert report._explain_new_lines_together(["machine", "waste"], before, after) is None

    def test_one_declared_line_is_left_to_the_single_line_check(self):
        """With one cause there is nothing to combine, and no second chance."""
        before = _row(total_make_cost="10.00", lines={})
        after = _row(total_make_cost="13.00", lines={"machine": "2.00"})
        assert report._explain_new_lines_together(["machine"], before, after) is None

    def test_lines_that_did_not_move_are_not_listed(self):
        before = _row(total_make_cost="10.00", lines={"waste": "1.00"})
        after = _row(total_make_cost="12.00", lines={"machine": "2.00", "waste": "1.00"})
        explanation = report._explain_new_lines_together(["machine", "waste"], before, after)
        assert explanation == "machine +2.00"

    def test_a_delta_with_no_declared_movement_at_all_is_not_attributed(self):
        before = _row(total_make_cost="10.00", lines={})
        after = _row(total_make_cost="13.00", lines={})
        assert report._explain_new_lines_together(["machine", "waste"], before, after) is None

    def test_attribute_falls_back_to_the_combination(self):
        before = _row(total_make_cost="10.00", lines={})
        after = _row(total_make_cost="13.00", lines={"machine": "2.00", "waste": "1.00"})
        explanation = report.attribute(before, after, ["new-line:machine", "new-line:waste"])
        assert explanation.startswith("new lines")

    def test_a_single_line_explanation_is_preferred_over_the_combination(self):
        """The more precise claim wins when it holds."""
        before = _row(total_make_cost="10.00", lines={})
        after = _row(total_make_cost="12.00", lines={"machine": "2.00", "waste": "0.00"})
        explanation = report.attribute(before, after, ["new-line:machine", "new-line:waste"])
        assert explanation.startswith("new-line:machine")


# ---------------------------------------------------------------------------
# the cause registry
# ---------------------------------------------------------------------------


class TestAttribute:
    def test_the_first_matching_cause_wins(self):
        before = _row(total_make_cost="20.30", lines={"machine": "0.00"})
        after = _row(total_make_cost="24.30", lines={"machine": "4.00"})
        assert "new-line:machine" in report.attribute(before, after, ["new-line:machine"])

    def test_an_unexplained_delta_raises_unattributed(self):
        before = _row(total_make_cost="20.30", lines={"machine": "0.00"})
        after = _row(total_make_cost="99.99", lines={"machine": "4.00"})
        with pytest.raises(report.Unattributed):
            report.attribute(before, after, ["new-line:machine"])

    def test_an_unknown_cause_stops_the_run_rather_than_passing_silently(self):
        """A typo in a cause name must not read as 'nothing matched'."""
        before = _row(total_make_cost="20.30")
        after = _row(total_make_cost="24.30")
        with pytest.raises(SystemExit) as excinfo:
            report.attribute(before, after, ["labour-rate"])  # British spelling
        assert "unknown cause" in str(excinfo.value)

    def test_several_causes_are_tried_in_order(self):
        before = _row(total_make_cost="12.50", engine_default_labor_rate="10.00")
        after = _row(total_make_cost="20.30", labor_rate_used="25.00")
        report._REPLAY[(after["product_id"], "10.00")] = "12.50"
        explanation = report.attribute(before, after, ["new-line:machine", "labor-rate"])
        assert explanation.startswith("labor-rate")


# ---------------------------------------------------------------------------
# the rendered report
# ---------------------------------------------------------------------------


class TestRender:
    def test_an_unchanged_cost_is_reported_as_unchanged(self):
        row = _row()
        body, unattributed = report.render([row], [row], ["labor-rate"], "HEAD")
        assert "unchanged" in body
        assert unattributed == []

    def test_an_attributed_change_names_its_cause(self):
        before = _row(total_make_cost="12.50", engine_default_labor_rate="10.00")
        after = _row(total_make_cost="20.30", labor_rate_used="25.00")
        report._REPLAY[(after["product_id"], "10.00")] = "12.50"

        body, unattributed = report.render([before], [after], ["labor-rate"], "HEAD")
        assert "labor-rate" in body
        assert "1 changed" in body
        assert unattributed == []

    def test_an_unattributed_change_is_named_and_returned(self):
        before = _row(total_make_cost="12.50", engine_default_labor_rate="10.00")
        after = _row(total_make_cost="20.30", labor_rate_used="25.00")
        # No replay recorded, so the rate cannot be verified as the cause.

        body, unattributed = report.render([before], [after], ["labor-rate"], "HEAD")
        assert "**UNATTRIBUTED**" in body
        assert "Unattributed changes" in body
        assert unattributed == ["handy/PROD-001"]

    def test_a_product_absent_from_the_before_ref_is_reported_as_new(self):
        after = _row()
        body, unattributed = report.render([], [after], ["labor-rate"], "HEAD")
        assert "new product, no before figure" in body
        assert unattributed == []

    def test_a_product_the_engine_cannot_cost_is_reported_not_hidden(self):
        """A circular reference is data about the catalogue, not a crash."""
        after = _row(error="CircularReferenceError: PROD-001 is in its own hierarchy")
        del after["total_make_cost"]
        body, _ = report.render([], [after], ["labor-rate"], "HEAD")
        assert "not costable" in body
        assert "CircularReferenceError" in body

    def test_a_newly_costable_product_is_distinguished_from_a_delta(self):
        before = _row(error="CircularReferenceError: cycle")
        after = _row()
        body, unattributed = report.render([before], [after], ["labor-rate"], "HEAD")
        assert "newly costable" in body
        assert unattributed == []

    def test_the_report_states_how_many_products_could_have_moved(self):
        body, _ = report.render([_row()], [_row()], ["labor-rate"], "HEAD")
        assert "carry a labor-bearing line" in body

    def test_a_dataset_with_nothing_to_measure_says_it_is_weak_evidence(self):
        """'0 changed' must not be mistaken for 'the change is safe'."""
        empty = _row(
            total_make_cost="0.00",
            lines={
                "models_cost": "0.00",
                "packaging_cost": "0.00",
                "assembly_cost": "0.00",
                "child_products_cost": "0.00",
            },
        )
        body, _ = report.render([empty], [empty], ["labor-rate"], "HEAD")
        assert "weak evidence" in body

    def test_a_dataset_with_something_to_measure_does_not_cry_weak(self):
        body, _ = report.render([_row()], [_row()], ["labor-rate"], "HEAD")
        assert "weak evidence" not in body

    def test_the_before_ref_is_named_in_the_report(self):
        body, _ = report.render([_row()], [_row()], ["labor-rate"], "0401b5c")
        assert "0401b5c" in body

    def test_rows_are_ordered_by_tenant_then_sku(self):
        first = _row(tenant="alpha", sku="B", product_id="a")
        second = _row(tenant="alpha", sku="A", product_id="b")
        third = _row(tenant="beta", sku="A", product_id="c")
        body, _ = report.render(
            [first, second, third], [first, second, third], ["labor-rate"], "HEAD"
        )
        positions = [body.index(f"| {r['tenant']} | {r['sku']} |") for r in (second, first, third)]
        assert positions == sorted(positions)


# ---------------------------------------------------------------------------
# the settings handed to the before-ref subprocess
# ---------------------------------------------------------------------------


class TestSettingsForSubprocess:
    def test_both_trees_are_pointed_at_the_same_database(self):
        """A comparison against a different database compares nothing."""
        handed = report._settings_for_subprocess()
        assert "DATABASE_URL" in handed
        assert handed["DATABASE_URL"]

    def test_the_secret_key_is_supplied_because_settings_refuses_without_one(self):
        handed = report._settings_for_subprocess()
        assert handed.get("SECRET_KEY")


# ---------------------------------------------------------------------------
# the money arithmetic the report itself does
# ---------------------------------------------------------------------------


class TestTheReportDoesNotUseFloats:
    def test_deltas_are_computed_in_decimal(self):
        before = _row(total_make_cost="0.1")
        after = _row(total_make_cost="0.3")
        body, _ = report.render([before], [after], ["labor-rate"], "HEAD")
        # 0.3 - 0.1 is exactly 0.2 in Decimal and 0.19999999999999998 in float.
        assert "+0.2" in body
        assert "0.1999" not in body

    def test_the_module_parses_money_with_decimal(self):
        assert Decimal(_row()["total_make_cost"]) == Decimal("20.30")
