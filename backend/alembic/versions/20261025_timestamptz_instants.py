"""Store the last seven naive instant columns as timestamptz.

Revision ID: timestamptz_instants_v1
Revises: pricing_tenant_currency_prov_v1

Bug postgres-naive-datetime-writes. These columns were declared as a bare
`Mapped[datetime]`, which maps to `timestamp without time zone`, while every
writer stores `datetime.now(UTC)`. psycopg casts the aware value through the
session time zone, so a server whose `TimeZone` is not UTC shifts every stored
instant; asyncpg refuses it outright. Every value written so far was UTC, so
the conversion reads the existing naive values as UTC.
"""

from alembic import op

revision = "timestamptz_instants_v1"
down_revision = "pricing_tenant_currency_prov_v1"
branch_labels = None
depends_on = None

COLUMNS = (
    ("platform_admin_audit_logs", "created_at"),
    ("platform_settings", "updated_at"),
    ("webhook_subscriptions", "last_triggered_at"),
    ("webhook_subscriptions", "last_success_at"),
    ("webhook_deliveries", "next_retry_at"),
    ("webhook_deliveries", "completed_at"),
    ("external_listings", "last_synced_at"),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE timestamptz USING {column} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE timestamp USING {column} AT TIME ZONE 'UTC'"
        )
