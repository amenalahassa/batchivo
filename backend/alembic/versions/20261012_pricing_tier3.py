"""Tier 3 of the pricing rebuild: snapshots, temporal prices, exchange rates.

Revision ID: pricing_tier3_v1
Revises: pricing_tier2_v1

What this migration is careful about, and why (task T099):

* **Every existing price keeps applying, from when it was set.**
  ``product_pricing.valid_from`` is backfilled from each row's ``created_at``
  date and ``valid_to`` is left null, so every existing row becomes the current
  period of its own history and every past order resolves to the figure it was
  actually charged (FR-039). Dating them from today would leave every
  historical order with no price in effect.

* **The constraint swap is the risky part, and it is ordered deliberately.**
  ``uq_product_channel_pricing`` forbade exactly the history this table now
  holds, so it goes -- but only *after* ``valid_to`` exists and is populated,
  because the partial unique index that replaces it is defined over that
  column. Between the two statements the table is briefly unconstrained, which
  is why both happen in one transaction.

* **The partial index, not an exclusion constraint.** One current row per
  product, channel and quantity tier. A range exclusion over
  ``[valid_from, valid_to)`` would be stricter but needs ``btree_gist``, an
  extension this cluster has not declared (research D6). Historical overlap is
  guarded in ``app/services/temporal_pricing.py`` with its own test.

* **Every snapshot column is nullable, and that is load-bearing.** Lines
  settled before this migration have no snapshot. They must read as *unknown*
  rather than as zero: a zero make-cost on a settled order is indistinguishable
  from a real one and would read as a sale with no cost of goods. Nothing is
  backfilled, deliberately -- a snapshot reconstructed from today's inputs
  would be precisely the restatement FR-037 forbids, and it would be
  indistinguishable from one frozen at the time.

* **``fx_rates`` carries no ``tenant_id``.** It is the one table in this
  feature outside the RLS rule, because a published exchange rate is not tenant
  data. The exception is argued at length in ``app/models/fx_rate.py``; it is
  called out here so a reader auditing RLS coverage finds the reasoning rather
  than an apparent omission. What *is* tenant data is the rate frozen onto
  ``order_items.fx_rate``, which sits on a tenant-scoped table under RLS.

* **``orders.postage_paid`` and ``sales_tax_collected`` already exist**, added
  by Tier 2. data-model.md lists them under Tier 3; they landed a tier early
  with the rest of the channel economics, so there is nothing to add here.

## The downgrade collapses price history

``downgrade()`` cannot restore ``uq_product_channel_pricing`` while several
periods exist for one product and channel, so it **deletes every superseded
row**, keeping only the current one, before restoring the constraint.

That is destructive and irreversible: the prices a past order was charged are
gone, and those orders will report today's figure instead. It is implemented
rather than left to fail because a downgrade that raises halfway has already
dropped the index and left the table in neither shape. Understand this before
ever running it (tasks.md notes it for the same reason).
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "pricing_tier3_v1"
down_revision = "pricing_tier2_v1"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _uuid_default() -> sa.sql.elements.TextClause | None:
    """``gen_random_uuid()`` on PostgreSQL, nothing on SQLite."""
    if _is_postgres():
        return sa.text("gen_random_uuid()")
    return None


def _json_type():
    """``JSONB`` on PostgreSQL, portable ``JSON`` on SQLite.

    The test suite runs on SQLite, where ``JSONB`` does not exist. A snapshot
    that could only be written in production would be a snapshot nothing tests.
    """
    return postgresql.JSONB() if _is_postgres() else sa.JSON()


def upgrade() -> None:
    is_postgres = _is_postgres()
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.Uuid()
    now = sa.func.now()

    # ------------------------------------------------------------------
    # order_items: the snapshot, written once at sale (FR-036, FR-037)
    # ------------------------------------------------------------------
    op.add_column(
        "order_items",
        sa.Column(
            "cost_breakdown_json",
            _json_type(),
            nullable=True,
            comment="The cost breakdown as it stood at sale; never recomputed",
        ),
    )
    op.add_column(
        "order_items",
        sa.Column("make_cost_at_sale", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("list_price_at_sale", sa.Numeric(10, 2), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "fees_json",
            _json_type(),
            nullable=True,
            comment="The itemised planned fees as the rules stood at sale",
        ),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "fx_rate",
            sa.Numeric(14, 8),
            nullable=True,
            comment="Frozen; never revised when a better rate becomes known (FR-028j)",
        ),
    )
    op.add_column(
        "order_items",
        sa.Column("margin_basis_at_sale", sa.String(20), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("pricing_rev", sa.Integer, nullable=True),
    )

    # ------------------------------------------------------------------
    # fx_rates — deliberately NOT tenant-scoped (see the module docstring)
    # ------------------------------------------------------------------
    op.create_table(
        "fx_rates",
        sa.Column("id", uuid_type, primary_key=True, server_default=_uuid_default()),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("rate_date", sa.Date, nullable=False),
        sa.Column("rate", sa.Numeric(14, 8), nullable=False),
        sa.Column("source", sa.String(10), nullable=False, server_default="service"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.UniqueConstraint(
            "base_currency",
            "quote_currency",
            "rate_date",
            "source",
            name="uq_fx_rate_pair_date_source",
        ),
        sa.CheckConstraint("rate > 0", name="ck_fx_rate_positive"),
        sa.CheckConstraint("source IN ('service', 'manual')", name="ck_fx_rate_source"),
        sa.CheckConstraint(
            "base_currency <> quote_currency", name="ck_fx_rate_pair_distinct"
        ),
        comment=(
            "Published exchange rates. Deliberately NOT tenant-scoped: a "
            "published rate is not tenant data. See app/models/fx_rate.py"
        ),
    )
    op.create_index(
        "ix_fx_rates_pair_date",
        "fx_rates",
        ["base_currency", "quote_currency", "rate_date"],
    )

    # ------------------------------------------------------------------
    # product_pricing: temporal, with quantity tiers (FR-039, research D6)
    # ------------------------------------------------------------------

    # Added nullable, backfilled, then made NOT NULL. Adding it NOT NULL with a
    # server default would stamp every existing row with today's date, losing
    # the one piece of history the table already held.
    op.add_column("product_pricing", sa.Column("valid_from", sa.Date, nullable=True))
    op.add_column("product_pricing", sa.Column("valid_to", sa.Date, nullable=True))
    op.add_column(
        "product_pricing",
        sa.Column("min_quantity", sa.Integer, nullable=False, server_default="1"),
    )

    # Every existing price becomes the current period of its own history,
    # starting the day it was created.
    if is_postgres:
        op.execute(
            "UPDATE product_pricing SET valid_from = created_at::date "
            "WHERE valid_from IS NULL"
        )
    else:
        op.execute(
            "UPDATE product_pricing SET valid_from = date(created_at) "
            "WHERE valid_from IS NULL"
        )
    # A row whose created_at was somehow null would block the NOT NULL below.
    op.execute(
        "UPDATE product_pricing SET valid_from = CURRENT_DATE WHERE valid_from IS NULL"
    )

    with op.batch_alter_table("product_pricing") as batch:
        # NOT NULL, with today as the server default. The default is not a
        # convenience: a price written without a start date would otherwise be
        # refused, which is a confusing way to learn that a price needs one,
        # and today is what an operator means when they do not say (FR-039).
        batch.alter_column(
            "valid_from",
            existing_type=sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        )

    # The swap. The old constraint forbade the history this table now holds, so
    # it goes -- but only now that `valid_to` exists, because the index that
    # replaces it is defined over that column.
    if is_postgres:
        op.execute(
            "ALTER TABLE product_pricing "
            "DROP CONSTRAINT IF EXISTS uq_product_channel_pricing"
        )
        op.execute(
            "CREATE UNIQUE INDEX uq_product_channel_tier_current "
            "ON product_pricing (product_id, sales_channel_id, min_quantity) "
            "WHERE valid_to IS NULL"
        )
    else:
        # SQLite names the unique constraint inline on the table, so it cannot
        # be dropped without rebuilding. The partial index is what enforces the
        # invariant that matters, and the test suite only needs that.
        op.execute(
            "CREATE UNIQUE INDEX uq_product_channel_tier_current "
            "ON product_pricing (product_id, sales_channel_id, min_quantity) "
            "WHERE valid_to IS NULL"
        )

    op.create_index(
        "ix_product_pricing_as_of",
        "product_pricing",
        ["product_id", "sales_channel_id", "valid_from"],
    )
    op.create_index("ix_product_pricing_valid_to", "product_pricing", ["valid_to"])


def downgrade() -> None:
    """Undo Tier 3, **collapsing price history to the current row**.

    Read the module docstring before running this. Every superseded price is
    deleted, which means every settled order stops reporting the price it was
    actually charged and starts reporting today's.
    """
    is_postgres = _is_postgres()

    op.drop_index("ix_product_pricing_valid_to", table_name="product_pricing")
    op.drop_index("ix_product_pricing_as_of", table_name="product_pricing")
    op.drop_index("uq_product_channel_tier_current", table_name="product_pricing")

    # Destructive, and the only way back to a one-row-per-channel table. The
    # current row of the base tier survives; everything else is discarded.
    op.execute("DELETE FROM product_pricing WHERE valid_to IS NOT NULL")
    op.execute("DELETE FROM product_pricing WHERE min_quantity > 1")

    with op.batch_alter_table("product_pricing") as batch:
        batch.drop_column("min_quantity")
        batch.drop_column("valid_to")
        batch.drop_column("valid_from")

    if is_postgres:
        op.create_unique_constraint(
            "uq_product_channel_pricing",
            "product_pricing",
            ["product_id", "sales_channel_id"],
        )

    op.drop_index("ix_fx_rates_pair_date", table_name="fx_rates")
    op.drop_table("fx_rates")

    with op.batch_alter_table("order_items") as batch:
        batch.drop_column("pricing_rev")
        batch.drop_column("margin_basis_at_sale")
        batch.drop_column("fx_rate")
        batch.drop_column("fees_json")
        batch.drop_column("list_price_at_sale")
        batch.drop_column("make_cost_at_sale")
        batch.drop_column("cost_breakdown_json")
