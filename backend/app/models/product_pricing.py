"""ProductPricing — one price, for one channel, over one period (task T094).

This table was a single current price per product and channel. FR-039 makes it
temporal: an order must report the price effective when it was placed, which a
table holding only the current figure cannot do. Changing a price therefore
closes the current row and opens a new one; nothing is updated in place.

**Why a partial unique index and not an exclusion constraint** (research D6): a
range exclusion constraint over `[valid_from, valid_to)` would be stricter, but
it needs the `btree_gist` extension, which this cluster has not declared. The
partial index covers the invariant that matters at read time — exactly one
current row per product, channel and quantity tier — and historical overlap is
rejected in `app.services.temporal_pricing` with a test, because a constraint
the database cannot express is still an invariant somebody has to keep.

**Quantity tiers** are part of the key rather than a separate table: a tier is
a price, and FR-039's as-of read has to resolve both at once. `min_quantity` is
the lower bound of a half-open tier, so the price at exactly a break quantity
is unambiguous — the tier whose `min_quantity` it reaches wins.
"""

import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    func,
    Integer,
    Numeric,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core import clock
from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.sales_channel import SalesChannel


class ProductPricing(Base, UUIDMixin, TimestampMixin):
    """
    Pricing for a Product on a specific Sales Channel, over an effective period.

    Each product can have different prices on different channels, different
    prices at different quantities, and a history of each. Platform fees are
    calculated from the channel's fee rules.
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

    # ------------------------------------------------------------------
    # The effective period (task T094, FR-039)
    # ------------------------------------------------------------------

    valid_from: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        # Defaults to today, which is what an operator means when they set a
        # price without naming a date: today's orders get the new figure and
        # yesterday's keep the old one (FR-039, mirrored in
        # `ProductPricingCreate`). Both sides are set: the Python default
        # covers an ORM insert, and the server default covers a plain SQL one
        # -- a row written without either would be refused by NOT NULL, which
        # is a confusing way to learn that a price needs a start date.
        default=clock.today,
        server_default=func.current_date(),
        comment="First day this price applied; backfilled from created_at",
    )

    valid_to: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        index=True,
        comment=(
            "Last day this price applied, or NULL for the price in effect now. "
            "Exactly one row per product, channel and tier may be NULL"
        ),
    )

    min_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment=(
            "Lower bound of the quantity tier this price applies from. The "
            "tier is half-open, so a price at exactly a break quantity is "
            "unambiguous: the highest tier the quantity reaches wins"
        ),
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="Whether this pricing is active (product listed on this channel)",
    )

    @property
    def is_current(self) -> bool:
        """Whether this is the row in effect now.

        Read off ``valid_to`` rather than compared against today's date: the
        partial unique index guarantees one open row per tier, and a row whose
        ``valid_to`` is in the future would otherwise read as two.
        """
        return self.valid_to is None

    def covers(self, on: date, *, quantity: int = 1) -> bool:
        """Whether this row priced ``quantity`` units on ``on``.

        Both bounds are inclusive, which is what makes a one-day price
        expressible: a row closed on the day it opened still priced that day's
        orders. Resolution across several matching rows belongs to
        :mod:`app.services.temporal_pricing`, not here.
        """
        if on < self.valid_from:
            return False
        if self.valid_to is not None and on > self.valid_to:
            return False
        return quantity >= self.min_quantity

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
    #
    # `uq_product_channel_pricing` is gone: it forbade exactly the history this
    # table now holds. What replaces it is narrower on purpose -- one *current*
    # row per product, channel and tier -- and the historical-overlap guard
    # lives in the service with its own test (research D6).
    __table_args__ = (
        Index(
            "uq_product_channel_tier_current",
            "product_id",
            "sales_channel_id",
            "min_quantity",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
        Index(
            "ix_product_pricing_as_of",
            "product_id",
            "sales_channel_id",
            "valid_from",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_product_pricing_period_ordered",
        ),
        CheckConstraint("min_quantity >= 1", name="ck_product_pricing_min_quantity_positive"),
        {"comment": "Product pricing per sales channel, per quantity tier, over time"},
    )

    def __repr__(self) -> str:
        period = f"{self.valid_from}..{self.valid_to or 'current'}"
        return (
            f"<ProductPricing(product_id={self.product_id}, "
            f"channel_id={self.sales_channel_id}, price={self.list_price}, "
            f"qty>={self.min_quantity}, {period})>"
        )
