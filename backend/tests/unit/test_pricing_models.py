"""Unit tests for SalesChannel.calculate_platform_fee and
ProductPricing.calculate_profit.

Rewritten for decimal returns (task T018).

Both methods previously took and returned `float`, and `calculate_profit`
converted the price to a float purely so it could call `calculate_platform_fee`
-- so a margin shown to the operator had passed through binary floating point
twice before reaching the screen. The old tests asserted with
`abs(result - expected) < 0.001`, a tolerance that existed only because the
arithmetic was inexact. With `Decimal` end to end the figures are exact, so the
assertions are exact too, and a tolerance reappearing here would mean a float
has crept back in (Constitution IV).

Uses SimpleNamespace + unbound method calls (no SQLAlchemy session needed).
"""

from decimal import Decimal
from types import SimpleNamespace

from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel

CENT = Decimal("0.01")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_channel(**kwargs):
    defaults = dict(fee_percentage=Decimal("0"), fee_fixed=Decimal("0"))
    channel = SimpleNamespace(**{**defaults, **kwargs})
    # Bind the real method so `pricing.sales_channel.calculate_platform_fee(...)`
    # exercises the implementation under test rather than a stand-in.
    channel.calculate_platform_fee = lambda price: SalesChannel.calculate_platform_fee(
        channel, price
    )
    return channel


def make_pricing(list_price, channel, **kwargs):
    return SimpleNamespace(list_price=Decimal(str(list_price)), sales_channel=channel, **kwargs)


# ---------------------------------------------------------------------------
# SalesChannel.calculate_platform_fee
# ---------------------------------------------------------------------------


class TestSalesChannelCalculatePlatformFee:
    def test_no_fees_returns_zero(self):
        channel = make_channel(fee_percentage=Decimal("0"), fee_fixed=Decimal("0"))
        assert SalesChannel.calculate_platform_fee(channel, Decimal("100")) == Decimal("0")

    def test_percentage_fee_only(self):
        price, pct = Decimal("100"), Decimal("5")
        channel = make_channel(fee_percentage=pct)
        assert SalesChannel.calculate_platform_fee(channel, price) == price * pct / Decimal("100")

    def test_fixed_fee_only(self):
        fixed = Decimal("0.20")
        channel = make_channel(fee_fixed=fixed)
        assert SalesChannel.calculate_platform_fee(channel, Decimal("100")) == fixed

    def test_both_fees_combined(self):
        price, pct, fixed = Decimal("50"), Decimal("6.5"), Decimal("0.30")
        channel = make_channel(fee_percentage=pct, fee_fixed=fixed)
        expected = price * pct / Decimal("100") + fixed
        assert SalesChannel.calculate_platform_fee(channel, price) == expected

    def test_etsy_like_fees(self):
        price, pct, fixed = Decimal("20"), Decimal("6.5"), Decimal("0.20")
        channel = make_channel(fee_percentage=pct, fee_fixed=fixed)
        expected = price * pct / Decimal("100") + fixed
        assert SalesChannel.calculate_platform_fee(channel, price) == expected

    def test_zero_list_price_still_charges_the_fixed_fee(self):
        fixed = Decimal("0.50")
        channel = make_channel(fee_percentage=Decimal("10"), fee_fixed=fixed)
        assert SalesChannel.calculate_platform_fee(channel, Decimal("0")) == fixed

    def test_high_percentage(self):
        price = Decimal("25")
        channel = make_channel(fee_percentage=Decimal("100"))
        assert SalesChannel.calculate_platform_fee(channel, price) == price

    def test_the_result_is_a_decimal(self):
        channel = make_channel(fee_percentage=Decimal("6.5"), fee_fixed=Decimal("0.20"))
        result = SalesChannel.calculate_platform_fee(channel, Decimal("64.99"))
        assert isinstance(result, Decimal), f"came back as {type(result).__name__}"

    def test_the_result_is_exact_not_approximate(self):
        """The old tests needed a 0.001 tolerance; this one needs none.

        6.5% of 0.07 is 0.00455 exactly. A float would land near it; a Decimal
        lands on it.
        """
        channel = make_channel(fee_percentage=Decimal("6.5"))
        assert SalesChannel.calculate_platform_fee(channel, Decimal("0.07")) == Decimal("0.00455")

    def test_it_does_not_round_so_a_caller_can_round_once(self):
        """Rounding here, then again downstream, is how a fee stack drifts."""
        channel = make_channel(fee_percentage=Decimal("6.5"))
        result = SalesChannel.calculate_platform_fee(channel, Decimal("33.33"))
        assert result == Decimal("33.33") * Decimal("6.5") / Decimal("100")
        assert result != result.quantize(CENT)

    def test_a_string_price_is_accepted_without_passing_through_a_float(self):
        """Values arrive from JSON as strings; none may become a float en route."""
        channel = make_channel(fee_percentage=Decimal("10"))
        assert SalesChannel.calculate_platform_fee(channel, "0.1") == Decimal("0.01")


# ---------------------------------------------------------------------------
# ProductPricing.calculate_profit
# ---------------------------------------------------------------------------


class TestProductPricingCalculateProfit:
    def test_basic_profit_no_fees(self):
        price, cost = Decimal("20.00"), Decimal("5.00")
        pricing = make_pricing(price, make_channel())
        result = ProductPricing.calculate_profit(pricing, make_cost=cost)

        assert result["list_price"] == price
        assert result["platform_fee"] == Decimal("0")
        assert result["net_revenue"] == price
        assert result["profit"] == price - cost
        assert result["margin_percentage"] == (price - cost) / price * Decimal("100")

    def test_with_percentage_fee(self):
        price, cost, pct = Decimal("100.00"), Decimal("30.00"), Decimal("10")
        pricing = make_pricing(price, make_channel(fee_percentage=pct))
        result = ProductPricing.calculate_profit(pricing, make_cost=cost)

        fee = price * pct / Decimal("100")
        assert result["platform_fee"] == fee
        assert result["net_revenue"] == price - fee
        assert result["profit"] == price - fee - cost

    def test_with_fixed_fee(self):
        price, cost, fixed = Decimal("10.00"), Decimal("3.00"), Decimal("0.50")
        pricing = make_pricing(price, make_channel(fee_fixed=fixed))
        result = ProductPricing.calculate_profit(pricing, make_cost=cost)

        assert result["platform_fee"] == fixed
        assert result["net_revenue"] == price - fixed
        assert result["profit"] == price - fixed - cost

    def test_negative_profit_when_cost_exceeds_revenue(self):
        price, cost = Decimal("5.00"), Decimal("10.00")
        pricing = make_pricing(price, make_channel())
        result = ProductPricing.calculate_profit(pricing, make_cost=cost)

        assert result["profit"] == price - cost
        assert result["profit"] < 0

    def test_zero_list_price_margin_is_zero(self):
        pricing = make_pricing(Decimal("0"), make_channel())
        result = ProductPricing.calculate_profit(pricing, make_cost=Decimal("0"))
        assert result["margin_percentage"] == Decimal("0")

    def test_result_contains_all_keys(self):
        pricing = make_pricing(Decimal("50.00"), make_channel(fee_percentage=Decimal("5")))
        result = ProductPricing.calculate_profit(pricing, make_cost=Decimal("10.00"))
        assert set(result.keys()) == {
            "list_price",
            "platform_fee",
            "net_revenue",
            "profit",
            "margin_percentage",
        }

    def test_every_figure_is_a_decimal(self):
        pricing = make_pricing(
            Decimal("64.99"),
            make_channel(fee_percentage=Decimal("6.5"), fee_fixed=Decimal("0.20")),
        )
        result = ProductPricing.calculate_profit(pricing, make_cost=Decimal("20.30"))
        for key, value in result.items():
            assert isinstance(value, Decimal), f"{key} came back as {type(value).__name__}"

    def test_the_golden_price_and_cost_give_an_exact_profit(self):
        """No tolerance: every step is exact.

        The figures are the golden case's price and the Tier 1 target make-cost.
        The margin here is the superseded single-percentage model, not the one
        the feature is building towards -- the point is only that it is exact.
        """
        price, cost = Decimal("64.99"), Decimal("20.30")
        pct, fixed = Decimal("6.5"), Decimal("0.20")
        pricing = make_pricing(price, make_channel(fee_percentage=pct, fee_fixed=fixed))
        result = ProductPricing.calculate_profit(pricing, make_cost=cost)

        fee = price * pct / Decimal("100") + fixed
        assert result["platform_fee"] == fee
        assert result["profit"] == price - fee - cost
        assert result["margin_percentage"] == (price - fee - cost) / price * Decimal("100")

    def test_no_fee_is_charged_on_another_fee(self):
        """A percentage is taken on the price, never on price-less-fixed-fee."""
        price = Decimal("100.00")
        pct, fixed = Decimal("10"), Decimal("5.00")
        pricing = make_pricing(price, make_channel(fee_percentage=pct, fee_fixed=fixed))
        result = ProductPricing.calculate_profit(pricing, make_cost=Decimal("0"))

        assert result["platform_fee"] == price * pct / Decimal("100") + fixed
        assert result["platform_fee"] != (price - fixed) * pct / Decimal("100") + fixed

    def test_it_reads_the_fee_through_the_channel_not_a_copy_of_it(self):
        """The margin must move when the channel's fee does.

        A margin computed from a stale copy of the fee structure is a stale
        figure served without error (Constitution V).
        """
        price, cost = Decimal("100.00"), Decimal("10.00")
        channel = make_channel(fee_percentage=Decimal("5"))
        pricing = make_pricing(price, channel)

        before = ProductPricing.calculate_profit(pricing, make_cost=cost)["profit"]
        channel.fee_percentage = Decimal("25")
        after = ProductPricing.calculate_profit(pricing, make_cost=cost)["profit"]

        assert after < before
        assert before - after == price * (Decimal("25") - Decimal("5")) / Decimal("100")

    def test_a_make_cost_given_as_a_string_stays_exact(self):
        price = Decimal("64.99")
        pricing = make_pricing(price, make_channel())
        result = ProductPricing.calculate_profit(pricing, make_cost="20.30")
        assert result["profit"] == price - Decimal("20.30")

    def test_it_does_not_round_so_a_caller_can_round_once(self):
        price, pct = Decimal("33.33"), Decimal("6.5")
        pricing = make_pricing(price, make_channel(fee_percentage=pct))
        result = ProductPricing.calculate_profit(pricing, make_cost=Decimal("10.00"))
        assert result["platform_fee"] == price * pct / Decimal("100")
        assert result["platform_fee"] != result["platform_fee"].quantize(CENT)


class TestTheseFiguresRemainSupersededByTierTwo:
    """What these two methods model, and what they do not.

    One percentage plus one fixed amount is not a marketplace fee stack: there
    is no cap, no floor, no per-listing or per-month charge, no shipping
    revenue, no tax treatment and no stated margin basis. Tier 2's fee engine
    (tasks T065, T070) replaces this, and `fee_percentage`/`fee_fixed` are
    dropped in T123 once no read path remains.

    These assertions describe the boundary so a reader is not misled into
    trusting the figure further than it goes.
    """

    def test_the_fee_has_no_cap(self):
        """A real marketplace fee often stops rising; this one never does."""
        channel = make_channel(fee_percentage=Decimal("6.5"))
        small = SalesChannel.calculate_platform_fee(channel, Decimal("10"))
        large = SalesChannel.calculate_platform_fee(channel, Decimal("10000"))
        assert large == small * 1000

    def test_the_margin_does_not_name_its_basis(self):
        pricing = make_pricing(Decimal("64.99"), make_channel())
        result = ProductPricing.calculate_profit(pricing, make_cost=Decimal("20.30"))
        assert "margin_basis" not in result

    def test_shipping_and_tax_are_absent_from_the_margin(self):
        pricing = make_pricing(Decimal("64.99"), make_channel())
        result = ProductPricing.calculate_profit(pricing, make_cost=Decimal("20.30"))
        assert "postage_paid" not in result
        assert "sales_tax_collected" not in result
