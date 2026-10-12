"""ProductPricing model - pricing per product per sales channel."""

import uuid
from typing import TYPE_CHECKING
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.sales_channel import SalesChannel


class ProductPricing(Base, UUIDMixin, TimestampMixin):
    """
    Pricing for a Product on a specific Sales Channel.

    Each product can have different prices on different channels.
    Platform fees are calculated from the channel's fee structure.
    """

    __tablename__ = "product_pricing"

    # References
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Product being priced",
    )

    sales_channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sales_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Sales channel for this price",
    )

    # Pricing
    list_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Listed selling price",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="Whether this pricing is active (product listed on this channel)",
    )

    # Relationships
    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="pricing",
    )

    sales_channel: Mapped["SalesChannel"] = relationship(
        "SalesChannel",
        back_populates="pricing",
        lazy="joined",
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("product_id", "sales_channel_id", name="uq_product_channel_pricing"),
        {"comment": "Product pricing per sales channel"},
    )

    def __repr__(self) -> str:
        return f"<ProductPricing(product_id={self.product_id}, channel_id={self.sales_channel_id}, price={self.list_price})>"

    def calculate_profit(self, make_cost: Decimal) -> dict[str, Decimal]:
        """
        Calculate profit for this product on this channel.

        Every figure in and out is a `Decimal`. The previous version took and
        returned `float`, and converted the price to a float purely to call
        `calculate_platform_fee` -- so a margin shown to the operator had passed
        through binary floating point twice before it reached the screen
        (Constitution IV).

        Args:
            make_cost: Total cost to make the product

        Returns:
            dict of Decimals with:
            - list_price: What customer pays
            - platform_fee: Fee charged by platform
            - net_revenue: After platform fees
            - profit: Net revenue minus make cost
            - margin_percentage: Profit as % of list price

        Note:
            The margin here is taken on price and is tax-inclusive. Tier 2
            (tasks T071, T072) introduces the tax-exclusive margin and names the
            basis beside every percentage; until then a reader should not assume
            which basis this is.
        """
        list_price = Decimal(str(self.list_price))
        platform_fee = self.sales_channel.calculate_platform_fee(list_price)
        net_revenue = list_price - platform_fee
        make = Decimal(str(make_cost))
        profit = net_revenue - make

        margin_pct = (profit / list_price * Decimal("100")) if list_price > 0 else Decimal("0")

        return {
            "list_price": list_price,
            "platform_fee": platform_fee,
            "net_revenue": net_revenue,
            "profit": profit,
            "margin_percentage": margin_pct,
        }
