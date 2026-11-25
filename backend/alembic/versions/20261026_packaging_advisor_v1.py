"""Packaging advisor, MVP: item dimensions, file measurement, packaging attributes.

Revision ID: packaging_advisor_v1
Revises: user_tenants_member_policy_v1

Feature 003 (research D1, D4, D5, D11). Every change is a nullable column (or
one boolean with a default), so no row changes and no computed figure moves:
- `models`, `products`, `product_variants`: length/width/height in mm with the
  source (`entered` | `measured`), the file measured and when they were set;
- `products.is_fragile`; `product_variants` packaging override;
- `model_files`: the bounding box measured from the file and its status;
- `consumable_types`: packaging kind, inner size, wall, empty weight, fill volume.

The tables already carry `tenant_id` under RLS; no new table is created.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "packaging_advisor_v1"
down_revision = "user_tenants_member_policy_v1"
branch_labels = None
depends_on = None

DIMENSION_TABLES = ("models", "products", "product_variants")


def _dimension_columns(table: str) -> None:
    op.add_column(table, sa.Column("length_mm", sa.Numeric(7, 1), nullable=True))
    op.add_column(table, sa.Column("width_mm", sa.Numeric(7, 1), nullable=True))
    op.add_column(table, sa.Column("height_mm", sa.Numeric(7, 1), nullable=True))
    op.add_column(table, sa.Column("dimensions_source", sa.String(10), nullable=True))
    op.add_column(
        table,
        sa.Column("dimensions_source_file_id", sa.Uuid(), nullable=True),
    )
    op.add_column(table, sa.Column("dimensions_set_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        f"fk_{table}_dims_source_file",
        table,
        "model_files",
        ["dimensions_source_file_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        f"ck_{table}_dims_all_or_none",
        table,
        "(length_mm IS NULL AND width_mm IS NULL AND height_mm IS NULL) OR "
        "(length_mm IS NOT NULL AND width_mm IS NOT NULL AND height_mm IS NOT NULL "
        "AND length_mm > 0 AND width_mm > 0 AND height_mm > 0)",
    )
    op.create_check_constraint(
        f"ck_{table}_dims_source",
        table,
        "(length_mm IS NULL AND dimensions_source IS NULL) OR "
        "(length_mm IS NOT NULL AND dimensions_source IN ('entered', 'measured'))",
    )


def _drop_dimension_columns(table: str) -> None:
    op.drop_constraint(f"ck_{table}_dims_source", table, type_="check")
    op.drop_constraint(f"ck_{table}_dims_all_or_none", table, type_="check")
    op.drop_constraint(f"fk_{table}_dims_source_file", table, type_="foreignkey")
    for column in (
        "dimensions_set_at",
        "dimensions_source_file_id",
        "dimensions_source",
        "height_mm",
        "width_mm",
        "length_mm",
    ):
        op.drop_column(table, column)


def upgrade() -> None:
    for table in DIMENSION_TABLES:
        _dimension_columns(table)

    op.add_column(
        "products",
        sa.Column("is_fragile", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.add_column(
        "product_variants",
        sa.Column("packaging_consumable_id", sa.Uuid(), nullable=True),
    )
    op.add_column("product_variants", sa.Column("packaging_quantity", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_product_variants_packaging_consumable",
        "product_variants",
        "consumable_types",
        ["packaging_consumable_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_product_variants_packaging_quantity",
        "product_variants",
        "packaging_quantity IS NULL OR packaging_quantity > 0",
    )

    op.add_column("model_files", sa.Column("measured_length_mm", sa.Numeric(7, 1)))
    op.add_column("model_files", sa.Column("measured_width_mm", sa.Numeric(7, 1)))
    op.add_column("model_files", sa.Column("measured_height_mm", sa.Numeric(7, 1)))
    op.add_column(
        "model_files",
        sa.Column("measured_objects", sa.JSON().with_variant(postgresql.JSONB(), "postgresql")),
    )
    op.add_column("model_files", sa.Column("measured_at", sa.DateTime(timezone=True)))
    op.add_column("model_files", sa.Column("measurement_note", sa.String(255)))
    op.add_column("model_files", sa.Column("measurement_status", sa.String(10)))
    op.create_check_constraint(
        "ck_model_files_measurement_status",
        "model_files",
        "measurement_status IS NULL OR "
        "measurement_status IN ('done', 'pending', 'skipped', 'failed')",
    )

    op.add_column("consumable_types", sa.Column("packaging_kind", sa.String(12)))
    op.add_column("consumable_types", sa.Column("inner_length_mm", sa.Numeric(7, 1)))
    op.add_column("consumable_types", sa.Column("inner_width_mm", sa.Numeric(7, 1)))
    op.add_column("consumable_types", sa.Column("inner_height_mm", sa.Numeric(7, 1)))
    op.add_column("consumable_types", sa.Column("wall_mm", sa.Numeric(5, 1)))
    op.add_column("consumable_types", sa.Column("empty_weight_grams", sa.Numeric(8, 1)))
    op.add_column("consumable_types", sa.Column("fill_volume_ml", sa.Numeric(10, 1)))
    op.create_check_constraint(
        "ck_consumable_types_packaging_kind",
        "consumable_types",
        "packaging_kind IS NULL OR packaging_kind IN ('box', 'mailer', 'void_fill', 'wrap')",
    )
    op.create_check_constraint(
        "ck_consumable_types_inner_dims",
        "consumable_types",
        "(inner_length_mm IS NULL AND inner_width_mm IS NULL AND inner_height_mm IS NULL)"
        " OR (inner_length_mm IS NOT NULL AND inner_width_mm IS NOT NULL"
        " AND inner_height_mm IS NOT NULL AND inner_length_mm > 0"
        " AND inner_width_mm > 0 AND inner_height_mm > 0)",
    )
    op.create_check_constraint(
        "ck_consumable_types_packaging_non_negative",
        "consumable_types",
        "(wall_mm IS NULL OR wall_mm >= 0)"
        " AND (empty_weight_grams IS NULL OR empty_weight_grams >= 0)"
        " AND (fill_volume_ml IS NULL OR fill_volume_ml >= 0)",
    )


def downgrade() -> None:
    for name in (
        "ck_consumable_types_packaging_non_negative",
        "ck_consumable_types_inner_dims",
        "ck_consumable_types_packaging_kind",
    ):
        op.drop_constraint(name, "consumable_types", type_="check")
    for column in (
        "fill_volume_ml",
        "empty_weight_grams",
        "wall_mm",
        "inner_height_mm",
        "inner_width_mm",
        "inner_length_mm",
        "packaging_kind",
    ):
        op.drop_column("consumable_types", column)

    op.drop_constraint("ck_model_files_measurement_status", "model_files", type_="check")
    for column in (
        "measurement_status",
        "measurement_note",
        "measured_at",
        "measured_objects",
        "measured_height_mm",
        "measured_width_mm",
        "measured_length_mm",
    ):
        op.drop_column("model_files", column)

    op.drop_constraint("ck_product_variants_packaging_quantity", "product_variants", type_="check")
    op.drop_constraint(
        "fk_product_variants_packaging_consumable", "product_variants", type_="foreignkey"
    )
    op.drop_column("product_variants", "packaging_quantity")
    op.drop_column("product_variants", "packaging_consumable_id")

    op.drop_column("products", "is_fragile")

    for table in reversed(DIMENSION_TABLES):
        _drop_dimension_columns(table)
