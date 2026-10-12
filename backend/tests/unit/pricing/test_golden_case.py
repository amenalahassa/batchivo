"""The acceptance case: a make-cost of CA$20.30, recomputed from its inputs.

SC-002 and US2 scenario 1 both name CA$20.30. Not one figure in this file is
copied from the spec and asserted as a constant: every expected amount is
derived here from `tests/fixtures/golden_case.py`, in one unrounded chain per
line, and rounded once at the end. A fixture carrying both the inputs and the
answers would let a wrong answer be pasted in beside the inputs that contradict
it, which the Constitution's Development Workflow section names as a failed
change.

**Where the rounding happens, and why it matters to a half-cent.**

Each line is computed unrounded and rounded once to the cent -- the unit money
is actually paid in -- and the total is the sum of those rounded lines. That is
what makes a breakdown add up: an operator reading the lines reaches the total
they are quoted.

The alternative, carrying every line unrounded into one sum and rounding only
that, gives 20.3051 for this case, which presents as CA$20.31. The difference
is half a cent and it is not an accident of either approach: it is the price of
making the lines sum to the total. The spec's whole downstream chain -- the
35.3% margin, the CA$22.92 profit, the CA$2.41 per machine-hour and the
CA$64.64 solved price -- is derived from 20.30, so 20.30 is the figure the
engine must report. ``test_the_unrounded_chain_differs_by_half_a_cent`` pins
that difference explicitly, so nobody later "fixes" one figure into the other
without noticing which of the two the rest of the spec depends on.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.costing import CostingService
from tests.fixtures import golden_case as golden
from tests.unit.pricing.conftest import (
    MINUTES_PER_HOUR,
    golden_cost_per_gram,
    golden_machine_rate_per_hour,
    golden_overhead_rate_per_machine_hour,
    make_model,
    make_policy,
    make_printer,
    make_product,
)

CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# The expected lines, each derived from the fixture's inputs
# ---------------------------------------------------------------------------


def expected_material() -> Decimal:
    return golden.PART_GRAMS * golden_cost_per_gram()


def expected_waste() -> Decimal:
    return golden.PURGE_GRAMS * golden_cost_per_gram()


def expected_machine() -> Decimal:
    return golden.PRINT_HOURS * golden_machine_rate_per_hour()


def expected_overhead() -> Decimal:
    return golden.PRINT_HOURS * golden_overhead_rate_per_machine_hour()


def expected_handling_labor() -> Decimal:
    return golden.AT_RISK_LABOR_MINUTES / MINUTES_PER_HOUR * golden.LABOR_RATE_PER_HOUR


def expected_packing_labor() -> Decimal:
    return golden.PACKING_LABOR_MINUTES / MINUTES_PER_HOUR * golden.LABOR_RATE_PER_HOUR


def expected_at_risk_subtotal() -> Decimal:
    """The rounded lines the failure premium is charged on (FR-015)."""
    return (
        expected_material().quantize(CENT)
        + expected_waste().quantize(CENT)
        + expected_machine().quantize(CENT)
        + expected_overhead().quantize(CENT)
        + expected_handling_labor().quantize(CENT)
    )


def expected_failure_premium() -> Decimal:
    at_risk = expected_at_risk_subtotal()
    return (at_risk / golden.EXPECTED_YIELD - at_risk).quantize(CENT)


def expected_make_cost() -> Decimal:
    return (
        expected_at_risk_subtotal()
        + expected_failure_premium()
        + expected_packing_labor().quantize(CENT)
        + golden.PACKAGING_COST.quantize(CENT)
    )


@pytest.fixture
def breakdown():
    """The golden product's breakdown: the printed item plus its packaging.

    Packaging materials are a cost line on every physical order (FR-016) and
    live on the sellable product, so the CA$20.30 the spec names is the
    product's make-cost. The item's own figure is asserted separately below.
    """
    model = make_model()
    return CostingService.product_breakdown(
        make_product(model),
        policy=make_policy(),
        printer_for_model={model.id: make_printer()},
    )


class TestTheGoldenMakeCost:
    def test_the_make_cost_is_the_figure_the_spec_names(self, breakdown) -> None:
        assert expected_make_cost() == Decimal("20.30"), (
            "the figures derived from the fixture no longer reach the CA$20.30 "
            "the spec asserts; either an input changed or the spec did"
        )
        assert breakdown.total_make_cost == expected_make_cost()

    def test_every_line_matches_its_own_derivation(self, breakdown) -> None:
        amounts = {line.key: line.amount for line in breakdown.lines}
        assert amounts["material"] == expected_material().quantize(CENT)
        assert amounts["waste"] == expected_waste().quantize(CENT)
        assert amounts["machine"] == expected_machine().quantize(CENT)
        assert amounts["overhead"] == expected_overhead().quantize(CENT)
        assert amounts["labor_handling"] == expected_handling_labor().quantize(CENT)
        assert amounts["labor_packing"] == expected_packing_labor().quantize(CENT)
        assert amounts["packaging"] == golden.PACKAGING_COST.quantize(CENT)

    def test_the_breakdown_names_every_line_the_scenario_requires(self, breakdown) -> None:
        """US2 scenario 1: material, waste, machine, labor, overhead, packaging."""
        keys = {line.key for line in breakdown.lines}
        assert {
            "material",
            "waste",
            "machine",
            "overhead",
            "labor_handling",
            "labor_packing",
            "packaging",
        } <= keys

    def test_the_lines_sum_to_the_total(self, breakdown) -> None:
        """A breakdown an operator cannot add up is not a breakdown."""
        lines = sum((line.amount for line in breakdown.lines), Decimal("0"))
        assert lines + breakdown.failure_premium == breakdown.total_make_cost

    def test_the_subtotals_split_the_lines_without_loss(self, breakdown) -> None:
        lines = sum((line.amount for line in breakdown.lines), Decimal("0"))
        assert breakdown.at_risk_subtotal + breakdown.not_at_risk_subtotal == lines

    def test_the_premium_is_charged_on_the_at_risk_subtotal_alone(self, breakdown) -> None:
        assert breakdown.at_risk_subtotal == expected_at_risk_subtotal()
        assert breakdown.failure_premium == expected_failure_premium()

    def test_the_yield_and_mode_are_reported_beside_the_premium(self, breakdown) -> None:
        """FR-015e: the same yield figure means different things under each mode."""
        assert breakdown.yield_applied == golden.EXPECTED_YIELD
        assert breakdown.failure_mode == "per_part"

    def test_nothing_is_reported_as_incompletely_costed(self, breakdown) -> None:
        """Every input the golden case needs is present, so FR-019 has nothing to say."""
        assert breakdown.incomplete_reasons == []

    def test_the_unrounded_chain_differs_by_half_a_cent(self) -> None:
        """Pin the half-cent, so neither figure is quietly turned into the other.

        This is not an assertion about the engine: it records *why* the engine
        sums rounded lines. If this ever fails, an input changed and the choice
        of rounding boundary has to be re-argued rather than re-derived.
        """
        at_risk_unrounded = (
            expected_material()
            + expected_waste()
            + expected_machine()
            + expected_overhead()
            + expected_handling_labor()
        )
        one_chain = (
            at_risk_unrounded / golden.EXPECTED_YIELD
            + expected_packing_labor()
            + golden.PACKAGING_COST
        )
        assert one_chain.quantize(CENT) == Decimal("20.31")
        assert expected_make_cost() == Decimal("20.30")
        assert abs(one_chain - expected_make_cost()) < Decimal("0.01")


class TestTheItemWithoutItsPackaging:
    """The printed item's own cost, which is the product's less its packaging."""

    def test_the_item_cost_is_the_make_cost_less_packaging(self) -> None:
        model = make_model()
        item = CostingService.item_breakdown(model, policy=make_policy(), printer=make_printer())
        assert item.total_make_cost == expected_make_cost() - golden.PACKAGING_COST

    def test_the_item_carries_no_packaging_line(self) -> None:
        model = make_model()
        item = CostingService.item_breakdown(model, policy=make_policy(), printer=make_printer())
        assert "packaging" not in {line.key for line in item.lines}

    def test_the_flat_shape_reports_the_same_item_total(self) -> None:
        """The legacy four-field shape is a projection, not a second calculation."""
        model = make_model()
        printer = make_printer()
        policy = make_policy()
        flat = CostingService.calculate_model_cost(model, policy=policy, printer=printer)
        structured = CostingService.item_breakdown(model, policy=policy, printer=printer)
        assert abs(flat.total_cost - structured.total_make_cost) < Decimal("0.01"), (
            "the flat projection and the structured breakdown disagree by more "
            "than presentation rounding, which means they are two calculations"
        )


class TestVaryingPrintHoursAlone:
    """US2's independent test, and scenario 2: only the hour-based lines move."""

    def test_only_machine_and_overhead_move_when_hours_change(self) -> None:
        printer = make_printer()
        policy = make_policy()

        def lines_at(hours: Decimal) -> dict[str, Decimal]:
            model = make_model(print_time_minutes=int(hours * MINUTES_PER_HOUR))
            breakdown = CostingService.item_breakdown(model, policy=policy, printer=printer)
            return {line.key: line.amount for line in breakdown.lines}

        short = lines_at(Decimal("2"))
        long = lines_at(Decimal("10"))

        for key in ("material", "waste", "labor_handling", "labor_packing"):
            assert short[key] == long[key], f"{key} moved when only print hours changed"
        assert long["machine"] > short["machine"]
        assert long["overhead"] > short["overhead"]

    def test_a_ten_hour_print_carries_roughly_five_times_a_two_hour_one(self) -> None:
        """US2 scenario 2, stated as the spec states it: roughly five times."""
        printer = make_printer()
        policy = make_policy()

        def hourly_lines(hours: Decimal) -> Decimal:
            model = make_model(print_time_minutes=int(hours * MINUTES_PER_HOUR))
            breakdown = CostingService.item_breakdown(model, policy=policy, printer=printer)
            return sum(
                (line.amount for line in breakdown.lines if line.key in ("machine", "overhead")),
                Decimal("0"),
            )

        short = hourly_lines(Decimal("2"))
        long = hourly_lines(Decimal("10"))
        ratio = long / short
        assert Decimal("4.9") < ratio < Decimal("5.1"), (
            f"ten hours cost {ratio} times two hours, not roughly five"
        )

    def test_no_print_time_is_reported_incomplete_rather_than_free(self) -> None:
        """Spec edge case: zero-hour or missing print time (FR-019)."""
        model = make_model(print_time_minutes=None)
        breakdown = CostingService.item_breakdown(
            model, policy=make_policy(), printer=make_printer()
        )
        keys = {line.key for line in breakdown.lines}
        assert "machine" not in keys
        assert "overhead" not in keys
        assert any("print time" in reason for reason in breakdown.incomplete_reasons)


# ===========================================================================
# The golden margin (task T063)
# ===========================================================================


class TestTheGoldenMargin:
    """SC-002: 35.3% at CA$64.99 on the default basis.

    Same discipline as the make-cost above. Not one figure here is copied from
    the spec: the channel's aggregate rate and fixed amount are recomputed from
    the fee rules in the fixture, the fees from those rules, and the margin from
    the fees -- so changing a rate fails the case that depends on it rather than
    quietly moving the answer.

    research.md D10 pins the aggregate the rest of the spec rests on: a variable
    rate of 12.5%, a 2.5% refund reserve, CA$2.52 of fixed fees, and costs of
    CA$29.80 -- the CA$20.30 make-cost plus CA$9.50 of postage the operator pays
    because the channel advertises free shipping.
    """

    @pytest.fixture
    def margin(self, breakdown):
        from app.services import fee_engine
        from tests.unit.pricing.conftest import make_channel

        channel = make_channel()
        context, treatment = fee_engine.exclusive_context(
            item_subtotal=golden.LIST_PRICE,
            shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
        )
        return CostingService.margin(
            context=context,
            make_cost=breakdown.total_make_cost,
            channel=channel,
            fees=fee_engine.compute(channel, context, date(2026, 6, 1)),
            policy=make_policy(),
            tax=treatment,
            postage_paid=golden.POSTAGE_PAID,
        )

    def test_the_channel_charges_the_aggregate_research_pinned(self) -> None:
        """The decomposition must still add up to the case the spec rests on."""
        from tests.unit.pricing.conftest import golden_fixed_fee_total, golden_variable_rate_pct

        assert golden_variable_rate_pct() == Decimal("12.5")
        assert golden_fixed_fee_total() == Decimal("2.52")
        assert golden.CHANNEL_EXPECTED_REFUND_PCT == Decimal("2.5")

    def test_the_costs_the_solver_works_against_are_the_figure_research_names(
        self, breakdown
    ) -> None:
        """CA$29.80: the make-cost plus the postage free shipping costs."""
        assert breakdown.total_make_cost + golden.POSTAGE_PAID == Decimal("29.80")

    def test_the_margin_is_the_figure_the_spec_names(self, margin) -> None:
        assert margin.margin_pct_display == Decimal("35.3")

    def test_the_profit_is_the_figure_the_spec_names(self, margin) -> None:
        """SC-002a names CA$22.92, and every basis must keep it."""
        assert margin.profit == Decimal("22.92")

    def test_the_margin_is_the_profit_over_the_customer_total(self, margin) -> None:
        expected = (
            margin.profit / (golden.LIST_PRICE + golden.CHANNEL_SHIPPING_REVENUE) * Decimal("100")
        )
        assert margin.margin_pct_display == expected.quantize(Decimal("0.1"))

    def test_the_default_basis_is_named_beside_the_figure(self, margin) -> None:
        """FR-031a and FR-031b together."""
        assert margin.margin_basis == "customer_total"
        assert margin.margin_basis_label

    def test_the_itemised_list_names_every_fee_the_channel_charges(self, margin) -> None:
        """US3 scenario 1: each fee with the amount it contributed."""
        charged = {charge.name for charge in margin.fees}
        configured = {
            name for name, basis, _, _, _ in golden.CHANNEL_FEE_RULES if basis != "per_listing"
        }
        assert charged == configured
        for charge in margin.fees:
            assert charge.amount > Decimal("0")
            assert charge.basis

    def test_each_fee_is_recomputable_from_its_own_inputs(self, margin) -> None:
        for charge in margin.fees:
            if charge.basis == "per_order":
                expected = charge.fixed_amount
            else:
                expected = (
                    charge.basis_amount * charge.rate_pct / Decimal("100") + charge.fixed_amount
                )
            assert charge.amount_exact == expected, f"{charge.name} does not match its inputs"

    def test_no_clamp_bound_and_no_fee_is_an_expectation(self, margin) -> None:
        """The golden case is deliberately plain, so the figures are readable."""
        assert [c.name for c in margin.fees if c.clamp_bound] == []
        assert [c.name for c in margin.fees if c.is_expected] == []

    def test_the_refund_reserve_reduces_net_revenue(self, margin) -> None:
        """FR-026."""
        reserve = next(d for d in margin.deductions if d.key == "expected_refund")

        assert reserve.rate_pct == golden.CHANNEL_EXPECTED_REFUND_PCT
        assert reserve.amount_exact == (
            golden.LIST_PRICE * golden.CHANNEL_EXPECTED_REFUND_PCT / Decimal("100")
        )

    def test_free_shipping_is_reported_as_a_negative_shipping_line(self, margin) -> None:
        """FR-024: the postage is visible, not buried in the make-cost."""
        assert margin.shipping_revenue == Decimal("0.00")
        assert margin.shipping_net == -golden.POSTAGE_PAID
        assert margin.postage_paid == golden.POSTAGE_PAID

    def test_the_whole_chain_reconciles_to_the_profit(self, margin) -> None:
        """An operator must be able to follow the arithmetic to the answer.

        Reading the *rounded* lines off the screen and subtracting them gives
        CA$22.93; the reported profit is CA$22.92. The cent between them is the
        price of the rounding boundary this chain uses, and it is pinned in
        ``test_the_rounded_lines_read_a_cent_high`` below rather than hidden
        behind a loose tolerance here.
        """
        chain = (
            golden.LIST_PRICE
            + golden.CHANNEL_SHIPPING_REVENUE
            - margin.fee_total
            - margin.deduction_total
            - margin.make_cost
            - margin.postage_paid
        )
        assert abs(chain - margin.profit) <= Decimal("0.01")

    def test_the_rounded_lines_read_a_cent_high(self, margin) -> None:
        """Pin the cent, so neither figure is quietly turned into the other.

        This is the margin chain's counterpart to
        ``test_the_unrounded_chain_differs_by_half_a_cent``, and it records
        *why* the chain rounds once at the end. The fees total CA$10.64375 and
        the reserve CA$1.62475: each rounds down on its own, so subtracting the
        rounded pair leaves a cent more profit than subtracting the exact pair.

        CA$22.92 is the figure SC-002a names and the one the 35.3% margin, the
        CA$2.41 per machine-hour and the CA$64.64 solved price are all derived
        from, so CA$22.92 is what the engine reports. If this ever fails, an
        input changed and the choice of boundary has to be re-argued rather
        than re-derived.
        """
        from_rounded = (
            golden.LIST_PRICE
            + golden.CHANNEL_SHIPPING_REVENUE
            - margin.fee_total
            - margin.deduction_total
            - margin.make_cost
            - margin.postage_paid
        )

        assert from_rounded == Decimal("22.93")
        assert margin.profit == Decimal("22.92")
        assert from_rounded - margin.profit == Decimal("0.01")

    def test_rounding_the_fee_stack_early_would_move_the_reported_margin(self) -> None:
        """Why the margin reads ``total_exact`` and not ``total``.

        Not an assertion about behaviour: a demonstration that the choice is
        load-bearing. Summing the rounded fees instead reports 35.3% still but
        CA$22.93 of profit, which contradicts the figure the rest of the spec
        is derived from.
        """
        from app.services import fee_engine
        from tests.unit.pricing.conftest import make_channel

        channel = make_channel()
        context, _ = fee_engine.exclusive_context(item_subtotal=golden.LIST_PRICE)
        stack = fee_engine.compute(channel, context, date(2026, 6, 1))

        rounded_each = sum((charge.amount for charge in stack.charges), Decimal("0"))
        reserve_rounded = (
            golden.LIST_PRICE * golden.CHANNEL_EXPECTED_REFUND_PCT / Decimal("100")
        ).quantize(Decimal("0.01"))

        naive_profit = (
            golden.LIST_PRICE
            - rounded_each
            - reserve_rounded
            - Decimal("20.30")
            - golden.POSTAGE_PAID
        )
        assert naive_profit == Decimal("22.93")
        assert naive_profit != Decimal("22.92")
