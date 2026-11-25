"""`costing.margin_of`, the one derivation of a profit and a margin (task T221).

A quote, a settled line's planned margin, its realised margin and a channel
period all take their profit and percentage from this function. These cases
pin what each of its arguments does, so a fifth caller cannot need a fifth
copy.
"""

from decimal import Decimal

from app.services.costing import margin_of

D = Decimal


def _margin(**overrides):
    args = dict(
        item_price=D("40.00"),
        shipping_revenue=D("5.00"),
        fees=D("4.50"),
        make_cost=D("12.00"),
        postage_paid=D("3.50"),
        basis="customer_total",
    )
    args.update(overrides)
    return margin_of(**args)


class TestTheProfit:
    def test_is_revenue_less_fees_cost_and_postage(self) -> None:
        assert _margin().profit == D("25.00")

    def test_other_costs_reduce_the_profit_but_not_the_basis(self) -> None:
        plain = _margin()
        reserved = _margin(other_costs=D("2.25"))

        assert reserved.profit == plain.profit - D("2.25")
        assert reserved.basis_amount == plain.basis_amount

    def test_a_refund_comes_off_revenue(self) -> None:
        assert _margin(refund=D("10.00")).profit == D("15.00")

    def test_nothing_is_rounded(self) -> None:
        assert _margin(fees=D("4.5049")).profit == D("24.9951")


class TestTheBasis:
    def test_customer_total_is_everything_the_customer_paid(self) -> None:
        assert _margin().basis_amount == D("45.00")

    def test_item_price_excludes_shipping(self) -> None:
        assert _margin(basis="item_price").basis_amount == D("40.00")

    def test_net_revenue_is_after_fees(self) -> None:
        assert _margin(basis="net_revenue").basis_amount == D("40.50")

    def test_item_price_is_net_of_a_refund(self) -> None:
        assert _margin(basis="item_price", refund=D("10.00")).basis_amount == D("30.00")

    def test_customer_total_is_net_of_a_refund(self) -> None:
        assert _margin(refund=D("10.00")).basis_amount == D("35.00")


class TestThePercentage:
    def test_is_profit_over_the_basis(self) -> None:
        assert _margin().margin_pct == D("55.5556")

    def test_is_undefined_where_the_basis_is_nothing(self) -> None:
        figures = _margin(basis="net_revenue", fees=D("45.00"))

        assert figures.margin_pct is None

    def test_a_loss_is_a_negative_percentage_not_a_clamp(self) -> None:
        assert _margin(make_cost=D("60.00")).margin_pct < D("0")
