"""Create product_variants where no migration ever did.

The table arrived with the size-variants feature, but no revision creates it:
``a0b1c2d3e4f5`` and ``f0g1h2i3j4k5`` only alter it *if it exists*. A database
built from migrations alone -- CI's end-to-end stage, a new environment, a
disaster-recovery restore of the schema -- has no such table, and the product
list fails on its first request with ``relation "product_variants" does not
exist``.

This creates it, exactly as the existing environments have it, where it is
missing, and does nothing where it is already there.

Revision ID: create_product_variants_v1
Revises: pricing_estimate_confidence_v1
"""

import sqlalchemy as sa
from alembic import op

revision = "create_product_variants_v1"
down_revision = "pricing_estimate_confidence_v1"
branch_labels = None
depends_on = None


def _exists() -> bool:
    return bool(
        op.get_bind()
        .execute(sa.text("SELECT to_regclass('public.product_variants') IS NOT NULL"))
        .scalar()
    )


def upgrade() -> None:
    if _exists():
        return
    op.create_table(
        "product_variants",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("size", sa.String(50), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(120), nullable=False),
        sa.Column("price_adjustment_pence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("units_in_stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fulfilment_type", sa.String(20), nullable=False, server_default="stock"),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
        sa.Column("material_cost_pence", sa.Integer(), nullable=True),
        sa.Column("print_time_hours", sa.Numeric(6, 2), nullable=True),
        sa.Column("yarn_requirements", sa.JSON(), nullable=True),
        sa.Column("make_cost_override_pence", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="product_variants_pkey"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="product_variants_product_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="product_variants_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("product_id", "size", name="uq_variant_product_size"),
        sa.UniqueConstraint("product_id", "sku", name="uq_variant_product_sku"),
    )
    op.create_index("ix_product_variants_product_id", "product_variants", ["product_id"])
    op.create_index("ix_product_variants_sku", "product_variants", ["sku"])
    op.create_index("ix_product_variants_tenant_id", "product_variants", ["tenant_id"])


def downgrade() -> None:
    # Deliberately nothing: on every environment that had the table before
    # this revision, dropping it here would destroy data this revision never
    # created. A fresh database rolled back past here keeps an empty table.
    pass
