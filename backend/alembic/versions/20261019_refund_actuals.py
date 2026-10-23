"""Record what a refund returned, so a realised margin can read it (task T189).

Revision ID: pricing_refund_actuals_v1
Revises: pricing_material_cost_numeric_v1

Nothing in this system recorded what a refund paid back against the order it
came from. The Square webhook set ``orders.status = 'REFUNDED'`` and wrote the
amount into a payment log; ``orders`` had no refund column; and
``return_requests.refund_amount`` is an RMA record the pricing engine never
read. So ``realised_margin`` took the order's full, un-reduced total as its
revenue, and a fully refunded order still reported the margin it earned at
sale -- SC-001 false by the whole refund, for a routine case.

What this migration is careful about:

* **Nothing existing is touched.** No column is added to ``orders``, nothing is
  retyped, and ``return_requests.refund_amount`` keeps its meaning. A refund is
  a later event with its own date, and reducing ``orders.total`` in place would
  restate the sale the snapshot was priced on (Constitution VI, FR-038).

* **No backfill.** There is no record anywhere of what past refunds returned --
  that is the defect -- and the amounts in the payment logs are provider JSON
  for payments, not a reliable per-order refund ledger. Inventing rows from
  them would put a guess into a table whose whole purpose is recorded fact
  (FR-019). Orders already marked ``REFUNDED`` therefore keep reporting their
  sale margin until an operator records the refund, which is the honest state:
  unknown, not zero.

* **A provider refund cannot be counted twice.** Square redelivers a webhook on
  any non-2xx response, so a partial unique index pins one row per
  ``provider_refund_id`` per tenant. It is partial because a human-entered
  refund has no provider id, and two of those on one order are legitimate.

The downgrade drops the table, which loses the recorded refunds -- there is
nowhere else they were being kept, which is the point.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "pricing_refund_actuals_v1"
down_revision = "pricing_material_cost_numeric_v1"
branch_labels = None
depends_on = None

TABLE = "refund_actuals"


def _enable_rls(table: str) -> None:
    """Tenant isolation at the database layer, as Constitution I requires.

    Guarded so the statement is a no-op outside PostgreSQL: the test suite runs
    on SQLite, where RLS does not exist, and a hard failure there would make
    the migration untestable rather than safe.
    """
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def _disable_rls(table: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def _uuid_default() -> sa.sql.elements.TextClause | None:
    """``gen_random_uuid()`` on PostgreSQL, nothing on SQLite."""
    if op.get_bind().dialect.name == "postgresql":
        return sa.text("gen_random_uuid()")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.Uuid()
    now = sa.func.now()

    op.create_table(
        TABLE,
        sa.Column("id", uuid_type, primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "tenant_id",
            uuid_type,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            uuid_type,
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="GBP"),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(12), nullable=False, server_default="entered"),
        sa.Column("provider_refund_id", sa.String(255), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "recorded_by_user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        # A refund of nothing is not a refund; a negative one is a sale.
        sa.CheckConstraint("amount > 0", name="check_refund_actual_amount_positive"),
        sa.CheckConstraint(
            "source IN ('entered', 'ingested')",
            name="check_refund_actual_source",
        ),
        comment="Refunds as they were actually paid back, per order (FR-040, SC-001)",
    )

    op.create_index(f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"])
    op.create_index(f"ix_{TABLE}_order_id", TABLE, ["order_id"])
    op.create_index(f"ix_{TABLE}_order", TABLE, ["tenant_id", "order_id"])

    # One row per provider refund, so a redelivered webhook records once.
    # Partial on PostgreSQL; SQLite honours the same clause, and the column
    # being NULL for an entered refund is what makes partial the right shape.
    op.create_index(
        f"uq_{TABLE}_provider_refund",
        TABLE,
        ["tenant_id", "provider_refund_id"],
        unique=True,
        postgresql_where=sa.text("provider_refund_id IS NOT NULL"),
        sqlite_where=sa.text("provider_refund_id IS NOT NULL"),
    )

    _enable_rls(TABLE)


def downgrade() -> None:
    _disable_rls(TABLE)
    op.drop_index(f"uq_{TABLE}_provider_refund", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_order", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_order_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
