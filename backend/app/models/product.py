"""Product model for sellable items (composed of one or more Models)."""

import uuid
from typing import TYPE_CHECKING, Optional
from decimal import Decimal

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeEngine


class TSVectorType(TypeDecorator):
    """
    A tsvector type that falls back to TEXT for non-PostgreSQL databases.

    This allows the model to work with both PostgreSQL (for FTS) and SQLite (for testing).
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect) -> TypeEngine:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import TSVECTOR

            return dialect.type_descriptor(TSVECTOR())
        else:
            # Fallback to TEXT for SQLite and other databases
            return dialect.type_descriptor(Text())


class StringArrayType(TypeDecorator):
    """
    A string array type that uses PostgreSQL ARRAY(String) in production
    and falls back to JSON for SQLite in tests.
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect) -> TypeEngine:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

            return dialect.type_descriptor(PG_ARRAY(String()))
        else:
            return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return [] if dialect.name != "postgresql" else value
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        return value


from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.consumable import ConsumableType
    from app.models.designer import Designer
    from app.models.external_listing import ExternalListing
    from app.models.print_job import PrintJob
    from app.models.product_component import ProductComponent
    from app.models.product_image import ProductImage
    from app.models.product_model import ProductModel
    from app.models.product_pricing import ProductPricing
    from app.models.product_variant import ProductVariant
    from app.models.production_run import ProductionRun
    from app.models.review import Review


class Product(Base, UUIDMixin, TimestampMixin):
    """
    Product represents a sellable item composed of one or more Models and/or other Products.

    A Product can be:
    - A single Model sold directly (e.g., "Dragon Body")
    - A composite of multiple Models (e.g., "Red Squirrel Set" = 26 models)
    - A bundle of other Products (e.g., "Mega Bundle" = Product A + Product B)
    - Any combination of Models and Products

    Products have their own pricing per sales channel and track packaged
    inventory separately from printed model inventory.

    Composite products (bundles) use ProductComponent to link to child products,
    while ProductModel links to individual printed Models.
    """

    __tablename__ = "products"

    # Tenant isolation
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    # Designer attribution
    designer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("designers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Designer who created this product's 3D model(s)",
    )

    # Product identification
    sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Stock Keeping Unit (unique per tenant)",
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Product name",
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Product description (can be rich text/HTML)",
    )

    # Inventory
    units_in_stock: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Packaged units ready to ship",
    )
    low_stock_threshold: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default="5",
        comment="Units-in-stock level at or below which a low-stock alert is raised",
    )

    # Packaging - can be manual cost or linked to consumable
    packaging_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=0,
        server_default="0",
        comment="Manual packaging cost per product (used if no consumable linked)",
    )

    packaging_consumable_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("consumable_types.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Optional consumable used for packaging (e.g., box)",
    )

    packaging_quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Quantity of packaging consumable per product",
    )

    assembly_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Time to assemble/package in minutes",
    )

    # Status
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="Whether product is active for sale",
    )

    # Shop visibility (separate from is_active for internal tracking)
    shop_visible: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Whether product appears in the online shop",
    )

    # Shop-specific description (can differ from internal description)
    shop_description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Rich HTML description for shop display (falls back to description if null)",
    )

    # Featured/showcase fields (for dragons, special editions)
    is_featured: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Whether product is featured in showcase/gallery",
    )

    # Dragon flag - separate from is_featured for shop dragon collection
    is_dragon: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        index=True,
        comment="Whether product appears in the Dragons collection",
    )

    # Print-to-order flag (made to order vs in-stock)
    print_to_order: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="Whether product is printed to order (vs in-stock ready to ship)",
    )

    # Shipping
    free_shipping: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="Whether product qualifies for free shipping",
    )

    feature_title: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Custom title for featured display (e.g., dragon name)",
    )

    backstory: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Backstory/lore for featured items (dragons, special editions)",
    )

    # Product specifications (for Etsy sync and display)
    weight_grams: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Product weight in grams (auto-captured from production run or manual)",
    )

    size_cm: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 1),
        nullable=True,
        comment="Product size/length in centimeters (manual entry)",
    )

    print_time_hours: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 2),
        nullable=True,
        comment="Print time in hours (auto-captured from production run or manual)",
    )

    # Review statistics (cached for performance)
    average_rating: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2),
        nullable=True,
        comment="Average review rating (1.00-5.00), null if no reviews",
    )
    review_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of approved reviews",
    )

    # Full-text search vector (PostgreSQL only, auto-updated by trigger)
    # Uses TSVectorType which falls back to TEXT for SQLite testing
    search_vector: Mapped[Optional[str]] = mapped_column(
        TSVectorType,
        nullable=True,
        comment="Full-text search vector (auto-populated by PostgreSQL trigger)",
    )

    # Multi-channel publishing fields
    tags: Mapped[Optional[list]] = mapped_column(
        StringArrayType,
        nullable=True,
        comment="Keyword tags for Shopify/Etsy discoverability",
    )

    product_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Product type / taxonomy (e.g. '3D Print') for Shopify product_type field",
    )

    seo_slug: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        index=True,
        comment="URL-friendly product handle for canonical URLs (auto-generated from name if null)",
    )

    seo_title: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="SEO meta title (≤60 chars); falls back to name",
    )

    seo_description: Mapped[Optional[str]] = mapped_column(
        String(300),
        nullable=True,
        comment="SEO meta description (≤155 chars); falls back to description truncated",
    )

    material: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Primary material (e.g. 'PLA', 'PETG') for Etsy/Shopify attributes",
    )

    colour_options: Mapped[Optional[list]] = mapped_column(
        StringArrayType,
        nullable=True,
        comment="Available filament colour options (e.g. ['Dragon Red', 'Bone White'])",
    )

    etsy_taxonomy_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Etsy taxonomy integer ID for product categorisation",
    )

    # Relationships
    product_models: Mapped[list["ProductModel"]] = relationship(
        "ProductModel",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    #: The **full price history**, every channel and every tier (FR-039).
    #:
    #: This used to be one row per channel, so every read of it was implicitly
    #: a read of the current price. Since Tier 3 it is a history, and a caller
    #: that still treats it as "the prices" will pick up superseded rows. Read
    #: `current_pricing` below for what is in effect now, or resolve as at a
    #: date through `app.services.temporal_pricing`.
    pricing: Mapped[list["ProductPricing"]] = relationship(
        "ProductPricing",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProductPricing.valid_from.desc()",
    )

    #: The prices **in effect now** — one per channel and quantity tier.
    #:
    #: Primary-joined on `valid_to IS NULL` (research D6), so the storefront
    #: and every other current-price read cannot accidentally serve a
    #: superseded figure. `viewonly` because this is a filtered view of
    #: `pricing`: writing through it would let two collections disagree about
    #: the same rows, and closing a period is the service's job.
    current_pricing: Mapped[list["ProductPricing"]] = relationship(
        "ProductPricing",
        primaryjoin=(
            "and_(Product.id == ProductPricing.product_id, "
            "ProductPricing.valid_to.is_(None))"
        ),
        viewonly=True,
        lazy="selectin",
        order_by="ProductPricing.min_quantity",
    )

    images: Mapped[list["ProductImage"]] = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ProductImage.display_order",
    )

    categories: Mapped[list["Category"]] = relationship(
        "Category",
        secondary="product_categories",
        back_populates="products",
        lazy="selectin",
    )

    packaging_consumable: Mapped[Optional["ConsumableType"]] = relationship(
        "ConsumableType",
        foreign_keys=[packaging_consumable_id],
        lazy="selectin",
    )

    # Composite product relationships (Product -> Product)
    # child_products: Products that this product contains (I am the parent/bundle)
    child_products: Mapped[list["ProductComponent"]] = relationship(
        "ProductComponent",
        foreign_keys="[ProductComponent.parent_product_id]",
        back_populates="parent_product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # parent_products: Products that contain this product (I am a child/component)
    parent_products: Mapped[list["ProductComponent"]] = relationship(
        "ProductComponent",
        foreign_keys="[ProductComponent.child_product_id]",
        back_populates="child_product",
        lazy="selectin",
    )

    # Production runs making this product
    production_runs: Mapped[list["ProductionRun"]] = relationship(
        "ProductionRun",
        back_populates="product",
        lazy="select",
    )

    # Designer relationship
    designer: Mapped[Optional["Designer"]] = relationship(
        "Designer",
        back_populates="products",
        lazy="selectin",
    )

    # Reviews
    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="noload",  # Don't auto-load reviews, use explicit query
    )

    # Print queue jobs
    print_jobs: Mapped[list["PrintJob"]] = relationship(
        "PrintJob",
        back_populates="product",
        lazy="select",
    )

    # External marketplace listings
    external_listings: Mapped[list["ExternalListing"]] = relationship(
        "ExternalListing",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Size variants (per-size pricing, stock, and fulfilment type)
    variants: Mapped[list["ProductVariant"]] = relationship(
        "ProductVariant",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductVariant.display_order",
        lazy="selectin",
    )

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_product_tenant_sku"),
        # GIN index for full-text search (PostgreSQL only)
        Index(
            "ix_products_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        {"comment": "Sellable products composed of one or more printed models"},
    )

    def __repr__(self) -> str:
        return f"<Product(sku={self.sku}, name={self.name})>"
