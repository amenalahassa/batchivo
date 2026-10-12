"""The price ladder: margin at each price, and no opinion about which to pick.

FR-007 is a restraint rather than a feature. What a customer will pay is not
derivable from any data this system holds -- there is no competitor feed, no
demand curve, no willingness-to-pay signal -- so a single "recommended price"
would be a number with nothing behind it, and a number with nothing behind it
is worse than no number at all once it appears on a screen beside figures that
are real.

The ladder is what replaces it: margin, profit and profit per machine-hour at
each of a range of prices, for the operator to choose from. The tests below
assert the two halves of that restraint:

1. the figures on each rung are the real ones, computed by the ordinary margin
   path on the basis in effect; and
2. nothing is stored, and the bounds are inputs rather than constants -- a
   default range baked into the module would be an implied recommendation
   wearing a different hat.
"""

import inspect
from datetime import date
from decimal import Decimal

import pytest

from app.services import fee_engine, pricing_solver
from app.services.costing import MARGIN_BASIS_LABELS, CostingService
from tests.fixtures import golden_case as golden
from tests.unit.pricing.conftest import (
    make_channel,
    make_model,
    make_policy,
    make_printer,
    make_product,
)

CENT = Decimal("0.01")
AS_OF = date(2026, 6, 1)


def golden_make_cost() -> Decimal:
    model = make_model()
    breakdown = CostingService.product_breakdown(
        make_product(model),
        policy=make_policy(),
        printer_for_model={model.id: make_printer()},
    )
    return breakdown.total_make_cost


def ladder(**overrides) -> list[pricing_solver.LadderRung]:
    """The golden ladder, with anything a test needs to vary overridden."""
    kwargs = dict(
        channel=overrides.pop("channel", None) or make_channel(),
        make_cost=golden_make_cost(),
        start=Decimal("50.00"),
        stop=Decimal("80.00"),
        step=Decimal("5.00"),
        as_of=AS_OF,
        postage_paid=golden.POSTAGE_PAID,
        shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
        policy=make_policy(),
    )
    kwargs.update(overrides)
    return pricing_solver.ladder(**kwargs)


# ---------------------------------------------------------------------------
# The rungs carry real figures
# ---------------------------------------------------------------------------


class TestEveryRungReportsTheRealMargin:
    """Each rung's margin is the one the margin endpoint reports at that price.

    A ladder computing its own approximation would be the second
    implementation this feature exists to remove, and the operator would be
    choosing a price from figures that no other screen agrees with.
    """

    @pytest.fixture
    def rungs(self) -> list[pricing_solver.LadderRung]:
        return ladder()

    def test_the_ladder_covers_the_range_asked_for(self, rungs) -> None:
        assert [rung.price for rung in rungs] == [
            Decimal("50.00"),
            Decimal("55.00"),
            Decimal("60.00"),
            Decimal("65.00"),
            Decimal("70.00"),
            Decimal("75.00"),
            Decimal("80.00"),
        ]

    def test_each_rung_agrees_with_the_ordinary_margin_path(self, rungs) -> None:
        channel = make_channel()
        for rung in rungs:
            context, treatment = fee_engine.exclusive_context(
                item_subtotal=rung.price,
                shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
            )
            expected = CostingService.margin(
                context=context,
                make_cost=golden_make_cost(),
                channel=channel,
                fees=fee_engine.compute(channel, context, AS_OF),
                policy=make_policy(),
                tax=treatment,
                postage_paid=golden.POSTAGE_PAID,
            )
            assert rung.margin_pct == expected.margin_pct, f"rung {rung.price}"
            assert rung.profit == expected.profit, f"rung {rung.price}"

    def test_margin_rises_with_price(self, rungs) -> None:
        """The one monotonicity an operator reads the ladder for."""
        margins = [rung.margin_pct for rung in rungs]
        assert margins == sorted(margins)
        assert margins[0] < margins[-1]

    def test_profit_rises_with_price(self, rungs) -> None:
        profits = [rung.profit for rung in rungs]
        assert profits == sorted(profits)

    def test_the_golden_price_appears_on_the_ladder_with_its_known_margin(self) -> None:
        """A rung at CA$64.99 must report the 35.3% the spec names.

        The ladder is not a separate calculation, and this is where that is
        checked against the one figure the whole feature is pinned to.
        """
        rungs = ladder(
            start=golden.LIST_PRICE, stop=golden.LIST_PRICE, step=Decimal("1.00")
        )

        assert len(rungs) == 1
        assert rungs[0].price == golden.LIST_PRICE
        assert rungs[0].margin_pct.quantize(Decimal("0.1")) == Decimal("35.3")

    def test_profit_per_machine_hour_is_reported_when_hours_are_known(self) -> None:
        """US7's headline figure, available on the ladder for the same choice.

        An operator choosing a price is choosing how to spend the machine, so
        the figure that orders the queue belongs beside the margin.
        """
        rungs = ladder(
            start=golden.LIST_PRICE,
            stop=golden.LIST_PRICE,
            step=Decimal("1.00"),
            machine_hours=golden.PRINT_HOURS,
        )

        rung = rungs[0]
        assert rung.profit_per_machine_hour == (
            rung.profit / golden.PRINT_HOURS
        ).quantize(CENT)

    def test_profit_per_machine_hour_is_absent_rather_than_zero_when_unknown(self) -> None:
        """FR-019's discipline: unknown is reported, never costed as nothing."""
        rungs = ladder(start=Decimal("60"), stop=Decimal("60"), step=Decimal("5"))

        assert rungs[0].profit_per_machine_hour is None

    def test_zero_machine_hours_do_not_divide(self) -> None:
        rungs = ladder(
            start=Decimal("60"),
            stop=Decimal("60"),
            step=Decimal("5"),
            machine_hours=Decimal("0"),
        )

        assert rungs[0].profit_per_machine_hour is None


# ---------------------------------------------------------------------------
# The basis in effect
# ---------------------------------------------------------------------------


class TestTheLadderReportsOnTheBasisInEffect:
    """FR-031b: every percentage on the ladder names its basis.

    A ladder of percentages with no basis is a column of numbers that cannot
    be compared with anything, including the margin on the product screen
    beside it.
    """

    @pytest.mark.parametrize("basis", sorted(MARGIN_BASIS_LABELS))
    def test_every_rung_names_the_basis(self, basis: str) -> None:
        rungs = ladder(policy=make_policy(margin_basis=basis))

        assert rungs
        assert all(rung.margin_basis == basis for rung in rungs)

    @pytest.mark.parametrize("basis", sorted(MARGIN_BASIS_LABELS))
    def test_each_rung_is_computed_on_that_basis(self, basis: str) -> None:
        shipping = Decimal("6.00")
        channel = make_channel()
        rungs = ladder(
            channel=channel,
            policy=make_policy(margin_basis=basis),
            shipping_revenue=shipping,
            start=Decimal("60"),
            stop=Decimal("60"),
            step=Decimal("5"),
        )
        expected = pricing_solver.margin_at(
            Decimal("60.00"),
            channel=channel,
            make_cost=golden_make_cost(),
            as_of=AS_OF,
            postage_paid=golden.POSTAGE_PAID,
            shipping_revenue=shipping,
            policy=make_policy(margin_basis=basis),
        )

        assert rungs[0].margin_pct == expected.margin_pct

    def test_the_basis_changes_only_the_percentage(self) -> None:
        """US3's invariant, holding on the ladder too: profit is profit.

        Switching basis changes what the profit is divided by and nothing
        else, so the same price must earn the same money under all three.
        """
        profits = set()
        percentages = set()
        for basis in MARGIN_BASIS_LABELS:
            rungs = ladder(
                policy=make_policy(margin_basis=basis),
                start=Decimal("65"),
                stop=Decimal("65"),
                step=Decimal("5"),
                shipping_revenue=Decimal("6.00"),
            )
            profits.add(rungs[0].profit)
            percentages.add(rungs[0].margin_pct)

        assert len(profits) == 1
        assert len(percentages) == 3

    def test_an_override_wins_over_policy(self) -> None:
        rungs = ladder(
            policy=make_policy(margin_basis="item_price"), margin_basis="net_revenue"
        )

        assert all(rung.margin_basis == "net_revenue" for rung in rungs)


# ---------------------------------------------------------------------------
# FR-007: the bounds are inputs, and nothing is stored
# ---------------------------------------------------------------------------


class TestTheBoundsAreInputsRatherThanConstants:
    """A default range would be an implied recommendation (FR-007).

    If the module chose where the ladder starts and stops, the midpoint of
    that range would function as a recommended price while being derived from
    nothing. So the caller supplies all three, and omitting one is an error
    rather than a default.
    """

    @pytest.mark.parametrize("missing", ["start", "stop", "step"])
    def test_every_bound_is_a_required_argument(self, missing: str) -> None:
        kwargs = dict(
            channel=make_channel(),
            make_cost=golden_make_cost(),
            start=Decimal("50"),
            stop=Decimal("80"),
            step=Decimal("5"),
        )
        del kwargs[missing]

        with pytest.raises(TypeError):
            pricing_solver.ladder(**kwargs)

    def test_no_bound_has_a_default_value(self) -> None:
        """Read off the signature, so a default added later fails here."""
        signature = inspect.signature(pricing_solver.ladder)

        for name in ("start", "stop", "step"):
            assert signature.parameters[name].default is inspect.Parameter.empty

    @pytest.mark.parametrize(
        "start,stop,step,expected",
        [
            (Decimal("10"), Decimal("12"), Decimal("1"), 3),
            (Decimal("10"), Decimal("10"), Decimal("1"), 1),
            (Decimal("10"), Decimal("11"), Decimal("0.25"), 5),
            (Decimal("10"), Decimal("20"), Decimal("10"), 2),
        ],
    )
    def test_the_caller_decides_how_fine_the_ladder_is(
        self, start, stop, step, expected
    ) -> None:
        rungs = ladder(start=start, stop=stop, step=step)

        assert len(rungs) == expected
        assert rungs[0].price == start.quantize(CENT)

    def test_a_step_that_overshoots_stops_at_the_last_rung_within_range(self) -> None:
        rungs = ladder(start=Decimal("10"), stop=Decimal("25"), step=Decimal("7"))

        assert [rung.price for rung in rungs] == [
            Decimal("10.00"),
            Decimal("17.00"),
            Decimal("24.00"),
        ]

    def test_a_zero_step_is_refused_rather_than_looping_forever(self) -> None:
        with pytest.raises(ValueError, match="step"):
            ladder(step=Decimal("0"))

    def test_a_negative_step_is_refused(self) -> None:
        with pytest.raises(ValueError, match="step"):
            ladder(step=Decimal("-5"))

    def test_a_range_that_runs_backwards_is_refused(self) -> None:
        """Silently returning nothing would read as "no price works"."""
        with pytest.raises(ValueError, match="stop"):
            ladder(start=Decimal("80"), stop=Decimal("50"))


class TestTheLadderWritesNothing:
    """FR-007: no market judgement is stored, as a figure or anything else.

    The ladder is a read. It takes no session, so there is nothing it could
    persist even by accident -- which is the structural version of the rule,
    and worth asserting rather than assuming.
    """

    def test_the_ladder_takes_no_database_session(self) -> None:
        signature = inspect.signature(pricing_solver.ladder)

        assert "db" not in signature.parameters
        assert "session" not in signature.parameters

    def test_the_solver_takes_no_database_session_either(self) -> None:
        """The solved price is a proposal too: the operator applies it."""
        signature = inspect.signature(pricing_solver.solve)

        assert "db" not in signature.parameters
        assert "session" not in signature.parameters

    def test_the_module_never_commits(self) -> None:
        """A grep-level guard, cheap and hard to defeat by accident."""
        source = inspect.getsource(pricing_solver)

        assert "commit" not in source
        assert ".add(" not in source

    def test_a_rung_carries_no_identity_to_be_stored_under(self) -> None:
        """A rung is a reported figure, not a record with a key."""
        rung = ladder(start=Decimal("60"), stop=Decimal("60"), step=Decimal("5"))[0]

        assert not hasattr(rung, "id")
        assert not hasattr(rung, "tenant_id")

    def test_rungs_are_immutable(self) -> None:
        """So a caller cannot adjust one and pass it on as the system's view."""
        rung = ladder(start=Decimal("60"), stop=Decimal("60"), step=Decimal("5"))[0]

        with pytest.raises(Exception):
            rung.price = Decimal("1.00")  # type: ignore[misc]


class TestTheLadderOffersNoRecommendation:
    """There is no "best" rung, and no field in which one could hide."""

    def test_no_rung_is_marked_as_recommended(self) -> None:
        rung = ladder(start=Decimal("60"), stop=Decimal("60"), step=Decimal("5"))[0]
        fields = set(rung.__dataclass_fields__)

        assert not fields & {
            "recommended",
            "is_recommended",
            "suggested",
            "best",
            "optimal",
            "score",
            "rank",
        }

    def test_the_rungs_come_back_in_price_order_and_nothing_else(self) -> None:
        """Any other ordering would rank them, which is a recommendation."""
        rungs = ladder()

        assert [r.price for r in rungs] == sorted(r.price for r in rungs)

    def test_a_rung_whose_margin_is_undefined_is_reported_as_undefined(self) -> None:
        """Fees consuming the whole basis gives no percentage, not a zero.

        At a price this low on the net-revenue basis the fees exceed what the
        customer paid, so the denominator is not positive. Reporting zero
        would read as break-even.
        """
        rungs = ladder(
            policy=make_policy(margin_basis="net_revenue"),
            start=Decimal("0.01"),
            stop=Decimal("0.01"),
            step=Decimal("1"),
        )

        assert rungs[0].margin_pct is None
        assert rungs[0].profit < Decimal("0")
