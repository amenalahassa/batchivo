"""A period's margin, derived once (task T160, FR-045/FR-048/FR-031b).

The reconciliation route used to subtract its own profit and choose its own
denominator with a three-way `if`, beside the one `CostingService.margin`
already owns. Constitution III calls a second implementation a defect whether
or not its output currently agrees, so these tests pin the period figure
against the engine's own `basis_amount_for` rather than against a constant --
a copy that drifts fails here rather than on a screen.
"""

from decimal import Decimal

import pytest

from app.services import channel_pnl
from app.services.costing import MARGIN_BASIS_LABELS, basis_amount_for

ZERO = Decimal("0")


def _margin(basis: str, **overrides):
    kwargs = dict(
        revenue_tax_exclusive=Decimal("1000.00"),
        shipping_revenue=Decimal("100.00"),
        planned_fee_total=Decimal("150.00"),
        postage_paid=Decimal("60.00"),
        absorbed_costs=[],
        basis=basis,
    )
    kwargs.update(overrides)
    return channel_pnl.period_margin(**kwargs)


class TestProfit:
    """What the period earned, before any basis is chosen."""

    def test_profit_is_revenue_less_fees_postage_and_absorbed_cost(self):
        absorbed = [
            channel_pnl.absorb(
                key="monthly_cost",
                label="Channel subscription",
                total=Decimal("40.00"),
                order_count=4,
            )
        ]
        result = _margin("customer_total", absorbed_costs=absorbed)
        # 1000 - 150 fees - 60 postage - 40 subscription
        assert result.profit == Decimal("750.00")

    def test_an_unabsorbed_cost_is_not_charged_against_the_period(self):
        """FR-025: a month with no orders reports the cost as unabsorbed.

        Loading it onto the period instead would report a loss that the
        absorption rule deliberately leaves visible as unabsorbed.
        """
        unabsorbed = channel_pnl.absorb(
            key="monthly_cost",
            label="Channel subscription",
            total=Decimal("40.00"),
            order_count=0,
        )
        assert unabsorbed.is_unabsorbed

        result = _margin("customer_total", absorbed_costs=[unabsorbed])
        assert result.profit == Decimal("790.00")


class TestBasis:
    """FR-031: three bases, one denominator-chooser."""

    @pytest.mark.parametrize("basis", sorted(MARGIN_BASIS_LABELS))
    def test_denominator_matches_the_engine(self, basis: str):
        result = _margin(basis)
        expected = basis_amount_for(
            basis,
            item_price=Decimal("1000.00") - Decimal("100.00"),
            customer_total=Decimal("1000.00"),
            fee_total_exact=Decimal("150.00"),
        )
        assert result.basis_amount == expected, (
            f"the period's denominator under {basis} must be the one "
            f"`basis_amount_for` chooses, or two screens disagree about one "
            f"percentage (Constitution III)"
        )

    @pytest.mark.parametrize("basis", sorted(MARGIN_BASIS_LABELS))
    def test_every_percentage_names_its_basis(self, basis: str):
        """FR-031b: two percentages are never compared without their basis."""
        result = _margin(basis)
        assert result.basis == basis
        assert result.basis_label == MARGIN_BASIS_LABELS[basis]

    def test_the_basis_changes_only_the_percentage(self):
        """FR-031c: the profit amount is the same under all three."""
        profits = {_margin(basis).profit for basis in MARGIN_BASIS_LABELS}
        assert profits == {Decimal("790.00")}

    def test_percentages_differ_between_bases(self):
        percentages = {str(_margin(basis).margin_pct) for basis in MARGIN_BASIS_LABELS}
        assert len(percentages) == 3, "three bases that all report the same figure is a bug"


class TestUndefined:
    """A percentage with nothing under it."""

    def test_no_revenue_reports_no_percentage_rather_than_zero(self):
        result = _margin(
            "customer_total",
            revenue_tax_exclusive=ZERO,
            shipping_revenue=ZERO,
            planned_fee_total=ZERO,
            postage_paid=ZERO,
        )
        assert result.margin_pct is None, "zero reads as break-even; undefined is honest"

    def test_fees_consuming_net_revenue_report_no_percentage(self):
        result = _margin(
            "net_revenue",
            revenue_tax_exclusive=Decimal("100.00"),
            planned_fee_total=Decimal("100.00"),
        )
        assert result.basis_amount == ZERO
        assert result.margin_pct is None


class TestExactness:
    """Constitution IV: nothing in the chain becomes a float."""

    def test_every_figure_is_a_decimal(self):
        result = _margin("customer_total")
        assert isinstance(result.profit, Decimal)
        assert isinstance(result.basis_amount, Decimal)
        assert isinstance(result.margin_pct, Decimal)

    def test_the_percentage_is_not_rounded_before_it_is_taken(self):
        """A third of a pound stays a third until the percentage is formed."""
        result = _margin(
            "customer_total",
            revenue_tax_exclusive=Decimal("3.00"),
            shipping_revenue=ZERO,
            planned_fee_total=Decimal("1.00"),
            postage_paid=ZERO,
        )
        # 2 / 3 * 100, to four places, half-up.
        assert result.margin_pct == Decimal("66.6667")
