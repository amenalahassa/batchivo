"""The economics migration must not leave a channel unplanned (task T136).

The schema half of this migration fails loudly: a table that will not create
raises. The **backfill** fails quietly, and that is what this file is for. Get
it wrong and every channel still resolves -- through the legacy-column fallback
-- so nothing errors and nothing looks broken, while the history the migration
was written to create does not exist.

Two things are pinned:

* **A period per channel, dated from the channel's own creation.** Dating them
  from today would leave every quote and every settled line before today with
  no economics in effect, which is exactly the fallback the migration exists to
  end.
* **The figures carried over.** A backfill that zeroed a reserve would silently
  drop money from every past plan.

The downgrade is tested too, because it is the half that is normally written
and never run: it has to put the current period's figures back on the columns
before dropping the table, or a rollback would lose the operator's reserves.

Everything is synchronous, like the other migration suites and for the same
reason: a migration is synchronous, and psycopg's async mode cannot run on
Windows' default event loop, so an async version would only ever run in CI --
the opposite of what a data-migration check is for.
"""

import os
import uuid
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from tests.integration.migration_support import (
    alembic_against,
    database_named,
    sync_url,
)

REVISION = "pricing_channel_economics_v1"
PARENT = "pricing_drop_legacy_v1"

#: The figures the channel carries before the migration. Deliberately not the
#: table's defaults: a backfill that ignored the columns and inserted zeros
#: would pass against a channel that happened to hold zeros.
DISCOUNT = Decimal("3.5000")
REFUND = Decimal("2.2500")
THRESHOLD = Decimal("45.00")
ROUNDING = "psychological_99"

#: The channel's creation date, which the backfill must date the period from.
CREATED_ON = "2025-03-14"

#: What the operator changes the reserve to after the migration, so the
#: downgrade has a current period distinguishable from the backfilled one.
LATER_REFUND = Decimal("9.0000")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _is_postgres() -> bool:
    return "postgres" in _database_url()


pytestmark = pytest.mark.skipif(
    not _is_postgres(),
    reason=(
        "the economics migration's data path needs the PostgreSQL dialect "
        "(gen_random_uuid, RLS, partial indexes); set DATABASE_URL to a "
        "PostgreSQL instance to run it"
    ),
)


@pytest.fixture
def scratch_database():
    """A scratch database at the migration's parent, with a channel in it.

    The channel goes in *between* the upgrades: against an empty database the
    backfill is a no-op and proves nothing.
    """
    base_url = _database_url()
    scratch = f"chan_econ_{uuid.uuid4().hex[:10]}"
    admin_url = database_named(base_url, "postgres")
    scratch_url = database_named(base_url, scratch)

    admin = create_engine(sync_url(admin_url), isolation_level="AUTOCOMMIT")
    engine = None
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{scratch}"'))

        engine = create_engine(sync_url(scratch_url), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

        with alembic_against(scratch_url) as config:
            command.upgrade(config, PARENT)

        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, slug, is_active, settings,
                                         created_at, updated_at)
                    VALUES (gen_random_uuid(), 'Economics Tenant',
                            'economics-tenant', true, '{}'::jsonb, now(), now())
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sales_channels (
                        id, tenant_id, name, platform_type, monthly_cost,
                        tax_remitter, expected_discount_pct, expected_refund_pct,
                        free_shipping_threshold, rounding_rule, currency_code,
                        is_active, created_at, updated_at
                    )
                    SELECT gen_random_uuid(), tenants.id, 'Economics Channel',
                           'etsy', 0, 'operator', :discount, :refund,
                           :threshold, :rounding, 'CAD', true,
                           CAST(:created AS timestamptz), now()
                    FROM tenants WHERE tenants.slug = 'economics-tenant'
                    """
                ),
                {
                    "discount": DISCOUNT,
                    "refund": REFUND,
                    "threshold": THRESHOLD,
                    "rounding": ROUNDING,
                    "created": f"{CREATED_ON} 09:00+00",
                },
            )

        yield engine, scratch_url
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


def _periods(conn) -> list[dict]:
    row = conn.execute(
        text(
            """
            SELECT expected_discount_pct, expected_refund_pct,
                   free_shipping_threshold, rounding_rule,
                   effective_from, effective_to
            FROM sales_channel_economics
            ORDER BY effective_from
            """
        )
    ).mappings()
    return [dict(entry) for entry in row]


class TestTheBackfill:
    def test_every_channel_gets_one_open_period(self, scratch_database) -> None:
        engine, scratch_url = scratch_database

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        with engine.connect() as conn:
            periods = _periods(conn)

        assert len(periods) == 1
        assert periods[0]["effective_to"] is None

    def test_it_carries_the_channel_s_own_figures(self, scratch_database) -> None:
        engine, scratch_url = scratch_database

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        with engine.connect() as conn:
            period = _periods(conn)[0]

        assert period["expected_discount_pct"] == DISCOUNT
        assert period["expected_refund_pct"] == REFUND
        assert period["free_shipping_threshold"] == THRESHOLD
        assert period["rounding_rule"] == ROUNDING

    def test_the_period_starts_when_the_channel_did(self, scratch_database) -> None:
        # Dating from today would leave every order before today resolving to
        # nothing, which is the fallback this migration exists to end.
        engine, scratch_url = scratch_database

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        with engine.connect() as conn:
            period = _periods(conn)[0]

        assert str(period["effective_from"]) == CREATED_ON

    def test_the_columns_are_left_in_place(self, scratch_database) -> None:
        # They are the fallback the pure costing functions read, so the
        # migration must not drop them.
        engine, scratch_url = scratch_database

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        with engine.connect() as conn:
            remaining = conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'sales_channels'
                      AND column_name IN ('expected_discount_pct',
                                          'expected_refund_pct',
                                          'free_shipping_threshold',
                                          'rounding_rule')
                    """
                )
            ).scalars()
            assert len(list(remaining)) == 4

    def test_the_table_is_under_row_level_security(self, scratch_database) -> None:
        """Constitution I: isolation is enforced by the database, not by hope."""
        engine, scratch_url = scratch_database

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        with engine.connect() as conn:
            enabled = conn.execute(
                text(
                    "SELECT relrowsecurity FROM pg_class WHERE relname = 'sales_channel_economics'"
                )
            ).scalar()
            policies = conn.execute(
                text("SELECT count(*) FROM pg_policies WHERE tablename = 'sales_channel_economics'")
            ).scalar()

        assert enabled is True
        assert policies == 1

    def test_only_one_period_per_channel_may_be_open(self, scratch_database) -> None:
        engine, scratch_url = scratch_database

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        with engine.connect() as conn:
            channel_id = conn.execute(text("SELECT id FROM sales_channels")).scalar()
            tenant_id = conn.execute(text("SELECT tenant_id FROM sales_channels")).scalar()

            with pytest.raises(Exception):
                conn.execute(
                    text(
                        """
                        INSERT INTO sales_channel_economics (
                            id, tenant_id, sales_channel_id, expected_discount_pct,
                            expected_refund_pct, effective_from, effective_to,
                            created_at, updated_at
                        )
                        VALUES (gen_random_uuid(), :tenant, :channel, 0, 0,
                                CURRENT_DATE, NULL, now(), now())
                        """
                    ),
                    {"tenant": tenant_id, "channel": channel_id},
                )


class TestTheDowngrade:
    def test_it_puts_the_current_figures_back_on_the_columns(self, scratch_database) -> None:
        # Otherwise a rollback loses the operator's reserves: the table goes
        # and the columns still hold whatever they held before the upgrade.
        engine, scratch_url = scratch_database

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        with engine.connect() as conn:
            # The operator supersedes the backfilled period, exactly as the
            # write path would.
            conn.execute(
                text(
                    """
                    UPDATE sales_channel_economics
                    SET effective_to = CURRENT_DATE - 1
                    WHERE effective_to IS NULL
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sales_channel_economics (
                        id, tenant_id, sales_channel_id, expected_discount_pct,
                        expected_refund_pct, free_shipping_threshold,
                        rounding_rule, effective_from, effective_to,
                        created_at, updated_at
                    )
                    SELECT gen_random_uuid(), tenant_id, id, :discount, :refund,
                           :threshold, :rounding, CURRENT_DATE, NULL, now(), now()
                    FROM sales_channels
                    """
                ),
                {
                    "discount": DISCOUNT,
                    "refund": LATER_REFUND,
                    "threshold": THRESHOLD,
                    "rounding": ROUNDING,
                },
            )

        with alembic_against(scratch_url) as config:
            command.downgrade(config, PARENT)

        with engine.connect() as conn:
            restored = conn.execute(text("SELECT expected_refund_pct FROM sales_channels")).scalar()

        assert restored == LATER_REFUND

    def test_the_table_is_gone(self, scratch_database) -> None:
        engine, scratch_url = scratch_database

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)
            command.downgrade(config, PARENT)

        with engine.connect() as conn:
            present = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name = 'sales_channel_economics'"
                )
            ).scalar()

        assert present == 0
