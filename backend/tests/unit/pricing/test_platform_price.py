"""What a marketplace sync or export publishes as the price of one (task T274).

The Shopify sync published the first current row of any channel at any
quantity tier, and zero when there was none; the Etsy sync fell back to another
channel's listing; the product export read an arbitrary row of the history.
`platform_price` is the one read they now share.
"""

from decimal import Decimal
from types import SimpleNamespace

from app.services.temporal_pricing import platform_price


def _row(price: str, platform: str, *, min_quantity: int = 1, active: bool = True):
    return SimpleNamespace(
        list_price=Decimal(price),
        min_quantity=min_quantity,
        is_active=active,
        sales_channel=SimpleNamespace(platform_type=platform),
    )


def _product(*rows: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(current_pricing=list(rows))


class TestThePriceOfOne:
    def test_the_platforms_own_row_is_read(self) -> None:
        product = _product(_row("30.00", "fair"), _row("25.00", "shopify"))
        assert platform_price(product, "shopify") == Decimal("25.00")

    def test_a_quantity_tier_is_not_the_price_of_one(self) -> None:
        product = _product(_row("22.00", "shopify", min_quantity=10), _row("25.00", "shopify"))
        assert platform_price(product, "shopify") == Decimal("25.00")

    def test_a_quantity_reaching_the_tier_reads_the_tier(self) -> None:
        product = _product(_row("22.00", "shopify", min_quantity=10), _row("25.00", "shopify"))
        assert platform_price(product, "shopify", quantity=10) == Decimal("22.00")

    def test_an_inactive_listing_is_not_published(self) -> None:
        product = _product(_row("25.00", "etsy", active=False))
        assert platform_price(product, "etsy") is None


class TestUnpricedIsReportedNotSubstituted:
    def test_another_channels_price_is_not_borrowed(self) -> None:
        product = _product(_row("30.00", "fair"))
        assert platform_price(product, "etsy") is None

    def test_no_rows_at_all_is_unpriced(self) -> None:
        assert platform_price(_product(), "shopify") is None
