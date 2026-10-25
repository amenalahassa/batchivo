"""Row-level security on the six tenant tables no earlier revision covered.

Revision ID: rls_uncovered_tenant_tables_v1
Revises: timestamptz_instants_v1

Bug product-variants-rls. `cffc14267961` and `8c3c671816d9` enumerated the
tenant tables by hand; these six carry `tenant_id` but were created later, or
outside Alembic (`product_variants`), and were never added. Each gets the same
isolation as the original list: RLS enabled and forced, one policy reading
`app.current_tenant_id`. Guarded with `to_regclass` so a database missing one
of the tables still migrates.

While `RLS_ENABLED` is off the application connects as the migration role,
which bypasses RLS, so this changes nothing until the flag is switched on.
"""

from alembic import op
from sqlalchemy import text

revision = "rls_uncovered_tenant_tables_v1"
down_revision = "timestamptz_instants_v1"
branch_labels = None
depends_on = None

TABLES = (
    "product_variants",
    "external_listings",
    "model_files",
    "order_items",
    "product_categories",
    "tenant_modules",
)

TENANT_MATCHES = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def _exists(table: str) -> bool:
    return bool(
        op.get_bind().execute(text(f"SELECT to_regclass('public.{table}') IS NOT NULL")).scalar()
    )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        if not _exists(table):
            continue
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({TENANT_MATCHES}) WITH CHECK ({TENANT_MATCHES})"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        if not _exists(table):
            continue
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
