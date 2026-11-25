"""Packaging and postage catalogue columns.

Revision ID: catalogue_columns_v1
Revises: model_file_versions_v1
Create Date: 2026-11-04

Spec 006 (data-model.md). Every column is nullable and no row is written, so
every existing consumable, shipping profile and product costs exactly what it
did: the columns only identify rows the release step seeds later
(`python -m app.cli.seed_catalogues`), record a shop's optional country and a
product's optional postage service.

- `tenants.country_code` (ISO 3166-1 alpha-2) chooses the carrier.
- `consumable_types.catalogue_key` / `catalogue_version` identify seeded
  packaging; unique per tenant when set (partial index), so seeding twice
  creates nothing twice.
- `shipping_profiles.catalogue_carrier` / `service` / `tariff_version` /
  `source` identify seeded postage; a seeded row names its service and tariff.
- `products.postage_service` overrides the shop's default service.

Downgrade drops them: the values only identify seeded rows, which stay.
"""

import sqlalchemy as sa
from alembic import op

revision = "catalogue_columns_v1"
down_revision = "model_file_versions_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "country_code",
            sa.String(2),
            nullable=True,
            comment="ISO 3166-1 alpha-2 country of the shop; chooses the postage carrier",
        ),
    )
    op.create_check_constraint(
        "ck_tenants_country_code",
        "tenants",
        "country_code IS NULL OR country_code ~ '^[A-Z]{2}$'",
    )

    op.add_column(
        "consumable_types",
        sa.Column(
            "catalogue_key",
            sa.String(64),
            nullable=True,
            comment="Key of the packaging catalogue entry this row was seeded from",
        ),
    )
    op.add_column(
        "consumable_types",
        sa.Column(
            "catalogue_version",
            sa.Integer(),
            nullable=True,
            comment="Packaging catalogue version that seeded this row",
        ),
    )
    op.create_index(
        "uq_consumable_types_tenant_catalogue_key",
        "consumable_types",
        ["tenant_id", "catalogue_key"],
        unique=True,
        postgresql_where=sa.text("catalogue_key IS NOT NULL"),
    )

    op.add_column(
        "shipping_profiles",
        sa.Column(
            "catalogue_carrier",
            sa.String(32),
            nullable=True,
            comment="Carrier whose shipped tariff seeded this row; NULL for operator rows",
        ),
    )
    op.add_column(
        "shipping_profiles",
        sa.Column(
            "service",
            sa.String(64),
            nullable=True,
            comment="Service key within the carrier, e.g. small_packet",
        ),
    )
    op.add_column(
        "shipping_profiles",
        sa.Column(
            "tariff_version",
            sa.Date(),
            nullable=True,
            comment="Effective date of the tariff file that seeded this row",
        ),
    )
    op.add_column(
        "shipping_profiles",
        sa.Column(
            "source",
            sa.String(255),
            nullable=True,
            comment="Where the price came from (document title and date)",
        ),
    )
    op.create_index(
        "ix_shipping_profiles_tenant_carrier",
        "shipping_profiles",
        ["tenant_id", "catalogue_carrier", "tariff_version"],
    )
    op.create_check_constraint(
        "ck_shipping_profiles_catalogue_identity",
        "shipping_profiles",
        "catalogue_carrier IS NULL OR (service IS NOT NULL AND tariff_version IS NOT NULL)",
    )

    op.add_column(
        "products",
        sa.Column(
            "postage_service",
            sa.String(100),
            nullable=True,
            comment="Postage service override, '<carrier>:<service>'; NULL = shop default",
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "postage_service")

    op.drop_constraint(
        "ck_shipping_profiles_catalogue_identity", "shipping_profiles", type_="check"
    )
    op.drop_index("ix_shipping_profiles_tenant_carrier", table_name="shipping_profiles")
    for column in ("source", "tariff_version", "service", "catalogue_carrier"):
        op.drop_column("shipping_profiles", column)

    op.drop_index("uq_consumable_types_tenant_catalogue_key", table_name="consumable_types")
    op.drop_column("consumable_types", "catalogue_version")
    op.drop_column("consumable_types", "catalogue_key")

    op.drop_constraint("ck_tenants_country_code", "tenants", type_="check")
    op.drop_column("tenants", "country_code")
