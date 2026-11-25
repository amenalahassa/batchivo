"""Packaging advisor, Phase 2: parcel-aware postage and confirmed parcels.

Revision ID: packaging_advisor_v2
Revises: packaging_advisor_v1

Feature 003 (research D8, D9, D10; data-model.md):
- `shipping_profiles`: size limits (all three or none) and a volumetric
  divisor, so a size class and chargeable weight can be priced;
- `order_parcels` / `order_parcel_items`: the parcels an operator confirmed at
  dispatch -- immutable records of what was sent, under RLS like every tenant
  table;
- `consumable_usage.order_id`: the packaging an order consumed.

Every change to an existing table is a nullable column, so no row changes and
no settled order's postage moves (FR-031).
"""

import sqlalchemy as sa
from alembic import op

revision = "packaging_advisor_v2"
down_revision = "packaging_advisor_v1"
branch_labels = None
depends_on = None

NEW_TENANT_TABLES = ("order_parcels", "order_parcel_items")
TENANT_MATCHES = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("shipping_profiles", sa.Column("max_length_mm", sa.Numeric(7, 1), nullable=True))
    op.add_column("shipping_profiles", sa.Column("max_width_mm", sa.Numeric(7, 1), nullable=True))
    op.add_column("shipping_profiles", sa.Column("max_height_mm", sa.Numeric(7, 1), nullable=True))
    op.add_column(
        "shipping_profiles", sa.Column("volumetric_divisor", sa.Numeric(8, 1), nullable=True)
    )
    op.create_check_constraint(
        "ck_shipping_profiles_size_limits",
        "shipping_profiles",
        "(max_length_mm IS NULL AND max_width_mm IS NULL AND max_height_mm IS NULL)"
        " OR (max_length_mm IS NOT NULL AND max_width_mm IS NOT NULL"
        " AND max_height_mm IS NOT NULL"
        " AND max_length_mm > 0 AND max_width_mm > 0 AND max_height_mm > 0)",
    )
    op.create_check_constraint(
        "ck_shipping_profiles_volumetric_divisor",
        "shipping_profiles",
        "volumetric_divisor IS NULL OR volumetric_divisor > 0",
    )

    op.create_table(
        "order_parcels",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("outer_length_mm", sa.Numeric(7, 1), nullable=True),
        sa.Column("outer_width_mm", sa.Numeric(7, 1), nullable=True),
        sa.Column("outer_height_mm", sa.Numeric(7, 1), nullable=True),
        sa.Column("packed_weight_grams", sa.Numeric(10, 1), nullable=True),
        sa.Column(
            "confirmed_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", "sequence", name="uq_order_parcels_order_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_order_parcels_sequence_positive"),
    )
    op.create_table(
        "order_parcel_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "order_parcel_id",
            sa.Uuid(),
            sa.ForeignKey("order_parcels.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "consumable_type_id",
            sa.Uuid(),
            sa.ForeignKey("consumable_types.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_parcel_items_quantity_positive"),
    )

    op.add_column(
        "consumable_usage",
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.id", ondelete="SET NULL", name="fk_consumable_usage_order"),
            nullable=True,
        ),
    )
    op.create_index("ix_consumable_usage_order_id", "consumable_usage", ["order_id"])

    if op.get_bind().dialect.name == "postgresql":
        for table in NEW_TENANT_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                f"USING ({TENANT_MATCHES}) WITH CHECK ({TENANT_MATCHES})"
            )


def downgrade() -> None:
    op.drop_index("ix_consumable_usage_order_id", table_name="consumable_usage")
    op.drop_constraint("fk_consumable_usage_order", "consumable_usage", type_="foreignkey")
    op.drop_column("consumable_usage", "order_id")

    # Dropping the tables drops their policies with them.
    op.drop_table("order_parcel_items")
    op.drop_table("order_parcels")

    op.drop_constraint(
        "ck_shipping_profiles_volumetric_divisor", "shipping_profiles", type_="check"
    )
    op.drop_constraint("ck_shipping_profiles_size_limits", "shipping_profiles", type_="check")
    for column in ("volumetric_divisor", "max_height_mm", "max_width_mm", "max_length_mm"):
        op.drop_column("shipping_profiles", column)
