"""Order model for tracking customer orders from sales channels."""

import uuid
from typing import TYPE_CHECKING, Optional
from decimal import Decimal
from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, Numeric, String, Text, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.sales_channel import SalesChannel
    from app.models.product import Product
    from app.models.customer import Customer


class OrderStatus:
    """Order status constants."""

    PENDING = "pending"  # Payment received, awaiting processing
    PROCESSING = "processing"  # Being prepared/printed
    SHIPPED = "shipped"  # Dispatched to customer
    DELIVERED = "delivered"  # Confirmed delivered
    CANCELLED = "cancelled"  # Order cancelled
    REFUNDED = "refunded"  # Payment refunded


class Order(Base, UUIDMixin, TimestampMixin):
    """
    Order represents a customer purchase from a sales channel.

    Stores order details, customer info, shipping address, and payment info.
    Links to OrderItems for individual line items.
    """

    __tablename__ = "orders"

    # Tenant isolation
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    # Order identification
    order_number: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="Human-readable order number (e.g., MF-20251210-001)",
    )

    # Sales channel reference
    sales_channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sales_channels.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Sales channel this order came from",
    )

    # Customer reference (optional - for logged-in customers)
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Customer account if logged in during purchase",
    )

    # Order status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=OrderStatus.PENDING,
        index=True,
        comment="Order status: pending, processing, shipped, delivered, cancelled, refunded",
    )

    # Customer information
    customer_email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Customer email address",
    )
    customer_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Customer full name",
    )
    customer_phone: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Customer phone number",
    )

    # Shipping address
    shipping_address_line1: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Shipping address line 1",
    )
    shipping_address_line2: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Shipping address line 2",
    )
    shipping_city: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Shipping city",
    )
    shipping_county: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Shipping county/state",
    )
    shipping_postcode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Shipping postcode",
    )
    shipping_country: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="United Kingdom",
        comment="Shipping country",
    )

    # Shipping method
    shipping_method: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Shipping method (e.g., Royal Mail 2nd Class)",
    )
    shipping_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment=(
            "Shipping REVENUE charged to the customer -- not postage paid. "
            "See postage_paid below; FR-024 keeps the two apart"
        ),
    )

    # ------------------------------------------------------------------
    # What the operator actually paid and actually owes (Tier 2)
    #
    # `shipping_cost` above is revenue: what the customer was charged. It was
    # the only shipping figure the system held, which is why free shipping
    # looked free. These two are the other side of that sale.
    # ------------------------------------------------------------------
    postage_paid: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0",
        comment="What the operator paid to post this order; a cost, never netted off revenue",
    )

    sales_tax_collected: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0",
        comment=(
            "Sales tax taken from the customer. A liability where the operator "
            "remits it, and never revenue or profit under either remitter (FR-028c, FR-028d)"
        ),
    )

    # Order totals
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Order subtotal before shipping",
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Order total including shipping",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="GBP",
        comment="Currency code",
    )

    # Discount applied
    discount_code: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Discount code used (stored for reference)",
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment="Discount amount applied to this order",
    )

    # Payment information
    payment_provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="square",
        comment="Payment provider (square, stripe, etc.)",
    )
    payment_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Payment provider transaction ID",
    )
    payment_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="completed",
        comment="Payment status from provider",
    )

    # Tracking
    tracking_number: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Shipping tracking number",
    )
    tracking_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Tracking URL",
    )
    shipped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the order was shipped",
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the order was delivered",
    )

    # Fulfillment (inventory deducted)
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When inventory was deducted for this order",
    )

    # Email tracking
    confirmation_email_sent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether order confirmation email was sent successfully",
    )
    confirmation_email_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When confirmation email was sent",
    )
    shipped_email_sent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether shipped notification email was sent successfully",
    )
    shipped_email_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When shipped email was sent",
    )
    delivered_email_sent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether delivered notification email was sent successfully",
    )
    delivered_email_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When delivered email was sent",
    )

    # Notes
    customer_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Notes from customer",
    )
    internal_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Internal notes for staff",
    )

    # Relationships
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    sales_channel: Mapped[Optional["SalesChannel"]] = relationship(
        "SalesChannel",
        lazy="selectin",
    )
    customer: Mapped[Optional["Customer"]] = relationship(
        "Customer",
        back_populates="orders",
        lazy="noload",
    )


class OrderItem(Base, UUIDMixin, TimestampMixin):
    """
    OrderItem represents a single line item in an order.

    Links to Product for inventory tracking and stores the
    price at time of purchase (which may differ from current price).
    """

    __tablename__ = "order_items"

    # Tenant isolation (denormalized from Order for RLS and direct queries)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    # Order reference
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Parent order ID",
    )

    # Product reference (nullable for products that may be deleted)
    product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Product ID (may be null if product deleted)",
    )

    # Product snapshot (stored at time of order)
    product_sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Product SKU at time of order",
    )
    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Product name at time of order",
    )

    # Quantity and pricing
    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="Quantity ordered",
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Price per unit at time of order",
    )
    total_price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        comment="Total line item price (quantity * unit_price)",
    )

    # ------------------------------------------------------------------
    # The snapshot, written once at the moment of sale (task T093)
    #
    # FR-036 and FR-037 together: what a line earned is recorded as it stood
    # and then never recomputed. Everything above this block is already a
    # snapshot of a kind -- `product_sku` and `unit_price` have always been
    # frozen -- and these columns extend that discipline to the figures the
    # margin is built from.
    #
    # Why this matters enough to be a table rather than a recomputation: a
    # settled order's margin is a historical fact. Recomputing it from today's
    # spool price, today's labor rate and today's fee rules would silently
    # restate last quarter's profit every time an input moved, which is the
    # defect FR-038 exists to prevent and `tests/integration/
    # test_snapshot_immutability.py` asserts the absence of.
    #
    # Every column is nullable: lines settled before this feature have no
    # snapshot and must read as *unknown* rather than as zero. A zero margin on
    # a historical order is indistinguishable from a real one.
    # ------------------------------------------------------------------

    cost_breakdown_json: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
        comment=(
            "The full cost breakdown as it stood at the moment of sale. "
            "Written once and never recomputed (FR-036, FR-037)"
        ),
    )

    make_cost_at_sale: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment="Make-cost of one unit as it stood at the moment of sale",
    )

    list_price_at_sale: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        comment=(
            "The channel list price in effect at the moment of sale. Distinct "
            "from unit_price, which is what was actually charged after any "
            "discount -- the two differing is information, not an error"
        ),
    )

    fees_json: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
        comment=(
            "The itemised PLANNED fees as the rules stood at sale. Recorded "
            "actuals are reconciled against these, never written back over them"
        ),
    )

    fx_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 8),
        nullable=True,
        comment=(
            "The exchange rate used, frozen. Never revised when a newer or "
            "more accurate rate becomes known (FR-028j); the difference is "
            "reported as a variance, not corrected"
        ),
    )

    margin_basis_at_sale: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment=(
            "The margin basis in effect at sale, so the order keeps reporting "
            "on the basis it sold on after the setting changes (FR-031d)"
        ),
    )

    pricing_rev: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment=(
            "Revision of the cost engine that produced this snapshot, so a "
            "figure can be attributed to the arithmetic that made it"
        ),
    )

    @property
    def has_snapshot(self) -> bool:
        """Whether this line carries a snapshot at all.

        A line settled before this feature has none. Callers must branch on
        this rather than reading ``make_cost_at_sale or 0`` -- an unrecorded
        cost and a cost of nothing are different facts, and the second reads
        as a sale with no cost of goods at all.
        """
        return self.make_cost_at_sale is not None

    # Relationships
    order: Mapped["Order"] = relationship(
        "Order",
        back_populates="items",
    )
    product: Mapped[Optional["Product"]] = relationship(
        "Product",
        lazy="selectin",
    )
