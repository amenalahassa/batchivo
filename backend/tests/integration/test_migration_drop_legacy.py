"""Dropping the superseded inputs must take only those (task T123).

The schema part fails loudly: a column that will not drop raises. The data part
fails quietly, and in two directions. Strip the wrong key and an operator loses
a setting nobody notices until a screen reads it; leave the key behind and the
drop did not happen, while the migration reports success either way.

The first version of this migration failed against a real database for a third
reason worth pinning: `tenants.settings` is declared `JSONB` on the model but
created as `json`, and `-` and `?` are jsonb operators that simply do not exist
for `json`. A statement written for one type errors outright against the other,
so the casts are tested here rather than assumed.

Everything is synchronous, like the Tier 1 and Tier 2 migration suites and for
the same reason: a migration is synchronous, and psycopg's async mode cannot
run on Windows' default event loop, so an async version of this would only ever
run in CI -- the opposite of what a data-migration check is for.
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

REVISION = "pricing_drop_legacy_v1"
PARENT = "pricing_tier4b_v1"

#: The rate sitting in the settings blob, and the one in the policy row that
#: superseded it. Deliberately different: if the downgrade restored the blob's
#: own figure it would be restoring a value it could not have known, and if the
#: upgrade read the blob at all it would be reading a figure nothing uses.
BLOB_LABOR_RATE = Decimal("17.25")
POLICY_LABOR_RATE = Decimal("31.50")

#: A key beside the rate, to prove the statement removes one key and not the
#: whole blob.
KEPT_SETTINGS_KEY = "currency"
KEPT_SETTINGS_VALUE = "CAD"

LEGACY_FEE_PERCENTAGE = Decimal("6.50")
LEGACY_FEE_FIXED = Decimal("0.20")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _is_postgres() -> bool:
    return "postgres" in _database_url()


pytestmark = pytest.mark.skipif(
    not _is_postgres(),
    reason=(
        "the drop migration's data path needs the PostgreSQL dialect (jsonb "
        "operators, RLS); set DATABASE_URL to a PostgreSQL instance to run it"
    ),
)


@pytest.fixture
def scratch_database():
    """A scratch database at the drop migration's parent, with data in it.

    One tenant with the legacy key and a policy row that superseded it, and one
    channel with the blended pair plus the two fee rules the Tier 2 migration
    would have converted it into. The data goes in *between* the upgrades:
    against an empty database every statement under test is a no-op and proves
    nothing.
    """
    base_url = _database_url()
    scratch = f"drop_legacy_{uuid.uuid4().hex[:10]}"
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
                    VALUES (gen_random_uuid(), 'Drop Tenant', 'drop-tenant', true,
                            CAST(:settings AS JSONB), now(), now())
                    """
                ),
                {
                    "settings": (
                        f'{{"default_labor_rate": {BLOB_LABOR_RATE}, '
                        f'"{KEPT_SETTINGS_KEY}": "{KEPT_SETTINGS_VALUE}"}}'
                    )
                },
            )
            # The policy row, written by hand. The Tier 1 migration seeds one
            # per tenant, but it ran before this tenant existed -- the data
            # here goes in between the upgrades on purpose -- so the row a
            # real tenant would already have is inserted explicitly. Its rate
            # is what the downgrade has to restore.
            conn.execute(
                text(
                    """
                    INSERT INTO tenant_pricing_policy (
                        id, tenant_id, print_labor_rate, finishing_labor_rate,
                        overhead_method, margin_basis, effective_from, effective_to,
                        created_at, updated_at
                    )
                    SELECT gen_random_uuid(), tenants.id, :rate, :rate,
                           'percentage', 'customer_total', DATE '2024-01-01', NULL,
                           now(), now()
                    FROM tenants WHERE tenants.slug = 'drop-tenant'
                    """
                ),
                {"rate": POLICY_LABOR_RATE},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO sales_channels (id, tenant_id, name, platform_type,
                                                fee_percentage, fee_fixed, monthly_cost,
                                                is_active, created_at, updated_at)
                    SELECT gen_random_uuid(), tenants.id, 'Drop Channel', 'etsy',
                           :pct, :fixed, 0, true, now(), now()
                    FROM tenants WHERE tenants.slug = 'drop-tenant'
                    """
                ),
                {"pct": LEGACY_FEE_PERCENTAGE, "fixed": LEGACY_FEE_FIXED},
            )
            for name, basis, pct, fixed, order in (
                ("platform_percentage", "item_plus_shipping", LEGACY_FEE_PERCENTAGE, 0, 10),
                ("platform_fixed", "per_order", 0, LEGACY_FEE_FIXED, 20),
            ):
                conn.execute(
                    text(
                        """
                        INSERT INTO fee_rules (id, tenant_id, sales_channel_id, name,
                                               basis, rate_pct, fixed_amount, sort_order,
                                               applies_from, created_at, updated_at)
                        SELECT gen_random_uuid(), sales_channels.tenant_id,
                               sales_channels.id, :name, :basis, :pct, :fixed, :order,
                               DATE '2020-01-01', now(), now()
                        FROM sales_channels WHERE sales_channels.name = 'Drop Channel'
                        """
                    ),
                    {"name": name, "basis": basis, "pct": pct, "fixed": fixed, "order": order},
                )

        yield engine, scratch_url
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def dropped(scratch_database):
    """The scratch database with the drop migration applied."""
    engine, scratch_url = scratch_database
    with alembic_against(scratch_url) as config:
        command.upgrade(config, REVISION)
    return engine, scratch_url


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = :table"
                ),
                {"table": table},
            )
            .scalars()
            .all()
        )


def _settings(engine) -> dict:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT settings FROM tenants WHERE slug = 'drop-tenant'")
        ).scalar()


# ---------------------------------------------------------------------------
# What the upgrade removes
# ---------------------------------------------------------------------------


class TestTheSupersededColumnsAreGone:
    def test_the_blended_pair_is_dropped(self, dropped) -> None:
        engine, _ = dropped

        columns = _columns(engine, "sales_channels")

        assert "fee_percentage" not in columns
        assert "fee_fixed" not in columns

    def test_the_rest_of_the_channel_is_untouched(self, dropped) -> None:
        engine, _ = dropped

        columns = _columns(engine, "sales_channels")

        # `monthly_cost` in particular: it reads like one of the fee columns
        # and is not -- a periodic cost is absorbed over order volume, not
        # charged per sale, and `channel_pnl` still needs it.
        assert {"monthly_cost", "tax_remitter", "expected_refund_pct"} <= columns

    def test_the_channels_own_rows_survive(self, dropped) -> None:
        engine, _ = dropped
        with engine.connect() as conn:
            names = list(conn.execute(text("SELECT name FROM sales_channels")).scalars().all())

        assert names == ["Drop Channel"]

    def test_the_fee_rules_are_untouched(self, dropped) -> None:
        """The whole point: the rules are what charges a fee now."""
        engine, _ = dropped
        with engine.connect() as conn:
            rules = sorted(
                conn.execute(text("SELECT name, rate_pct, fixed_amount FROM fee_rules")).all()
            )

        assert rules == [
            ("platform_fixed", Decimal("0.0000"), LEGACY_FEE_FIXED),
            ("platform_percentage", Decimal("6.5000"), Decimal("0.00")),
        ]


class TestTheLegacyKeyIsGoneAndNothingElseIs:
    def test_the_labor_rate_key_is_removed(self, dropped) -> None:
        engine, _ = dropped

        assert "default_labor_rate" not in _settings(engine)

    def test_the_other_settings_keys_survive(self, dropped) -> None:
        """A migration that emptied the blob would pass the test above."""
        engine, _ = dropped

        assert _settings(engine)[KEPT_SETTINGS_KEY] == KEPT_SETTINGS_VALUE

    def test_the_policy_rate_is_not_touched(self, dropped) -> None:
        """The rate the engine actually reads must come through unchanged."""
        engine, _ = dropped
        with engine.connect() as conn:
            rate = conn.execute(
                text(
                    "SELECT print_labor_rate FROM tenant_pricing_policy WHERE effective_to IS NULL"
                )
            ).scalar()

        assert Decimal(str(rate)) == POLICY_LABOR_RATE

    def test_a_tenant_without_the_key_is_left_alone(self, scratch_database) -> None:
        engine, scratch_url = scratch_database
        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, slug, is_active, settings,
                                         created_at, updated_at)
                    VALUES (gen_random_uuid(), 'Plain Tenant', 'plain-tenant', true,
                            CAST('{"currency": "GBP"}' AS JSONB), now(), now())
                    """
                )
            )

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        with engine.connect() as conn:
            settings = conn.execute(
                text("SELECT settings FROM tenants WHERE slug = 'plain-tenant'")
            ).scalar()

        assert settings == {"currency": "GBP"}


class TestTheProvenanceRowsGoWithTheFields:
    def test_no_provenance_remains_for_a_field_that_no_longer_exists(self, dropped) -> None:
        """Provenance for a column nothing can display is a dead end on screen."""
        engine, _ = dropped
        with engine.connect() as conn:
            remaining = list(
                conn.execute(
                    text(
                        "SELECT field_name FROM pricing_input_provenance "
                        "WHERE entity_type = 'sales_channel' "
                        "AND field_name IN ('fee_percentage', 'fee_fixed')"
                    )
                )
                .scalars()
                .all()
            )

        assert remaining == []


# ---------------------------------------------------------------------------
# What the downgrade restores
# ---------------------------------------------------------------------------


class TestTheDowngradeRestoresAUsableShape:
    @pytest.fixture
    def reverted(self, dropped):
        engine, scratch_url = dropped
        with alembic_against(scratch_url) as config:
            command.downgrade(config, PARENT)
        return engine, scratch_url

    def test_the_columns_come_back(self, reverted) -> None:
        engine, _ = reverted

        columns = _columns(engine, "sales_channels")

        assert {"fee_percentage", "fee_fixed"} <= columns

    def test_they_are_backfilled_from_the_rules(self, reverted) -> None:
        """Summed from the rules, not from a remembered value: the columns were
        dropped, so there is nothing left to remember."""
        engine, _ = reverted
        with engine.connect() as conn:
            pct, fixed = conn.execute(
                text("SELECT fee_percentage, fee_fixed FROM sales_channels")
            ).one()

        assert Decimal(str(pct)) == LEGACY_FEE_PERCENTAGE
        assert Decimal(str(fixed)) == LEGACY_FEE_FIXED

    def test_the_labor_rate_comes_back_from_the_policy_row(self, reverted) -> None:
        engine, _ = reverted

        assert Decimal(str(_settings(engine)["default_labor_rate"])) == POLICY_LABOR_RATE

    def test_the_other_settings_keys_are_still_there(self, reverted) -> None:
        engine, _ = reverted

        assert _settings(engine)[KEPT_SETTINGS_KEY] == KEPT_SETTINGS_VALUE

    def test_the_migration_can_be_reapplied(self, reverted) -> None:
        """Down and up again, because a downgrade nobody can undo is a dead end."""
        engine, scratch_url = reverted
        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        columns = _columns(engine, "sales_channels")

        assert "fee_percentage" not in columns
        assert "default_labor_rate" not in _settings(engine)
