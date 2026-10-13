"""The target-margin solver: CA$64.64, and why it is that and not CA$62.00.

The defect this endpoint exists to remove is the one an operator makes with a
calculator: cost plus a markup, then subtract the fees. The fees are charged on
the price being solved for, so subtracting them from a price computed without
them leaves a margin below the one asked for -- several points below, at a
12.5% fee stack and a 35% target.

Every expected figure here is recomputed from `tests/fixtures/golden_case.py`,
never copied from the spec or from research.md. research.md D10 records the
arithmetic as ``P × (1 − 0.125 − 0.025 − 0.35) = 32.32``, so ``P = 64.64``;
:func:`expected_solved_price` below rebuilds that from the fixture's own rows,
which means changing one fee rate fails the case that depends on it instead of
quietly moving the answer.

The test that matters most is not the one asserting CA$64.64 --
``TestTheSolverDoesNotKnowItsOwnFeeArithmetic`` is. The solver linearises each
fee rule to solve in closed form, which is a second expression of the fee
arithmetic and therefore a candidate for the exact defect this whole feature
removed from the cost path (Constitution III). That class asserts the two agree
at arbitrary prices, so they cannot drift apart unnoticed.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services import fee_engine, pricing_solver
from app.services.costing import MARGIN_BASIS_LABELS, CostingService
from tests.fixtures import golden_case as golden
from tests.unit.pricing.conftest import (
    golden_fixed_fee_total,
    golden_variable_rate_pct,
    make_channel,
    make_fee_rule,
    make_model,
    make_policy,
    make_printer,
    make_product,
)

CENT = Decimal("0.01")
HUNDRED = Decimal("100")

#: A date inside every golden fee rule's effective period.
AS_OF = date(2026, 6, 1)


# ---------------------------------------------------------------------------
# The expected answer, derived from the fixture
# ---------------------------------------------------------------------------


def golden_make_cost() -> Decimal:
    """The golden product's make-cost, from the engine that reports it.

    Taken from :class:`CostingService` rather than hardcoded as CA$20.30: the
    solver's answer depends on the cost, so a cost regression must surface here
    as a wrong price rather than be masked by a literal that agrees with the
    spec while the engine no longer does.
    """
    model = make_model()
    breakdown = CostingService.product_breakdown(
        make_product(model),
        policy=make_policy(),
        printer_for_model={model.id: make_printer()},
    )
    return breakdown.total_make_cost


def expected_solved_price() -> Decimal:
    """research.md D10's arithmetic, rebuilt from the fixture's own rows.

    ``P × (1 − variable_rate − refund_reserve − target) = costs + fixed_fees``

    The left side is what survives of each extra dollar of price once the
    percentage fees, the refund reserve and the target margin have taken their
    share; the right side is everything that does not scale with price. Costs
    are the make-cost plus the postage the operator pays because the channel
    advertises free shipping (FR-024).
    """
    variable = golden_variable_rate_pct() / HUNDRED
    reserve = golden.CHANNEL_EXPECTED_REFUND_PCT / HUNDRED
    target = golden.TARGET_MARGIN_PCT / HUNDRED
    costs = golden_make_cost() + golden.POSTAGE_PAID
    return (costs + golden_fixed_fee_total()) / (Decimal("1") - variable - reserve - target)


def solve(**overrides) -> pricing_solver.SolveResult:
    """The golden solve, with anything a test needs to vary overridden."""
    channel = overrides.pop("channel", None) or make_channel()
    kwargs = dict(
        channel=channel,
        make_cost=golden_make_cost(),
        target_margin_pct=golden.TARGET_MARGIN_PCT,
        as_of=AS_OF,
        postage_paid=golden.POSTAGE_PAID,
        shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
        policy=make_policy(),
    )
    kwargs.update(overrides)
    return pricing_solver.solve(**kwargs)


# ---------------------------------------------------------------------------
# FR-032: the price that achieves the target
# ---------------------------------------------------------------------------


class TestTheGoldenSolve:
    """US4's independent test: a 35% target on the golden item and channel."""

    @pytest.fixture
    def result(self) -> pricing_solver.SolveResult:
        return solve()

    def test_the_price_is_the_figure_the_spec_names(self, result) -> None:
        """CA$64.64, recomputed rather than quoted."""
        assert result.achievable is True
        assert result.raw_price == expected_solved_price().quantize(pricing_solver.RAW_PRECISION)
        assert result.price == Decimal("64.64")

    def test_the_target_is_actually_achieved_at_that_price(self, result) -> None:
        """The whole point: ask the margin path and get the target back.

        A solver whose answer the margin endpoint then disputes is worse than
        no solver, because the operator has no way to tell which figure is the
        real one.
        """
        assert result.margin_pct_at_price == golden.TARGET_MARGIN_PCT.quantize(Decimal("0.0001"))

    def test_the_margin_is_confirmed_through_the_ordinary_margin_path(self, result) -> None:
        """Not from the solver's own arithmetic -- from ``CostingService``."""
        channel = make_channel()
        context, treatment = fee_engine.exclusive_context(
            item_subtotal=result.price,
            shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
        )
        margin = CostingService.margin(
            context=context,
            make_cost=golden_make_cost(),
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(),
            tax=treatment,
            postage_paid=golden.POSTAGE_PAID,
        )
        assert margin.margin_pct == result.margin_pct_at_price

    def test_the_naive_calculation_would_have_been_wrong(self, result) -> None:
        """Pin the defect, so nobody "simplifies" the solver back into it.

        Cost plus a markup, then subtract the fees: the price that leaves the
        target margin on an amount that excludes the fees is lower than the one
        that leaves it once the fees land on the higher number. The gap is
        several points of margin, which is why the closed form exists.
        """
        costs = golden_make_cost() + golden.POSTAGE_PAID
        naive = costs / (Decimal("1") - golden.TARGET_MARGIN_PCT / HUNDRED)

        assert naive < result.price
        naive_margin = pricing_solver.margin_at(
            naive.quantize(CENT),
            channel=make_channel(),
            make_cost=golden_make_cost(),
            as_of=AS_OF,
            postage_paid=golden.POSTAGE_PAID,
            shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
            policy=make_policy(),
        )
        assert naive_margin.margin_pct < golden.TARGET_MARGIN_PCT - Decimal("5")

    def test_no_clamp_bound_on_the_plain_case(self, result) -> None:
        assert result.binding_clamps == []

    def test_one_pass_suffices_when_nothing_clamps(self, result) -> None:
        """The clamp loop is bounded, and here it does not run at all."""
        assert result.passes == 1

    def test_the_answer_reports_the_inputs_it_came_from(self, result) -> None:
        """FR-034: an operator asking "why that price" gets the arithmetic."""
        assert result.inputs["make_cost"] == golden_make_cost()
        assert result.inputs["postage_paid"] == golden.POSTAGE_PAID
        assert result.inputs["target_margin_pct"] == golden.TARGET_MARGIN_PCT
        assert result.inputs["margin_basis"] == "customer_total"
        assert result.inputs["fee_rate_pct"] == golden_variable_rate_pct()
        assert result.inputs["as_of"] == AS_OF

    def test_every_monetary_input_is_exact(self, result) -> None:
        """Constitution IV, at the boundary where a float would be easiest."""
        for key in ("make_cost", "postage_paid", "shipping_revenue", "target_margin_pct"):
            assert isinstance(result.inputs[key], Decimal)


# ---------------------------------------------------------------------------
# FR-032 on FR-031's three bases
# ---------------------------------------------------------------------------


class TestEachMarginBasisIsSolvedOnItsOwnTerms:
    """One closed form per basis (research.md D10).

    Shipping revenue is deliberately **non-zero** here. The golden channel
    advertises free shipping, which makes the item price and the customer total
    the same amount and would let a solver that confused the two pass. With
    shipping revenue on the order the three bases have three different answers,
    which is the only way to tell they are each solved correctly.
    """

    SHIPPING_REVENUE = Decimal("6.00")

    def solve_on(self, basis: str) -> pricing_solver.SolveResult:
        return solve(margin_basis=basis, shipping_revenue=self.SHIPPING_REVENUE)

    @pytest.mark.parametrize("basis", sorted(MARGIN_BASIS_LABELS))
    def test_the_raw_price_achieves_the_target_exactly(self, basis: str) -> None:
        """Exactly, to four decimal places, before any rounding.

        The rounded price achieves slightly *more* than the target, because
        every rounding rule rounds up; the raw price is where the closed form
        is tested, and it must be exact rather than close.
        """
        result = self.solve_on(basis)
        achieved = pricing_solver.margin_at(
            result.raw_price,
            channel=make_channel(),
            make_cost=golden_make_cost(),
            as_of=AS_OF,
            postage_paid=golden.POSTAGE_PAID,
            shipping_revenue=self.SHIPPING_REVENUE,
            policy=make_policy(),
            margin_basis=basis,
        )
        assert achieved.margin_pct == golden.TARGET_MARGIN_PCT.quantize(Decimal("0.0001"))

    @pytest.mark.parametrize("basis", sorted(MARGIN_BASIS_LABELS))
    def test_the_figure_names_the_basis_it_was_solved_on(self, basis: str) -> None:
        """FR-031b: a percentage without its basis cannot be compared."""
        result = self.solve_on(basis)
        assert result.margin_basis == basis
        assert result.margin_basis_label == MARGIN_BASIS_LABELS[basis]

    def test_the_three_bases_give_three_different_prices(self) -> None:
        """A stricter basis needs a higher price for the same percentage."""
        prices = {basis: self.solve_on(basis).raw_price for basis in MARGIN_BASIS_LABELS}

        assert len(set(prices.values())) == 3
        # Net revenue after fees is the smallest denominator, so the target is
        # reached soonest; the customer total is the largest, so last.
        assert prices["net_revenue"] < prices["item_price"] < prices["customer_total"]

    def test_the_basis_comes_from_policy_when_no_override_is_given(self) -> None:
        """FR-031: the basis is an operator setting, not a call argument."""
        result = solve(policy=make_policy(margin_basis="item_price"))
        assert result.margin_basis == "item_price"

    def test_an_override_wins_over_policy(self) -> None:
        """The settled-order path needs this: it reports the basis it sold on."""
        result = solve(
            policy=make_policy(margin_basis="item_price"),
            margin_basis="net_revenue",
        )
        assert result.margin_basis == "net_revenue"


# ---------------------------------------------------------------------------
# FR-032a: clamps
# ---------------------------------------------------------------------------


class TestAFeeThatStopsScalingWithPrice:
    """FR-032a: caps and floors break the linearity the closed form assumes.

    The loop solves, asks the fee engine which clamps bound at that price, pins
    each bound fee at the amount its clamp holds it to, and solves again. It is
    bounded by the number of rules that *could* clamp, so it terminates
    deterministically rather than iterating to a fixed point (research.md D10).
    """

    def test_a_capped_fee_is_reported_as_binding(self) -> None:
        rules = [
            make_fee_rule(
                "transaction",
                "item_subtotal",
                rate_pct=Decimal("6.5"),
                max_amount=Decimal("1.50"),
                sort_order=10,
            ),
            make_fee_rule("handling", "per_order", fixed_amount=Decimal("2.00"), sort_order=20),
        ]
        channel = make_channel(fee_rules=rules, expected_refund_pct=Decimal("0"))

        result = solve(channel=channel)

        assert result.achievable is True
        assert result.binding_clamps == ["transaction"]

    def test_a_capped_fee_is_not_a_miscalculated_one(self) -> None:
        """The cap must hold at the price returned, not just at the first pass.

        This is the assertion that makes the clamp loop worth having: the fee
        the engine actually charges at the solved price is the capped amount,
        so the price was solved against the fee that is really charged.
        """
        cap = Decimal("1.50")
        rules = [
            make_fee_rule(
                "transaction",
                "item_subtotal",
                rate_pct=Decimal("6.5"),
                max_amount=cap,
                sort_order=10,
            ),
        ]
        channel = make_channel(fee_rules=rules, expected_refund_pct=Decimal("0"))
        result = solve(channel=channel)

        context = fee_engine.OrderContext(item_subtotal=result.price, quantity=1)
        stack = fee_engine.compute(channel, context, AS_OF, rules=rules)
        charge = next(c for c in stack.charges if c.name == "transaction")

        assert charge.amount_exact == cap
        assert charge.clamp_bound is True

    def test_a_floor_binds_and_is_reported(self) -> None:
        """A minimum is the same break in linearity, from the other side."""
        rules = [
            make_fee_rule(
                "transaction",
                "item_subtotal",
                rate_pct=Decimal("2"),
                min_amount=Decimal("5.00"),
                sort_order=10,
            ),
        ]
        channel = make_channel(fee_rules=rules, expected_refund_pct=Decimal("0"))

        result = solve(channel=channel, postage_paid=Decimal("0"))

        assert result.binding_clamps == ["transaction"]

    def test_the_target_is_still_met_once_a_clamp_binds(self) -> None:
        """Pinning a fee must not quietly cost the operator their margin."""
        rules = [
            make_fee_rule(
                "transaction",
                "item_subtotal",
                rate_pct=Decimal("6.5"),
                max_amount=Decimal("1.50"),
                sort_order=10,
            ),
        ]
        channel = make_channel(fee_rules=rules, expected_refund_pct=Decimal("0"))
        result = solve(channel=channel)

        assert result.margin_pct_at_price >= golden.TARGET_MARGIN_PCT

    def test_the_loop_is_bounded_by_the_rules_that_could_clamp(self) -> None:
        """Two clampable rules, so at most three passes -- and no spinning."""
        rules = [
            make_fee_rule(
                "a",
                "item_subtotal",
                rate_pct=Decimal("6.5"),
                max_amount=Decimal("1.50"),
                sort_order=10,
            ),
            make_fee_rule(
                "b",
                "item_plus_shipping",
                rate_pct=Decimal("3"),
                max_amount=Decimal("0.80"),
                sort_order=20,
            ),
        ]
        channel = make_channel(fee_rules=rules, expected_refund_pct=Decimal("0"))
        result = solve(channel=channel)

        assert result.passes <= len(rules) + 1
        assert sorted(result.binding_clamps) == ["a", "b"]

    def test_an_unclamped_stack_needs_no_second_pass(self) -> None:
        rules = [
            make_fee_rule(
                "transaction",
                "item_subtotal",
                rate_pct=Decimal("6.5"),
                max_amount=Decimal("500.00"),
                sort_order=10,
            ),
        ]
        channel = make_channel(fee_rules=rules)
        result = solve(channel=channel)

        assert result.binding_clamps == []


# ---------------------------------------------------------------------------
# FR-033: adjustments
# ---------------------------------------------------------------------------


class TestEveryMoveAwayFromTheSolvedPriceIsNamed:
    """FR-033: a price that silently differs from the arithmetic is unreadable.

    Both moves here are the operator's own policy rather than a correction, so
    neither is hidden: each is reported with where the price came from and
    where it went.
    """

    @pytest.mark.parametrize(
        "rule,expected",
        [
            ("nearest_dollar", Decimal("65.00")),
            ("psychological_99", Decimal("64.99")),
            ("psychological_95", Decimal("64.95")),
            ("nearest_five_cents", Decimal("64.65")),
        ],
    )
    def test_a_rounding_rule_is_shown_as_an_adjustment(self, rule: str, expected: Decimal) -> None:
        result = solve(rounding_rule=rule)

        rounding = next(a for a in result.adjustments if a.key == "rounding")
        # The adjustment starts from the full-precision solved price, which is
        # what ``raw_price`` reports to four places.
        assert rounding.from_price.quantize(pricing_solver.RAW_PRECISION) == result.raw_price
        assert rounding.to_price == expected
        assert result.price == expected

    @pytest.mark.parametrize(
        "rule",
        ["nearest_dollar", "psychological_99", "psychological_95", "nearest_five_cents"],
    )
    def test_every_rounding_rule_rounds_up(self, rule: str) -> None:
        """A rule that rounded down would return a price below the target.

        That is the one thing the solver must never do quietly: the figure it
        returns is the figure it promises.
        """
        result = solve(rounding_rule=rule)

        assert result.price >= result.raw_price
        assert result.margin_pct_at_price >= golden.TARGET_MARGIN_PCT

    def test_the_raw_price_is_reported_alongside_the_rounded_one(self) -> None:
        """So the adjustment can be checked rather than taken on trust."""
        result = solve(rounding_rule="nearest_dollar")

        assert result.raw_price == expected_solved_price().quantize(pricing_solver.RAW_PRECISION)
        assert result.price == Decimal("65.00")
        assert result.price != result.raw_price

    def test_an_unknown_rounding_rule_falls_back_to_the_cent(self) -> None:
        """A misspelt setting must not 500 a pricing screen."""
        result = solve(rounding_rule="to_the_nearest_goat")

        assert result.achievable is True
        assert result.price == Decimal("64.64")

    def test_the_free_shipping_snap_is_shown_as_an_adjustment(self) -> None:
        """FR-033: the snap is the operator's call, and a visible one."""
        channel = make_channel(free_shipping_threshold=Decimal("75.00"))

        result = solve(channel=channel, snap_to_free_shipping=True)

        snap = next(a for a in result.adjustments if a.key == "free_shipping_snap")
        assert snap.to_price == Decimal("75.00")
        assert snap.delta > Decimal("0")
        assert result.price == Decimal("75.00")

    def test_the_snap_is_off_unless_asked_for(self) -> None:
        """FR-033 makes it a MAY, and doing it unasked would reprice a catalogue."""
        channel = make_channel(free_shipping_threshold=Decimal("75.00"))

        result = solve(channel=channel)

        assert [a.key for a in result.adjustments] == []
        assert result.price == Decimal("64.64")

    def test_a_price_already_above_the_threshold_is_left_alone(self) -> None:
        channel = make_channel(free_shipping_threshold=Decimal("40.00"))

        result = solve(channel=channel, snap_to_free_shipping=True)

        assert [a.key for a in result.adjustments] == []
        assert result.price == Decimal("64.64")

    def test_adjustments_are_reported_in_the_order_applied(self) -> None:
        """FR-033: rounding first, then the snap acting on the rounded price."""
        channel = make_channel(free_shipping_threshold=Decimal("75.00"))

        result = solve(channel=channel, snap_to_free_shipping=True, rounding_rule="nearest_dollar")

        assert [a.key for a in result.adjustments] == ["rounding", "free_shipping_snap"]
        assert result.adjustments[0].to_price == result.adjustments[1].from_price


# ---------------------------------------------------------------------------
# FR-035: no price exists
# ---------------------------------------------------------------------------


class TestATargetNoPriceCanAchieve:
    """FR-035: report the binding constraint, never a number.

    Where the percentage fees plus the reserves plus the target reach the whole
    denominator, every extra dollar of price is consumed by the percentages
    charged on it, so no price leaves the target margin behind. Returning a
    very large number -- or a negative one -- would read as an answer.
    """

    @pytest.fixture
    def result(self) -> pricing_solver.SolveResult:
        return solve(target_margin_pct=Decimal("90"))

    def test_it_is_reported_as_unachievable(self, result) -> None:
        assert result.achievable is False
        assert result.reason == "unachievable"

    def test_no_price_is_returned(self, result) -> None:
        assert result.price is None
        assert result.raw_price is None
        assert result.margin_pct_at_price is None

    def test_the_binding_constraint_is_named_in_words(self, result) -> None:
        """An operator must learn *why*, not just that it failed."""
        assert result.binding_constraint
        assert "90.00%" in result.binding_constraint
        assert "12.50%" in result.binding_constraint

    def test_the_inputs_are_still_reported(self, result) -> None:
        """FR-034 does not stop applying because the answer is "no price"."""
        assert result.inputs["target_margin_pct"] == Decimal("90")
        assert result.inputs["make_cost"] == golden_make_cost()

    def test_the_basis_is_still_named(self, result) -> None:
        assert result.margin_basis == "customer_total"
        assert result.margin_basis_label

    def test_a_target_at_exactly_the_breaking_point_is_unachievable(self) -> None:
        """The boundary: target plus fees plus reserves equal the whole amount.

        At exactly 85% the denominator is zero, which is unachievable rather
        than infinite -- a division would read as a crash and a huge number
        would read as a price.
        """
        breaking = HUNDRED - golden_variable_rate_pct() - golden.CHANNEL_EXPECTED_REFUND_PCT

        result = solve(target_margin_pct=breaking)

        assert result.achievable is False
        assert result.price is None

    def test_a_target_just_below_the_breaking_point_is_achievable(self) -> None:
        """And it is a very large price, which is the honest answer there."""
        breaking = HUNDRED - golden_variable_rate_pct() - golden.CHANNEL_EXPECTED_REFUND_PCT

        result = solve(target_margin_pct=breaking - Decimal("1"))

        assert result.achievable is True
        assert result.price > Decimal("1000")


# ---------------------------------------------------------------------------
# Constitution III, at the one place this feature could reintroduce it
# ---------------------------------------------------------------------------


class TestTheSolverDoesNotKnowItsOwnFeeArithmetic:
    """:func:`pricing_solver.linearise` must agree with :mod:`fee_engine`.

    The solver writes each rule as ``rate × price + constant`` so it can solve
    in closed form. That is a second expression of the fee arithmetic, and a
    second expression that drifts is precisely the defect this feature removed
    from the cost path -- reintroduced one module along. These assertions are
    what keep the two tied together.
    """

    SHIPPING = Decimal("4.25")
    EXTRAS = Decimal("1.10")
    QUANTITY = 3

    @pytest.fixture
    def rules(self) -> list:
        """One rule per basis that scales or counts, so nothing is untested."""
        return [
            make_fee_rule(
                "transaction", "item_plus_shipping", rate_pct=Decimal("6.5"), sort_order=10
            ),
            make_fee_rule(
                "payment",
                "order_total",
                rate_pct=Decimal("3"),
                fixed_amount=Decimal("0.30"),
                sort_order=20,
            ),
            make_fee_rule(
                "regulatory",
                "item_subtotal",
                rate_pct=Decimal("3"),
                fixed_amount=Decimal("0.22"),
                sort_order=30,
            ),
            make_fee_rule("handling", "per_order", fixed_amount=Decimal("2.00"), sort_order=40),
            make_fee_rule("per_unit", "per_unit_sold", fixed_amount=Decimal("0.15"), sort_order=50),
        ]

    @pytest.mark.parametrize(
        "price",
        [Decimal("1.00"), Decimal("17.33"), Decimal("64.99"), Decimal("500.00")],
    )
    def test_the_linear_form_equals_the_fee_engine_at_any_price(
        self, rules, price: Decimal
    ) -> None:
        channel = make_channel(fee_rules=rules)
        lines = pricing_solver.linearise(
            rules,
            as_of=AS_OF,
            shipping_revenue=self.SHIPPING,
            extras=self.EXTRAS,
            quantity=self.QUANTITY,
        )
        context = fee_engine.OrderContext(
            item_subtotal=price,
            shipping_revenue=self.SHIPPING,
            extras=self.EXTRAS,
            quantity=self.QUANTITY,
        )
        stack = fee_engine.compute(channel, context, AS_OF, rules=rules)

        linear_total = sum((line.at(price) for line in lines), Decimal("0"))

        assert linear_total == stack.total_exact

    def test_incidence_scales_the_line_the_way_the_engine_scales_the_charge(self) -> None:
        """An expectation is a planning figure, and both sides must scale it alike."""
        rules = [
            make_fee_rule(
                "offsite_ads",
                "order_total",
                rate_pct=Decimal("15"),
                incidence_pct=Decimal("40"),
                sort_order=10,
            ),
        ]
        channel = make_channel(fee_rules=rules)
        price = Decimal("64.99")

        lines = pricing_solver.linearise(rules, as_of=AS_OF)
        context = fee_engine.OrderContext(item_subtotal=price, quantity=1)
        stack = fee_engine.compute(channel, context, AS_OF, rules=rules)

        assert sum((line.at(price) for line in lines), Decimal("0")) == stack.total_exact

    def test_periodic_rules_are_excluded_from_both(self) -> None:
        """A listing fee is absorbed over a period's volume (FR-025).

        Charging it on one sale would price that sale as though it carried the
        whole month, so neither the solver nor the fee engine may see it here.
        """
        rules = [
            make_fee_rule("listing", "per_listing", fixed_amount=Decimal("0.20"), sort_order=10),
            make_fee_rule(
                "subscription", "per_month", fixed_amount=Decimal("15.00"), sort_order=20
            ),
            make_fee_rule("transaction", "item_subtotal", rate_pct=Decimal("6.5"), sort_order=30),
        ]

        lines = pricing_solver.linearise(rules, as_of=AS_OF)

        assert [line.name for line in lines] == ["transaction"]

    def test_a_rule_outside_its_effective_period_is_not_linearised(self) -> None:
        rules = [
            make_fee_rule(
                "retired",
                "item_subtotal",
                rate_pct=Decimal("6.5"),
                applies_from=date(2020, 1, 1),
                applies_to=date(2021, 1, 1),
                sort_order=10,
            ),
        ]

        assert pricing_solver.linearise(rules, as_of=AS_OF) == []

    def test_the_solver_reports_the_margin_the_margin_path_reports(self) -> None:
        """:func:`pricing_solver.margin_at` must delegate, never recompute."""
        channel = make_channel()
        price = Decimal("64.99")

        through_solver = pricing_solver.margin_at(
            price,
            channel=channel,
            make_cost=golden_make_cost(),
            as_of=AS_OF,
            postage_paid=golden.POSTAGE_PAID,
            policy=make_policy(),
        )
        context, treatment = fee_engine.exclusive_context(
            item_subtotal=price, shipping_revenue=Decimal("0")
        )
        directly = CostingService.margin(
            context=context,
            make_cost=golden_make_cost(),
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(),
            tax=treatment,
            postage_paid=golden.POSTAGE_PAID,
        )

        assert through_solver.margin_pct == directly.margin_pct
        assert through_solver.profit == directly.profit


# ---------------------------------------------------------------------------
# Properties that must hold whatever the inputs
# ---------------------------------------------------------------------------


class TestPropertiesOfTheSolve:
    """Relationships that survive any particular case."""

    @pytest.mark.parametrize("target", [Decimal("5"), Decimal("20"), Decimal("35"), Decimal("50")])
    def test_a_higher_target_needs_a_higher_price(self, target: Decimal) -> None:
        lower = solve(target_margin_pct=target)
        higher = solve(target_margin_pct=target + Decimal("5"))

        assert higher.raw_price > lower.raw_price

    def test_a_higher_cost_needs_a_higher_price(self) -> None:
        cheap = solve(make_cost=golden_make_cost())
        dear = solve(make_cost=golden_make_cost() + Decimal("10"))

        assert dear.raw_price > cheap.raw_price

    def test_postage_the_operator_pays_raises_the_price(self) -> None:
        """FR-024: postage is a cost, so it must move the price like one."""
        free = solve(postage_paid=Decimal("0"))
        paid = solve(postage_paid=Decimal("9.50"))

        assert paid.raw_price > free.raw_price

    def test_a_zero_target_prices_at_break_even(self) -> None:
        """The margin at the solved price is zero, not merely small."""
        result = solve(target_margin_pct=Decimal("0"))

        assert result.achievable is True
        assert result.margin_pct_at_price >= Decimal("0")
        assert result.margin_pct_at_price < Decimal("0.5")
