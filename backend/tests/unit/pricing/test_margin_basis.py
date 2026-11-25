"""The margin basis changes the percentage and nothing else (task T060).

FR-031c is the whole requirement in one line: changing the basis must not alter
any stored figure, any make-cost or any profit amount -- only the percentage
derived from them. SC-002a names the two figures that must hold still: the
make-cost stays CA$20.30 and the profit stays CA$22.92 under all three bases.

FR-031b is the other half. A percentage without its basis is a number two
people will compare and disagree about, so every figure carries the basis that
produced it as data.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.tenant_pricing_policy import MARGIN_BASES
from app.services import fee_engine
from app.services.costing import (
    DEFAULT_MARGIN_BASIS,
    MARGIN_BASIS_LABELS,
    CostingService,
    resolve_margin_basis,
)
from app.services.fee_engine import OrderContext
from tests.fixtures import golden_case as golden
from tests.unit.pricing.conftest import make_channel, make_policy

AS_OF = date(2026, 6, 1)

#: The acceptance case's make-cost. Derived in ``test_golden_case.py`` from the
#: fixture's inputs; taken as given here, because this file is about the
#: denominator rather than about the cost.
MAKE_COST = Decimal("20.30")


def _margin(basis: str | None = None, *, shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE):
    channel = make_channel()
    context, treatment = fee_engine.exclusive_context(
        item_subtotal=golden.LIST_PRICE,
        shipping_revenue=shipping_revenue,
    )
    return CostingService.margin(
        context=context,
        make_cost=MAKE_COST,
        channel=channel,
        fees=fee_engine.compute(channel, context, AS_OF),
        policy=make_policy(margin_basis=basis) if basis else make_policy(),
        tax=treatment,
        postage_paid=golden.POSTAGE_PAID,
    )


# ============================================================================
# Only the percentage moves
# ============================================================================


class TestOnlyThePercentageMoves:
    def test_the_make_cost_is_the_same_under_every_basis(self) -> None:
        costs = {basis: _margin(basis).make_cost for basis in MARGIN_BASES}

        assert set(costs.values()) == {MAKE_COST}

    def test_the_profit_amount_is_the_same_under_every_basis(self) -> None:
        """SC-002a: CA$22.92 under all three."""
        profits = {basis: _margin(basis).profit for basis in MARGIN_BASES}

        assert len(set(profits.values())) == 1, f"the profit amount moved with the basis: {profits}"
        assert set(profits.values()) == {Decimal("22.92")}

    def test_the_fees_are_the_same_under_every_basis(self) -> None:
        """A basis is a denominator. It cannot change what was charged."""
        totals = {basis: _margin(basis).fee_total for basis in MARGIN_BASES}

        assert len(set(totals.values())) == 1

    def test_the_percentage_itself_does_move(self) -> None:
        """Otherwise the setting would be decoration."""
        with_shipping = {
            basis: _margin(basis, shipping_revenue=Decimal("8.00")).margin_pct
            for basis in MARGIN_BASES
        }

        assert len(set(with_shipping.values())) == len(MARGIN_BASES), (
            f"two bases produced the same percentage: {with_shipping}"
        )


# ============================================================================
# Each basis puts the right amount under the profit
# ============================================================================


class TestEachBasisDividesByWhatItNames:
    @pytest.mark.parametrize("basis", sorted(MARGIN_BASES))
    def test_the_percentage_is_the_profit_over_the_basis_amount(self, basis: str) -> None:
        result = _margin(basis, shipping_revenue=Decimal("8.00"))

        recomputed = (result.profit / result.margin_basis_amount * Decimal("100")).quantize(
            Decimal("0.1")
        )
        assert result.margin_pct.quantize(Decimal("0.1")) == recomputed

    def test_customer_total_divides_by_item_plus_shipping_revenue(self) -> None:
        shipping = Decimal("8.00")
        result = _margin("customer_total", shipping_revenue=shipping)

        assert result.margin_basis_amount == golden.LIST_PRICE + shipping

    def test_item_price_divides_by_the_item_alone(self) -> None:
        result = _margin("item_price", shipping_revenue=Decimal("8.00"))

        assert result.margin_basis_amount == golden.LIST_PRICE

    def test_net_revenue_divides_by_the_customer_total_less_fees(self) -> None:
        shipping = Decimal("8.00")
        result = _margin("net_revenue", shipping_revenue=shipping)

        assert result.margin_basis_amount == (
            golden.LIST_PRICE + shipping - result.fee_total
        ).quantize(Decimal("0.01"))

    def test_net_revenue_reports_the_highest_percentage_of_the_three(self) -> None:
        """Its denominator is the smallest, so its percentage is the largest.

        Worth pinning: this is the basis that flatters a figure most, and an
        operator comparing it against a competitor's customer-total margin is
        the comparison FR-031b exists to prevent.
        """
        shipping = Decimal("8.00")
        percentages = {
            basis: _margin(basis, shipping_revenue=shipping).margin_pct for basis in MARGIN_BASES
        }

        assert percentages["net_revenue"] == max(percentages.values())
        assert percentages["customer_total"] == min(percentages.values())

    def test_the_two_revenue_bases_coincide_when_shipping_is_free(self) -> None:
        """The golden case's own shape, stated so it is not mistaken for a bug.

        With no shipping revenue the customer total *is* the item price, so
        those two bases must agree exactly -- and the acceptance figure of
        35.3% therefore holds under either.
        """
        customer_total = _margin("customer_total")
        item_price = _margin("item_price")

        assert customer_total.margin_pct == item_price.margin_pct
        assert customer_total.margin_basis_amount == item_price.margin_basis_amount


# ============================================================================
# Every figure names its basis
# ============================================================================


class TestEveryFigureNamesItsBasis:
    @pytest.mark.parametrize("basis", sorted(MARGIN_BASES))
    def test_the_basis_is_reported_beside_the_percentage(self, basis: str) -> None:
        """FR-031b."""
        result = _margin(basis)

        assert result.margin_basis == basis
        assert result.margin_basis_label == MARGIN_BASIS_LABELS[basis]
        assert result.margin_basis_label

    def test_every_basis_the_model_allows_has_a_label(self) -> None:
        """A basis a screen cannot name is a percentage nobody can compare."""
        assert set(MARGIN_BASIS_LABELS) == set(MARGIN_BASES)


# ============================================================================
# Resolution
# ============================================================================


class TestResolvingTheBasis:
    def test_the_policy_decides(self) -> None:
        assert resolve_margin_basis(make_policy(margin_basis="net_revenue")) == "net_revenue"

    def test_the_default_reproduces_todays_definition(self) -> None:
        """FR-031a: a tenant who changes nothing sees no percentage move."""
        assert DEFAULT_MARGIN_BASIS == "customer_total"
        assert resolve_margin_basis(None) == "customer_total"

    def test_an_override_wins_over_the_policy(self) -> None:
        """FR-031d: a settled order keeps the basis it sold on."""
        policy = make_policy(margin_basis="net_revenue")

        assert resolve_margin_basis(policy, override="item_price") == "item_price"

    def test_an_unknown_basis_falls_back_rather_than_raising(self) -> None:
        """A pricing screen that 500s over a misspelt string is worse."""
        assert resolve_margin_basis(None, override="per_fortnight") == DEFAULT_MARGIN_BASIS

    def test_a_settled_order_is_not_restated_by_a_later_policy_change(self) -> None:
        """FR-031d, through the margin path rather than the resolver alone."""
        sold_on = _margin()
        assert sold_on.margin_basis == "customer_total"

        channel = make_channel()
        context, treatment = fee_engine.exclusive_context(item_subtotal=golden.LIST_PRICE)
        restated = CostingService.margin(
            context=context,
            make_cost=MAKE_COST,
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(margin_basis="net_revenue"),
            tax=treatment,
            postage_paid=golden.POSTAGE_PAID,
            margin_basis="customer_total",
        )

        assert restated.margin_basis == "customer_total"
        assert restated.margin_pct == sold_on.margin_pct


# ============================================================================
# The undefined case
# ============================================================================


class TestNetRevenueConsumedEntirelyByFees:
    def test_the_percentage_is_undefined_rather_than_a_division_by_zero(self) -> None:
        """Spec, Edge Cases: reported as undefined, not divided by zero."""
        from tests.unit.pricing.conftest import make_fee_rule

        channel = make_channel(
            fee_rules=[make_fee_rule("everything", "item_subtotal", rate_pct=Decimal("100"))]
        )
        context = OrderContext(item_subtotal=golden.LIST_PRICE)
        result = CostingService.margin(
            context=context,
            make_cost=MAKE_COST,
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(margin_basis="net_revenue"),
        )

        assert result.margin_basis_amount == Decimal("0.00")
        assert result.margin_pct is None
        assert result.margin_pct_display is None

    def test_the_profit_is_still_reported(self) -> None:
        """An undefined percentage is not an undefined loss."""
        from tests.unit.pricing.conftest import make_fee_rule

        channel = make_channel(
            fee_rules=[make_fee_rule("everything", "item_subtotal", rate_pct=Decimal("100"))]
        )
        context = OrderContext(item_subtotal=golden.LIST_PRICE)
        result = CostingService.margin(
            context=context,
            make_cost=MAKE_COST,
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(margin_basis="net_revenue"),
        )

        assert result.profit < Decimal("0")
