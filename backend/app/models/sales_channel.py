"""SalesChannel model for marketplace/selling platform tracking."""

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.fee_rule import FeeRule
    from app.models.product_pricing import ProductPricing
    from app.models.sales_channel_economics import SalesChannelEconomics


#: Who hands the sales tax to the revenue authority (FR-028b). It changes
#: nothing about margin -- tax is never revenue under either answer (FR-028c)
#: -- and everything about whether the operator owes a liability (FR-028d).
TAX_REMITTERS: tuple[str, ...] = ("marketplace", "operator")


class SalesChannel(Base, UUIDMixin, TimestampMixin):
    """
    Sales Channel represents where products are sold.

    Examples: Craft fairs, Etsy, eBay, Shopify store, direct sales
    Each channel can have different fee structures (percentage, fixed, or both).
    """

    __tablename__ = "sales_channels"

    # Tenant isolation
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    # Channel identification
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Channel name (e.g., 'Milton Keynes Craft Fair', 'Etsy Store')",
    )

    platform_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Platform type: fair, online_shop, shopify, ebay, etsy, amazon, other",
    )

    monthly_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
        server_default="0",
        comment="Monthly subscription/booth fee",
    )

    # ------------------------------------------------------------------
    # Channel economics (Tier 2)
    # ------------------------------------------------------------------
    tax_remitter: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default="operator",
        server_default="operator",
        comment="Who remits sales tax on this channel's sales: marketplace or operator (FR-028b)",
    )

    expected_discount_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment=(
            "Expected discount share, which reduces planned net revenue (FR-026). "
            "The authority for this figure is `sales_channel_economics`, one row per effective period (FR-003, task T136). This column is the fallback the pure costing functions read when a channel has no row -- a unit test's stand-in, or a channel created before the migration. Do not write it."
        ),
    )

    expected_refund_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment=(
            "Expected refund share, held as a reserve against planned revenue (FR-026). "
            "The authority for this figure is `sales_channel_economics`, one row per effective period (FR-003, task T136). This column is the fallback the pure costing functions read when a channel has no row -- a unit test's stand-in, or a channel created before the migration. Do not write it."
        ),
    )

    free_shipping_threshold: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment=(
            "Order value at which shipping is free; the solver may snap to it (FR-033). "
            "The authority for this figure is `sales_channel_economics`, one row per effective period (FR-003, task T136). This column is the fallback the pure costing functions read when a channel has no row -- a unit test's stand-in, or a channel created before the migration. Do not write it."
        ),
    )

    rounding_rule: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment=(
            "How a solved price is rounded on this channel, e.g. 'psychological_99' (FR-033). "
            "The authority for this figure is `sales_channel_economics`, one row per effective period (FR-003, task T136). This column is the fallback the pure costing functions read when a channel has no row -- a unit test's stand-in, or a channel created before the migration. Do not write it."
        ),
    )

    currency_code: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="GBP",
        server_default="GBP",
        comment="Channel display currency (FR-028)",
    )

    offsite_ads_opt_in: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether the operator opted into marketplace offsite advertising (FR-002)",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="Whether channel is active",
    )

    # Relationships
    fee_rules: Mapped[list["FeeRule"]] = relationship(
        "FeeRule",
        back_populates="sales_channel",
        cascade="all, delete-orphan",
        order_by="FeeRule.sort_order",
        lazy="select",
    )

    economics: Mapped[list["SalesChannelEconomics"]] = relationship(
        "SalesChannelEconomics",
        back_populates="sales_channel",
        cascade="all, delete-orphan",
        order_by="SalesChannelEconomics.effective_from",
        lazy="select",
    )

    pricing: Mapped[list["ProductPricing"]] = relationship(
        "ProductPricing",
        back_populates="sales_channel",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_sales_channel_tenant_name"),
        CheckConstraint(
            "platform_type IN ('fair', 'online_shop', 'shopify', 'ebay', 'etsy', 'amazon', 'other')",
            name="check_platform_type",
        ),
        CheckConstraint(
            "tax_remitter IN ('marketplace', 'operator')",
            name="check_sales_channel_tax_remitter",
        ),
        {"comment": "Sales channels/marketplaces with fee structures"},
    )

    def __repr__(self) -> str:
        return f"<SalesChannel(name={self.name}, platform={self.platform_type})>"
