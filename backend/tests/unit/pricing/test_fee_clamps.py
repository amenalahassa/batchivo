"""Fee minimums and maximums, and saying when one bound (task T057).

A capped final-value fee and a "percentage but at least X" processing minimum
are both ordinary marketplace shapes, and both were inexpressible before this
feature. FR-021c is the part that matters most to an operator reading a
breakdown: where a clamp changed the amount, the itemised list has to say so,
or a capped fee reads as a miscalculated one and the engine loses the reader's
trust over a figure that was right.

FR-021d is enforced at save time rather than at compute time, because a rule
whose floor exceeds its cap would otherwise charge whichever the code applied
last -- and which that is would be a property of the implementation rather
than of the operator's intent.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services import fee_engine
from app.services.fee_engine import FeeRuleInvalid, OrderContext
from tests.unit.pricing.conftest import make_channel, make_fee_rule

AS_OF = date(2026, 6, 1)
HUNDRED = Decimal("100")

CONTEXT = OrderContext(item_subtotal=Decimal("200.00"), quantity=1)


def _charge(rule, context=CONTEXT):
    stack = fee_engine.compute(make_channel(fee_rules=[rule]), context, AS_OF)
    return stack.named(rule.name)


def _uncapped_amount(rate: Decimal, fixed: Decimal, context=CONTEXT) -> Decimal:
    """What the rule would have charged with no clamp, from its own inputs."""
    return context.item_subtotal * rate / HUNDRED + fixed


# ============================================================================
# A maximum
# ============================================================================


class TestAMaximumBinds:
    def test_the_fee_charges_the_cap_rather_than_the_rate(self) -> None:
        rate = Decimal("6.5")
        cap = Decimal("5.00")
        assert _uncapped_amount(rate, Decimal("0")) > cap, "fixture must exceed the cap"

        charge = _charge(make_fee_rule("capped", "item_subtotal", rate_pct=rate, max_amount=cap))

        assert charge.amount_exact == cap

    def test_the_itemised_list_says_the_cap_bound(self) -> None:
        """FR-021c. Without this a capped fee reads as a bug in the engine."""
        charge = _charge(
            make_fee_rule(
                "capped",
                "item_subtotal",
                rate_pct=Decimal("6.5"),
                max_amount=Decimal("5.00"),
            )
        )

        assert charge.clamp_applied == "max"
        assert charge.clamp_bound is True

    def test_a_cap_above_the_computed_amount_does_not_bind(self) -> None:
        rate = Decimal("1")
        cap = Decimal("500.00")
        charge = _charge(make_fee_rule("roomy", "item_subtotal", rate_pct=rate, max_amount=cap))

        assert charge.amount_exact == _uncapped_amount(rate, Decimal("0"))
        assert charge.clamp_applied is None

    def test_a_capped_fee_stops_scaling_with_the_amount(self) -> None:
        """The property that breaks the solver's linearity (research.md D10)."""
        rule = make_fee_rule(
            "capped", "item_subtotal", rate_pct=Decimal("6.5"), max_amount=Decimal("5.00")
        )
        small = _charge(rule, OrderContext(item_subtotal=Decimal("200.00")))
        large = _charge(rule, OrderContext(item_subtotal=Decimal("2000.00")))

        assert small.amount_exact == large.amount_exact

    def test_a_capped_rule_leaves_the_variable_rate(self) -> None:
        """A clamped rule no longer belongs in the rate the solver scales."""
        stack = fee_engine.compute(
            make_channel(
                fee_rules=[
                    make_fee_rule("scaling", "item_subtotal", rate_pct=Decimal("3")),
                    make_fee_rule(
                        "capped",
                        "item_subtotal",
                        rate_pct=Decimal("6.5"),
                        max_amount=Decimal("5.00"),
                    ),
                ]
            ),
            CONTEXT,
            AS_OF,
        )

        assert stack.variable_rate_pct == Decimal("3")
        assert stack.bound_clamps == ["capped"]


# ============================================================================
# A minimum
# ============================================================================


class TestAMinimumBinds:
    def test_the_fee_charges_the_floor_rather_than_the_rate(self) -> None:
        """A processing minimum: a percentage, but at least this much."""
        rate = Decimal("3")
        floor = Decimal("20.00")
        context = OrderContext(item_subtotal=Decimal("10.00"))
        assert _uncapped_amount(rate, Decimal("0"), context) < floor

        charge = _charge(
            make_fee_rule("floored", "item_subtotal", rate_pct=rate, min_amount=floor),
            context,
        )

        assert charge.amount_exact == floor
        assert charge.clamp_applied == "min"

    def test_a_floor_below_the_computed_amount_does_not_bind(self) -> None:
        charge = _charge(
            make_fee_rule(
                "floored", "item_subtotal", rate_pct=Decimal("6.5"), min_amount=Decimal("0.01")
            )
        )

        assert charge.clamp_applied is None
        assert charge.amount_exact == _uncapped_amount(Decimal("6.5"), Decimal("0"))

    def test_a_floor_applies_to_a_count_basis_too(self) -> None:
        charge = _charge(
            make_fee_rule(
                "floored",
                "per_unit_sold",
                fixed_amount=Decimal("0.10"),
                min_amount=Decimal("1.00"),
            ),
            OrderContext(item_subtotal=Decimal("50.00"), quantity=2),
        )

        assert charge.amount_exact == Decimal("1.00")
        assert charge.clamp_applied == "min"


# ============================================================================
# A floor above a cap
# ============================================================================


class TestAFloorAboveACapIsRefusedAtSaveTime:
    def test_the_rule_is_rejected_rather_than_resolved(self) -> None:
        """FR-021d. There is no correct amount, so there is no amount."""
        with pytest.raises(FeeRuleInvalid, match="min_amount"):
            fee_engine.validate_rule(
                basis="item_subtotal",
                rate_pct=Decimal("3"),
                min_amount=Decimal("10.00"),
                max_amount=Decimal("5.00"),
            )

    def test_a_floor_equal_to_its_cap_is_allowed(self) -> None:
        """A fee pinned to one amount is unusual, not invalid."""
        fee_engine.validate_rule(
            basis="item_subtotal",
            rate_pct=Decimal("3"),
            min_amount=Decimal("5.00"),
            max_amount=Decimal("5.00"),
        )

    def test_one_clamp_alone_is_always_allowed(self) -> None:
        fee_engine.validate_rule(basis="item_subtotal", min_amount=Decimal("10.00"))
        fee_engine.validate_rule(basis="item_subtotal", max_amount=Decimal("5.00"))


# ============================================================================
# Clamps and incidence together
# ============================================================================


class TestAClampBindsBeforeIncidenceScales:
    def test_the_cap_binds_on_the_charge_then_incidence_scales_it(self) -> None:
        """Order matters, and this is the order the requirements imply.

        A clamp applies to what the rule charges when it lands (FR-021b);
        incidence then turns that into what the channel charges on average
        (FR-029). Scaling first would cap an average rather than a charge, and
        would report a cap as binding on orders where it never did.
        """
        cap = Decimal("5.00")
        charge = _charge(
            make_fee_rule(
                "capped_expectation",
                "item_subtotal",
                rate_pct=Decimal("6.5"),
                max_amount=cap,
                incidence_pct=Decimal("50"),
            )
        )

        assert charge.amount_exact == cap * Decimal("50") / HUNDRED
        assert charge.clamp_applied == "max"
        assert charge.is_expected is True
