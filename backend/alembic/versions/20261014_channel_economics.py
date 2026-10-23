"""Effective-date the channel planning economics (task T136).

Revision ID: pricing_channel_economics_v1
Revises: pricing_drop_legacy_v1

Four figures moved out of ``sales_channels`` and into a dated table:
``expected_discount_pct``, ``expected_refund_pct``, ``free_shipping_threshold``
and ``rounding_rule``. Each is an operator decision (FR-002), and FR-003
requires a decision to be superseded rather than updated in place. While they
were columns, raising a refund reserve changed what every past plan said it had
reserved.

## Every existing channel keeps planning, from when it was created

The backfill writes one open period per channel from the channel's current
column values, dated from the channel's own ``created_at``. Dating them from
today would leave every quote and every settled line before today with no
economics in effect, and the resolver would fall back to the columns -- which
is the behaviour this migration exists to end.

A channel whose ``created_at`` is somehow null is dated from today: a period
with a real start that is too recent is recoverable by the operator, while a
null start would break the as-of read for that channel entirely.

## The columns stay, and that is deliberate

They are not dropped. The pure costing functions take a channel object and no
session, so a unit test or a scenario sweep can hand them a stand-in, and
``app/services/channel_economics.channel_defaults`` reads the columns as the
fallback for a channel with no period at all. After this migration no live
channel is in that state. Dropping them is a separate change, once nothing
constructs a channel-shaped object by hand.

## The downgrade loses the history, not the figures

``downgrade()`` copies each channel's *current* period back onto its columns
before dropping the table, so no planning figure changes. What goes is every
superseded period -- the record of what the channel used to be planned
against. That is irreversible; understand it before running it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "pricing_channel_economics_v1"
down_revision = "pricing_drop_legacy_v1"
branch_labels = None
depends_on = None

TABLE = "sales_channel_economics"

#: The figures that move. Named once so the backfill and the downgrade's
#: copy-back cannot disagree about which columns they are.
FIGURES = (
    "expected_discount_pct",
    "expected_refund_pct",
    "free_shipping_threshold",
    "rounding_rule",
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _enable_rls(table: str) -> None:
    """Tenant isolation at the database layer, as Constitution I requires.

    A no-op outside PostgreSQL: the test suite runs on SQLite, where RLS does
    not exist, and failing hard there would make the migration untestable
    rather than safe.
    """
    if not _is_postgres():
        return
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def _disable_rls(table: str) -> None:
    if not _is_postgres():
        return
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def _uuid_default() -> sa.sql.elements.TextClause | None:
    if _is_postgres():
        return sa.text("gen_random_uuid()")
    return None


def upgrade() -> None:
    is_postgres = _is_postgres()
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
            "sales_channel_id",
            uuid_type,
            sa.ForeignKey("sales_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "expected_discount_pct",
            sa.Numeric(7, 4),
            nullable=False,
            server_default="0",
            comment="Expected discount share, which reduces planned net revenue (FR-026)",
        ),
        sa.Column(
            "expected_refund_pct",
            sa.Numeric(7, 4),
            nullable=False,
            server_default="0",
            comment="Expected refund share, held as a reserve against revenue (FR-026)",
        ),
        sa.Column(
            "free_shipping_threshold",
            sa.Numeric(10, 2),
            nullable=True,
            comment="Order value at which shipping is free (FR-033)",
        ),
        sa.Column(
            "rounding_rule",
            sa.String(20),
            nullable=True,
            comment="How a solved price is rounded on this channel (FR-033)",
        ),
        sa.Column(
            "effective_from",
            sa.Date,
            nullable=False,
            comment="First day these figures applied",
        ),
        sa.Column(
            "effective_to",
            sa.Date,
            nullable=True,
            comment="Last day they applied; NULL means this is the current period",
        ),
        sa.Column(
            "set_by_user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment="Who set these figures (FR-012)",
        ),
        sa.Column("set_by_role", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_channel_economics_effective_range",
        ),
        sa.CheckConstraint(
            "expected_discount_pct >= 0 AND expected_discount_pct <= 100",
            name="ck_channel_economics_discount_is_a_percentage",
        ),
        sa.CheckConstraint(
            "expected_refund_pct >= 0 AND expected_refund_pct <= 100",
            name="ck_channel_economics_refund_is_a_percentage",
        ),
        sa.CheckConstraint(
            "free_shipping_threshold IS NULL OR free_shipping_threshold >= 0",
            name="ck_channel_economics_threshold_is_not_negative",
        ),
        comment=(
            "A channel's planning economics, one row per effective period "
            "(FR-003). Superseded, never updated in place"
        ),
    )

    op.create_index(f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"])
    op.create_index(f"ix_{TABLE}_sales_channel_id", TABLE, ["sales_channel_id"])
    op.create_index(
        "idx_channel_economics_channel_from", TABLE, ["sales_channel_id", "effective_from"]
    )
    # Exactly one current period per channel, said in the schema rather than
    # left to whoever writes the next update path.
    op.create_index(
        "uq_channel_economics_current",
        TABLE,
        ["sales_channel_id"],
        unique=True,
        postgresql_where=sa.text("effective_to IS NULL"),
        sqlite_where=sa.text("effective_to IS NULL"),
    )

    _backfill()
    _enable_rls(TABLE)


def _backfill() -> None:
    """One open period per existing channel, from its own current figures.

    Dated from the channel's ``created_at`` so that every quote and every
    settled line already in the database resolves to the figures it was planned
    against, rather than to nothing.
    """
    figures = ", ".join(FIGURES)
    uuid_expr = "gen_random_uuid()" if _is_postgres() else "lower(hex(randomblob(16)))"
    start = (
        "COALESCE(created_at::date, CURRENT_DATE)"
        if _is_postgres()
        else "COALESCE(date(created_at), date('now'))"
    )
    op.execute(
        f"""
        INSERT INTO {TABLE} (
            id, tenant_id, sales_channel_id, {figures},
            effective_from, effective_to, created_at, updated_at
        )
        SELECT
            {uuid_expr},
            tenant_id,
            id,
            COALESCE(expected_discount_pct, 0),
            COALESCE(expected_refund_pct, 0),
            free_shipping_threshold,
            rounding_rule,
            {start},
            NULL,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM sales_channels
        """
    )


def downgrade() -> None:
    """Copy each channel's current period back, then drop the history.

    No planning figure moves: the open period is written back onto the columns
    the resolver's fallback reads. Every superseded period is lost, so what a
    channel *used* to be planned against is gone for good.
    """
    assignments = ",\n            ".join(
        f"{figure} = (\n                SELECT e.{figure} FROM {TABLE} e\n"
        f"                WHERE e.sales_channel_id = sales_channels.id\n"
        f"                  AND e.effective_to IS NULL\n"
        f"                LIMIT 1\n            )"
        for figure in FIGURES
    )
    op.execute(
        f"""
        UPDATE sales_channels
        SET {assignments}
        WHERE EXISTS (
            SELECT 1 FROM {TABLE} e
            WHERE e.sales_channel_id = sales_channels.id
              AND e.effective_to IS NULL
        )
        """
    )

    _disable_rls(TABLE)
    op.drop_index("uq_channel_economics_current", table_name=TABLE)
    op.drop_index("idx_channel_economics_channel_from", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_sales_channel_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
