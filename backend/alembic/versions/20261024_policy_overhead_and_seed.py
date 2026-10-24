"""Give every tenant a policy row, and the overhead percentage a home in it.

Revision ID: pricing_policy_overhead_seed_v1
Revises: pricing_shipping_effective_to_v1

Two defects in one table (tasks T219 and T222):

* A tenant created after the Tier 1 migration had no policy row, so it was
  costed from a rate that existed nowhere. Such tenants are seeded a row here,
  dated from the tenant's creation, with no author -- which the engine reads as
  ``assumed``, not as a decision.
* The percentage overhead method read its percentage from the
  ``Tenant.settings`` blob, which nothing wrote and which carried no date. It
  becomes a dated policy lever. The blob's figure, where a tenant has one, is
  carried into each of that tenant's rows -- the blob applied throughout their
  history, so carrying it into the closed rows keeps every past cost where it
  was (FR-050).
"""

import sqlalchemy as sa

from alembic import op

revision = "pricing_policy_overhead_seed_v1"
down_revision = "pricing_shipping_effective_to_v1"
branch_labels = None
depends_on = None

TABLE = "tenant_pricing_policy"
CHECK = "check_policy_overhead_percentage_non_negative"


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"

    op.add_column(
        TABLE,
        sa.Column(
            "overhead_percentage",
            sa.Numeric(7, 4),
            nullable=False,
            server_default="0",
            comment="Overhead percentage of material and labor, for the percentage method (FR-014)",
        ),
    )
    op.create_check_constraint(CHECK, TABLE, "overhead_percentage >= 0")

    blob_sql = (
        "(tenants.settings ->> 'default_overhead_percentage')"
        if is_postgres
        else "json_extract(tenants.settings, '$.default_overhead_percentage')"
    )
    # Only a figure that reads as a non-negative number is carried; anything
    # else the old reader also ignored, falling back to zero.
    numeric_guard = (
        f"{blob_sql} ~ '^[0-9]+(\\.[0-9]+)?$'"
        if is_postgres
        else f"CAST({blob_sql} AS REAL) >= 0 AND {blob_sql} IS NOT NULL"
    )
    op.execute(
        f"""
        UPDATE {TABLE}
        SET overhead_percentage = (
            SELECT CAST({blob_sql} AS NUMERIC) FROM tenants
            WHERE tenants.id = {TABLE}.tenant_id
        )
        WHERE EXISTS (
            SELECT 1 FROM tenants
            WHERE tenants.id = {TABLE}.tenant_id AND {numeric_guard}
        )
        """
    )

    uuid_sql = "gen_random_uuid()" if is_postgres else "lower(hex(randomblob(16)))"
    overhead_sql = f"CASE WHEN {numeric_guard} THEN CAST({blob_sql} AS NUMERIC) ELSE 0 END"
    # The labour rate is POLICYLESS_LABOR_RATE, the figure such a tenant was
    # already being costed at; set_by_user_id stays NULL, so it reads assumed.
    op.execute(
        f"""
        INSERT INTO {TABLE} (
            id, tenant_id, print_labor_rate, finishing_labor_rate,
            overhead_method, overhead_percentage, margin_basis,
            effective_from, effective_to, created_at, updated_at
        )
        SELECT
            {uuid_sql}, tenants.id, 20.00, 20.00,
            'percentage', {overhead_sql}, 'customer_total',
            CAST(tenants.created_at AS DATE), NULL,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM tenants
        WHERE NOT EXISTS (
            SELECT 1 FROM {TABLE} WHERE {TABLE}.tenant_id = tenants.id
        )
        """
    )


def downgrade() -> None:
    # The seeded rows are left: they hold what those tenants were costed at.
    op.drop_constraint(CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "overhead_percentage")
