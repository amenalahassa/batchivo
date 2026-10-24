"""The fee engine's evaluation semantics (task T056).

Three properties, each of which is a way a marketplace fee model is usually got
wrong (research.md D9):

* **All seven bases charge the amount or count they name**, and nothing else.
* **Rules evaluate in ``sort_order``**, and reordering them cannot change any
  total -- order decides presentation, not arithmetic.
* **No fee is ever charged on another fee.** This is asserted structurally:
  adding an enormous fee to the stack must not move any other fee by a cent.

Every expected figure is recomputed from the rule's own inputs. Nothing is
asserted as a literal that a wrong implementation could be made to match by
editing the literal.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.fee_rule import COUNT_BASES, FEE_BASES, PERIODIC_BASES
from app.services import fee_engine
from app.services.fee_engine import FeeRuleInvalid, OrderContext
from tests.unit.pricing.conftest import make_channel, make_fee_rule

AS_OF = date(2026, 6, 1)
HUNDRED = Decimal("100")

#: A context whose every amount and count differs, so a rule charged on the
#: wrong one is caught rather than coinciding with the right answer.
CONTEXT = OrderContext(
    item_subtotal=Decimal("50.00"),
    shipping_revenue=Decimal("7.00"),
    extras=Decimal("3.00"),
    quantity=3,
    listings=11,
    months=2,
)


def _compute(rules, context=CONTEXT, **kwargs):
    channel = make_channel(fee_rules=rules)
    return fee_engine.compute(channel, context, AS_OF, **kwargs)


# ============================================================================
# The seven bases
# ============================================================================


class TestEveryBasisChargesWhatItNames:
    @pytest.mark.parametrize(
        ("basis", "expected"),
        [
            ("item_subtotal", CONTEXT.item_subtotal),
            ("item_plus_shipping", CONTEXT.item_subtotal + CONTEXT.shipping_revenue),
            (
                "order_total",
                CONTEXT.item_subtotal + CONTEXT.shipping_revenue + CONTEXT.extras,
            ),
            ("per_order", Decimal(1)),
            ("per_unit_sold", Decimal(CONTEXT.quantity)),
            ("per_listing", Decimal(CONTEXT.listings)),
            ("per_month", Decimal(CONTEXT.months)),
        ],
    )
    def test_the_basis_amount_is_the_one_the_basis_names(
        self, basis: str, expected: Decimal
    ) -> None:
        rule = make_fee_rule("fee", basis, fixed_amount=Decimal("1.00"))
        stack = _compute([rule], include_periodic=True)

        charge = stack.named("fee")
        assert charge is not None
        assert charge.basis_amount == expected

    def test_all_seven_bases_are_covered_by_this_suite(self) -> None:
        """A basis added to the model without a test here is a gap, not a pass."""
        covered = {
            "item_subtotal",
            "item_plus_shipping",
            "order_total",
            "per_order",
            "per_unit_sold",
            "per_listing",
            "per_month",
        }
        assert covered == set(FEE_BASES)

    def test_an_amount_basis_charges_rate_then_adds_the_fixed_amount(self) -> None:
        rule = make_fee_rule(
            "fee",
            "item_plus_shipping",
            rate_pct=Decimal("6.5"),
            fixed_amount=Decimal("0.30"),
        )
        stack = _compute([rule])

        expected = CONTEXT.item_plus_shipping * Decimal("6.5") / HUNDRED + Decimal("0.30")
        assert stack.named("fee").amount_exact == expected

    def test_a_count_basis_charges_its_fixed_amount_once_per_thing_counted(self) -> None:
        rule = make_fee_rule("fee", "per_unit_sold", fixed_amount=Decimal("0.45"))
        stack = _compute([rule])

        assert stack.named("fee").amount_exact == Decimal("0.45") * Decimal(CONTEXT.quantity)

    def test_shipping_revenue_is_never_netted_before_a_fee(self) -> None:
        """FR-023, stated as the requirement states it.

        The fee is charged on the shipping the customer paid, not on what is
        left of it after postage -- which the engine never sees at all, and
        that is the structural half of this guarantee.
        """
        rule = make_fee_rule("fee", "item_plus_shipping", rate_pct=Decimal("10"))
        stack = _compute([rule])

        charged_on = stack.named("fee").basis_amount
        assert charged_on == CONTEXT.item_subtotal + CONTEXT.shipping_revenue
        assert charged_on > CONTEXT.item_subtotal

    def test_sales_tax_enters_no_basis(self) -> None:
        """FR-028c: tax is not revenue, so no fee is charged on it."""
        taxed = OrderContext(
            item_subtotal=CONTEXT.item_subtotal,
            shipping_revenue=CONTEXT.shipping_revenue,
            extras=CONTEXT.extras,
            quantity=CONTEXT.quantity,
            sales_tax_collected=Decimal("13.00"),
        )
        rule = make_fee_rule("fee", "order_total", rate_pct=Decimal("10"))

        with_tax = _compute([rule], taxed)
        without_tax = _compute([rule], CONTEXT)

        assert with_tax.named("fee").amount_exact == without_tax.named("fee").amount_exact


# ============================================================================
# Order, and the absence of fee-on-fee
# ============================================================================


class TestRulesEvaluateInSortOrder:
    def test_the_itemised_list_is_in_sort_order(self) -> None:
        rules = [
            make_fee_rule("third", "per_order", fixed_amount=Decimal("1"), sort_order=30),
            make_fee_rule("first", "per_order", fixed_amount=Decimal("1"), sort_order=10),
            make_fee_rule("second", "per_order", fixed_amount=Decimal("1"), sort_order=20),
        ]
        stack = _compute(rules)

        assert [charge.name for charge in stack.charges] == ["first", "second", "third"]

    def test_a_tie_on_sort_order_is_broken_by_name_not_by_insertion(self) -> None:
        """Two channels configured the same way must present the same way."""
        forwards = _compute(
            [
                make_fee_rule("alpha", "per_order", fixed_amount=Decimal("1"), sort_order=10),
                make_fee_rule("beta", "per_order", fixed_amount=Decimal("1"), sort_order=10),
            ]
        )
        backwards = _compute(
            [
                make_fee_rule("beta", "per_order", fixed_amount=Decimal("1"), sort_order=10),
                make_fee_rule("alpha", "per_order", fixed_amount=Decimal("1"), sort_order=10),
            ]
        )

        assert [c.name for c in forwards.charges] == [c.name for c in backwards.charges]

    def test_reordering_the_rules_changes_no_total(self) -> None:
        """The arithmetic consequence of there being no fee on a fee."""
        rules = [
            make_fee_rule("a", "item_subtotal", rate_pct=Decimal("6.5"), sort_order=10),
            make_fee_rule("b", "order_total", rate_pct=Decimal("3"), sort_order=20),
            make_fee_rule("c", "per_order", fixed_amount=Decimal("2"), sort_order=30),
        ]
        reversed_order = [
            make_fee_rule("c", "per_order", fixed_amount=Decimal("2"), sort_order=10),
            make_fee_rule("b", "order_total", rate_pct=Decimal("3"), sort_order=20),
            make_fee_rule("a", "item_subtotal", rate_pct=Decimal("6.5"), sort_order=30),
        ]

        assert _compute(rules).total_exact == _compute(reversed_order).total_exact


class TestNoFeeIsChargedOnAnotherFee:
    def test_adding_an_enormous_fee_moves_no_other_fee(self) -> None:
        """research.md D9, asserted where it would actually break.

        If any basis were derived from another rule's output, a fee large
        enough to dominate the order would move every rule evaluated after it.
        """
        base = [
            make_fee_rule("a", "item_subtotal", rate_pct=Decimal("6.5"), sort_order=10),
            make_fee_rule("b", "item_plus_shipping", rate_pct=Decimal("3"), sort_order=20),
            make_fee_rule("c", "order_total", rate_pct=Decimal("3"), sort_order=30),
        ]
        with_whale = base + [
            make_fee_rule("whale", "per_order", fixed_amount=Decimal("10000"), sort_order=1)
        ]

        before = {c.name: c.amount_exact for c in _compute(base).charges}
        after = {c.name: c.amount_exact for c in _compute(with_whale).charges}

        for name in ("a", "b", "c"):
            assert before[name] == after[name], f"{name} moved when another fee grew"

    def test_the_total_is_the_sum_of_the_parts(self) -> None:
        rules = [
            make_fee_rule("a", "item_subtotal", rate_pct=Decimal("6.5"), sort_order=10),
            make_fee_rule("b", "per_unit_sold", fixed_amount=Decimal("0.45"), sort_order=20),
        ]
        stack = _compute(rules)

        assert stack.total_exact == sum((c.amount_exact for c in stack.charges), Decimal("0"))


# ============================================================================
# Effective dates
# ============================================================================


class TestEffectiveDates:
    def test_a_rule_that_had_not_started_is_not_charged(self) -> None:
        rule = make_fee_rule(
            "future",
            "per_order",
            fixed_amount=Decimal("5"),
            applies_from=AS_OF.replace(year=AS_OF.year + 1),
        )
        assert _compute([rule]).charges == []

    def test_a_rule_that_has_ended_is_not_charged(self) -> None:
        rule = make_fee_rule(
            "past",
            "per_order",
            fixed_amount=Decimal("5"),
            applies_from=date(2020, 1, 1),
            applies_to=date(2021, 1, 1),
        )
        assert _compute([rule]).charges == []

    def test_the_boundary_days_are_both_inclusive(self) -> None:
        rule = make_fee_rule(
            "exact",
            "per_order",
            fixed_amount=Decimal("5"),
            applies_from=AS_OF,
            applies_to=AS_OF,
        )
        assert _compute([rule]).named("exact") is not None


# ============================================================================
# Periodic rules
# ============================================================================


class TestPeriodicRulesAreNotChargedOnASale:
    @pytest.mark.parametrize("basis", sorted(PERIODIC_BASES))
    def test_a_periodic_rule_is_reported_separately_not_charged(self, basis: str) -> None:
        """FR-025: absorbed over a period's order volume, not on one sale."""
        rule = make_fee_rule("periodic", basis, fixed_amount=Decimal("0.22"))
        stack = _compute([rule])

        assert stack.charges == []
        assert [c.name for c in stack.periodic] == ["periodic"]
        assert stack.total_exact == Decimal("0")

    def test_a_periodic_rule_is_never_silently_dropped(self) -> None:
        """An operator who configured a listing fee must still see it."""
        rule = make_fee_rule("listing", "per_listing", fixed_amount=Decimal("0.22"))
        stack = _compute([rule])

        assert stack.periodic_total_exact == Decimal("0.22") * Decimal(CONTEXT.listings)

    def test_the_period_view_charges_them(self) -> None:
        rule = make_fee_rule("listing", "per_listing", fixed_amount=Decimal("0.22"))
        stack = _compute([rule], include_periodic=True)

        assert stack.named("listing") is not None
        assert stack.periodic == []


# ============================================================================
# Incidence
# ============================================================================


class TestExpectedIncidence:
    def test_an_incidence_scales_the_amount_and_labels_it_an_expectation(self) -> None:
        """FR-029: an expectation must be distinct from an amount charged."""
        rule = make_fee_rule(
            "offsite_ads",
            "order_total",
            rate_pct=Decimal("15"),
            incidence_pct=Decimal("20"),
        )
        stack = _compute([rule])
        charge = stack.named("offsite_ads")

        full = CONTEXT.order_total * Decimal("15") / HUNDRED
        assert charge.amount_exact == full * Decimal("20") / HUNDRED
        assert charge.is_expected is True

    def test_an_incidence_of_a_hundred_percent_is_not_an_expectation(self) -> None:
        """A fee that lands on every order is charged, not expected."""
        rule = make_fee_rule(
            "always",
            "order_total",
            rate_pct=Decimal("15"),
            incidence_pct=Decimal("100"),
        )
        charge = _compute([rule]).named("always")

        assert charge.is_expected is False
        assert charge.amount_exact == CONTEXT.order_total * Decimal("15") / HUNDRED

    def test_no_incidence_at_all_is_not_an_expectation(self) -> None:
        rule = make_fee_rule("always", "order_total", rate_pct=Decimal("15"))
        assert _compute([rule]).named("always").is_expected is False


# ============================================================================
# Validation at save time
# ============================================================================


class TestRuleValidation:
    def test_a_rate_on_a_count_basis_is_refused_rather_than_ignored(self) -> None:
        """A percentage of a quantity is not an amount."""
        for basis in sorted(COUNT_BASES):
            with pytest.raises(FeeRuleInvalid, match="count, not an amount"):
                fee_engine.validate_rule(basis=basis, rate_pct=Decimal("3"))

    def test_an_unknown_basis_is_refused(self) -> None:
        with pytest.raises(FeeRuleInvalid, match="basis must be one of"):
            fee_engine.validate_rule(basis="per_fortnight")

    def test_a_negative_rate_is_refused(self) -> None:
        with pytest.raises(FeeRuleInvalid, match="cannot be negative"):
            fee_engine.validate_rule(basis="item_subtotal", rate_pct=Decimal("-1"))

    def test_an_incidence_outside_nought_to_a_hundred_is_refused(self) -> None:
        with pytest.raises(FeeRuleInvalid, match="share of orders"):
            fee_engine.validate_rule(basis="item_subtotal", incidence_pct=Decimal("140"))


# ============================================================================
# Rounding
# ============================================================================


class TestRounding:
    def test_each_charge_carries_both_the_exact_and_the_rounded_amount(self) -> None:
        rule = make_fee_rule("fee", "item_plus_shipping", rate_pct=Decimal("6.5"))
        charge = _compute([rule]).named("fee")

        assert charge.amount == charge.amount_exact.quantize(Decimal("0.01"))
        assert charge.amount != charge.amount_exact, (
            "this case was chosen because it does not land on a cent; if it "
            "now does, the test has stopped covering the rounding boundary"
        )

    def test_the_total_rounds_once_rather_than_summing_rounded_charges(self) -> None:
        """The boundary the acceptance margin depends on.

        Five fees each a third of a cent short round down to five cents less
        when rounded individually. The margin chain consumes ``total_exact``
        for exactly this reason.
        """
        rules = [
            make_fee_rule(
                f"fee{index}", "item_subtotal", rate_pct=Decimal("0.337"), sort_order=index
            )
            for index in range(5)
        ]
        stack = _compute(rules)

        summed_rounded = sum((c.amount for c in stack.charges), Decimal("0"))
        assert stack.total == stack.total_exact.quantize(Decimal("0.01"))
        assert stack.total != summed_rounded


# ---------------------------------------------------------------------------
# A period's periodic charges, computed once (task T214)
# ---------------------------------------------------------------------------


class TestMonthsIn:
    @pytest.mark.parametrize(
        ("start", "end", "months"),
        [
            (date(2026, 6, 1), date(2026, 6, 30), Decimal("1")),
            (date(2026, 1, 1), date(2026, 3, 31), Decimal("3")),
            (date(2026, 2, 1), date(2026, 2, 28), Decimal("1")),
            (date(2026, 6, 1), date(2026, 6, 15), Decimal("0.5")),
            (date(2026, 6, 16), date(2026, 7, 31), Decimal("1.5")),
        ],
    )
    def test_whole_and_partial_months_are_measured_exactly(self, start, end, months) -> None:
        assert fee_engine.months_in(start, end) == months

    def test_a_reversed_range_covers_nothing(self) -> None:
        assert fee_engine.months_in(date(2026, 6, 30), date(2026, 6, 1)) == Decimal("0")


class TestPeriodicCharges:
    def test_a_monthly_rule_is_charged_for_the_months_of_the_period(self) -> None:
        rule = make_fee_rule("shop", "per_month", fixed_amount=Decimal("10"))

        charges = fee_engine.periodic_charges(
            [rule], date(2026, 1, 1), date(2026, 3, 31), listings=0
        )

        assert [c.amount_exact for c in charges] == [Decimal("30")]

    def test_a_listing_rule_is_charged_per_listing_once_per_period(self) -> None:
        rule = make_fee_rule("listing", "per_listing", fixed_amount=Decimal("0.20"))

        charges = fee_engine.periodic_charges(
            [rule], date(2026, 1, 1), date(2026, 3, 31), listings=7
        )

        assert [c.amount_exact for c in charges] == [Decimal("1.40")]

    def test_a_rule_not_in_force_during_the_period_charges_nothing(self) -> None:
        rule = make_fee_rule(
            "shop", "per_month", fixed_amount=Decimal("10"), applies_to=date(2025, 12, 31)
        )

        assert (
            fee_engine.periodic_charges([rule], date(2026, 1, 1), date(2026, 1, 31), listings=0)
            == []
        )

    def test_a_per_sale_rule_is_not_a_periodic_charge(self) -> None:
        rule = make_fee_rule("transaction", "item_subtotal", rate_pct=Decimal("6.5"))

        assert (
            fee_engine.periodic_charges([rule], date(2026, 1, 1), date(2026, 1, 31), listings=3)
            == []
        )

    def test_a_cap_still_binds_at_period_scale(self) -> None:
        rule = make_fee_rule(
            "shop", "per_month", fixed_amount=Decimal("10"), max_amount=Decimal("25")
        )

        [charge] = fee_engine.periodic_charges(
            [rule], date(2026, 1, 1), date(2026, 3, 31), listings=0
        )

        assert charge.amount_exact == Decimal("25")
        assert charge.clamp_applied == "max"
