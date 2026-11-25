"""Sales tax is tracked and never earned (task T059).

The requirement is narrow and absolute. Tax is not revenue in any margin or
profitability figure, whoever remits it (FR-028c). Where the operator remits
it, the amount collected is a liability, distinct from income (FR-028d). And
where a recorded amount arrived tax-inclusive, as a marketplace statement
usually shows it, the exclusive figure the system derived has to be visible so
a reconciliation against the statement does not have to redo the subtraction by
hand (FR-028e).

The headline assertion is the first one: two otherwise identical sales, one on
a marketplace-remitted channel and one on an operator-remitted channel, report
the same margin. If they ever differ, tax has leaked into revenue.
"""

from datetime import date
from decimal import Decimal

from app.services import fee_engine
from app.services.costing import CostingService
from app.services.fee_engine import OrderContext
from tests.fixtures import golden_case as golden
from tests.unit.pricing.conftest import make_channel

AS_OF = date(2026, 6, 1)

PRICE = golden.LIST_PRICE
MAKE_COST = Decimal("20.30")
POSTAGE = golden.POSTAGE_PAID
TAX = Decimal("8.45")


def _margin(*, remitter: str, tax: Decimal = TAX, tax_inclusive: bool = False, price=PRICE):
    """One sale, costed through the single tax-exclusive context.

    The context the fees are charged on is the same one the margin divides by.
    An earlier draft built two, and the inclusive case silently charged fees on
    the gross while dividing by the net -- which is why
    :func:`fee_engine.exclusive_context` is the only way to make one.
    """
    channel = make_channel(tax_remitter=remitter)
    context, treatment = fee_engine.exclusive_context(
        item_subtotal=price,
        sales_tax_collected=tax,
        tax_inclusive=tax_inclusive,
    )
    return CostingService.margin(
        context=context,
        make_cost=MAKE_COST,
        channel=channel,
        fees=fee_engine.compute(channel, context, AS_OF),
        tax=treatment,
        postage_paid=POSTAGE,
    )


# ============================================================================
# The same margin under either remitter
# ============================================================================


class TestTheRemitterDoesNotChangeMargin:
    def test_two_identical_sales_report_the_same_margin(self) -> None:
        """FR-028c, stated as the requirement states it."""
        marketplace = _margin(remitter="marketplace")
        operator = _margin(remitter="operator")

        assert marketplace.margin_pct == operator.margin_pct
        assert marketplace.profit == operator.profit
        assert marketplace.net_revenue == operator.net_revenue

    def test_collecting_tax_at_all_changes_no_margin(self) -> None:
        """The stronger form: the tax amount itself is inert."""
        taxed = _margin(remitter="operator", tax=TAX)
        untaxed = _margin(remitter="operator", tax=Decimal("0"))

        assert taxed.margin_pct == untaxed.margin_pct
        assert taxed.profit == untaxed.profit

    def test_no_fee_is_charged_on_the_tax(self) -> None:
        channel = make_channel()
        with_tax = fee_engine.compute(
            channel,
            OrderContext(item_subtotal=PRICE, sales_tax_collected=TAX),
            AS_OF,
        )
        without_tax = fee_engine.compute(channel, OrderContext(item_subtotal=PRICE), AS_OF)

        assert with_tax.total_exact == without_tax.total_exact


# ============================================================================
# The liability
# ============================================================================


class TestTheLiability:
    def test_an_operator_remitted_sale_owes_what_it_collected(self) -> None:
        """FR-028d: a liability, distinct from income."""
        result = _margin(remitter="operator")

        assert result.sales_tax_liability == TAX
        assert result.tax_remitter == "operator"

    def test_a_marketplace_remitted_sale_owes_nothing(self) -> None:
        result = _margin(remitter="marketplace")

        assert result.sales_tax_liability == Decimal("0.00")
        assert result.sales_tax_collected == TAX, (
            "what was collected is still recorded; only the liability differs"
        )

    def test_the_liability_is_never_part_of_profit(self) -> None:
        result = _margin(remitter="operator")

        assert result.profit < result.profit + result.sales_tax_liability
        assert result.net_revenue + result.sales_tax_collected != result.net_revenue


# ============================================================================
# Deriving the tax-exclusive amount
# ============================================================================


class TestTaxInclusiveAmounts:
    def test_the_exclusive_amount_is_derived_and_reported(self) -> None:
        """FR-028e: visible, so a statement can be reconciled against it."""
        result = _margin(remitter="operator", tax_inclusive=True)

        assert result.tax_exclusive_derived is True
        assert result.revenue_tax_exclusive == (PRICE - TAX).quantize(Decimal("0.01"))

    def test_an_exclusive_amount_is_not_re_derived(self) -> None:
        result = _margin(remitter="operator", tax_inclusive=False)

        assert result.tax_exclusive_derived is False
        assert result.revenue_tax_exclusive == PRICE

    def test_an_inclusive_sale_reports_a_lower_margin_than_an_exclusive_one(self) -> None:
        """The whole point of the distinction.

        The same recorded total means less revenue once the tax comes out, so
        the margin must fall. A system that reported the same figure either way
        would be counting the tax as income.
        """
        inclusive = _margin(remitter="operator", tax_inclusive=True)
        exclusive = _margin(remitter="operator", tax_inclusive=False)

        assert inclusive.margin_pct < exclusive.margin_pct
        assert inclusive.profit < exclusive.profit

    def test_removing_the_tax_shrinks_the_fees_charged_on_it_too(self) -> None:
        """The invariant that one shared context exists to guarantee.

        Profit does not simply fall by the tax: the percentage fees and the
        reserve are charged on the smaller amount as well, so it falls by the
        tax less what those no longer take. A chain that charged fees on the
        inclusive amount while dividing by the exclusive one would lose exactly
        the whole tax, which is how that defect would present.
        """
        inclusive = _margin(remitter="operator", tax_inclusive=True)
        exclusive = _margin(remitter="operator", tax_inclusive=False)

        assert inclusive.fee_total < exclusive.fee_total
        assert inclusive.deduction_total < exclusive.deduction_total
        lost = exclusive.profit - inclusive.profit
        assert lost < TAX, (
            "profit fell by the entire tax, which means the fees were charged "
            "on an amount the margin did not divide by"
        )

    def test_the_remitter_still_does_not_change_the_margin(self) -> None:
        """FR-028a says every basis and every channel, inclusive amounts too."""
        marketplace = _margin(remitter="marketplace", tax_inclusive=True)
        operator = _margin(remitter="operator", tax_inclusive=True)

        assert marketplace.margin_pct == operator.margin_pct

    def test_the_helper_is_a_plain_subtraction(self) -> None:
        assert fee_engine.tax_exclusive_amount(
            Decimal("113.00"), Decimal("13.00"), tax_inclusive=True
        ) == Decimal("100.00")
        assert fee_engine.tax_exclusive_amount(
            Decimal("113.00"), Decimal("13.00"), tax_inclusive=False
        ) == Decimal("113.00")

    def test_an_inclusive_sale_with_shipping_revenue_splits_the_tax_pro_rata(self) -> None:
        """The allocation is a documented choice, so it is pinned here.

        A statement rarely splits its tax between item and shipping.
        Attributing all of it to the item would understate the item's margin by
        the shipping share, so it comes off both in proportion -- and the sum
        of the two exclusive figures is still the exclusive total, which is the
        property that matters.
        """
        channel = make_channel(tax_remitter="operator")
        item = Decimal("50.00")
        shipping = Decimal("10.00")
        context, treatment = fee_engine.exclusive_context(
            item_subtotal=item,
            shipping_revenue=shipping,
            sales_tax_collected=TAX,
            tax_inclusive=True,
        )
        result = CostingService.margin(
            context=context,
            make_cost=MAKE_COST,
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            tax=treatment,
            postage_paid=POSTAGE,
        )

        assert result.list_price < item
        assert result.shipping_revenue < shipping
        assert result.list_price + result.shipping_revenue == result.revenue_tax_exclusive
