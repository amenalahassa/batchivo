"""The Tier 1 migration must preserve existing data and seed from it (T045).

The schema part of a migration fails loudly. The *data* part fails quietly: a
labor figure that was not copied, a policy row seeded from a default instead of
from what the operator configured, a provenance row dated today rather than
when the figure was set. None of those raise — they just make every cost on
screen slightly wrong, which is the class of defect this feature exists to end.

So this suite runs the chain against a scratch database with pre-Tier-1 data in
it, and checks what the seeding statements actually produced. It needs the real
PostgreSQL dialect (JSONB, partial indexes, RLS) and is skipped, loudly, on
SQLite.

Everything here is synchronous on purpose. A migration is synchronous, and
psycopg's async mode cannot run on Windows' default event loop -- an async
version of this suite would error out on a developer machine and only ever run
in CI, which is the opposite of what a data-migration check is for.
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

TIER1_REVISION = "pricing_tier1_v1"
TIER1_PARENT = "commerce_handover_v1"

#: What the operator had configured before Tier 1: a labor rate sitting unread
#: in the settings blob while every screen costed labor at a hardcoded 10.00.
CONFIGURED_LABOR_RATE = Decimal("22.5")
TENANT_CREATED_ON = "2024-05-04"
MODEL_CREATED_ON = "2024-06-01"
MODEL_LABOR_HOURS = Decimal("0.250")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


def _is_postgres() -> bool:
    return "postgres" in _database_url()


pytestmark = pytest.mark.skipif(
    not _is_postgres(),
    reason=(
        "the Tier 1 data migration needs the PostgreSQL dialect (JSONB, partial "
        "indexes, RLS policies); set DATABASE_URL to a PostgreSQL instance to run it"
    ),
)


@pytest.fixture
def migrated_tier1():
    """A scratch database upgraded to the Tier 1 parent, seeded, then upgraded.

    Yields a connected engine against the migrated database. The data is
    inserted *between* the two upgrades, which is the only way to exercise the
    seeding statements: run on an empty database they are all no-ops and prove
    nothing.
    """
    base_url = _database_url()
    scratch = f"tier1_seed_{uuid.uuid4().hex[:10]}"
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
            command.upgrade(config, TIER1_PARENT)

        with engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, slug, is_active, settings,
                                         created_at, updated_at)
                    VALUES (gen_random_uuid(), 'Seed Tenant', 'seed-tenant', true,
                            CAST(:settings AS JSONB), :created_at, now())
                    """
                ),
                {
                    "settings": f'{{"default_labor_rate": {CONFIGURED_LABOR_RATE}}}',
                    "created_at": f"{TENANT_CREATED_ON}T10:00:00Z",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO models (id, tenant_id, sku, name, labor_hours,
                                        print_time_minutes, prints_per_plate, is_active,
                                        created_at, updated_at)
                    SELECT gen_random_uuid(), tenants.id, 'SEED-MODEL', 'Seed Model',
                           :labor_hours, 540, 1, true, :created_at, now()
                    FROM tenants WHERE tenants.slug = 'seed-tenant'
                    """
                ),
                {
                    "labor_hours": MODEL_LABOR_HOURS,
                    "created_at": f"{MODEL_CREATED_ON}T10:00:00Z",
                },
            )

        with alembic_against(scratch_url) as config:
            command.upgrade(config, TIER1_REVISION)

        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


class TestThePolicyRowIsSeededFromTheOperatorsOwnSettings:
    def test_one_current_policy_row_per_tenant(self, migrated_tier1) -> None:
        with migrated_tier1.connect() as conn:
            rows = (
                conn.execute(
                    text("SELECT count(*) FROM tenant_pricing_policy WHERE effective_to IS NULL")
                )
            ).scalar_one()
        assert rows == 1

    def test_the_labor_rate_comes_from_the_settings_blob(self, migrated_tier1) -> None:
        """Not from a default invented here (Constitution IV)."""
        with migrated_tier1.connect() as conn:
            row = (
                conn.execute(
                    text("SELECT print_labor_rate, finishing_labor_rate FROM tenant_pricing_policy")
                )
            ).one()
        assert Decimal(str(row[0])) == CONFIGURED_LABOR_RATE
        assert Decimal(str(row[1])) == CONFIGURED_LABOR_RATE

    def test_it_is_effective_from_the_tenants_own_creation_date(self, migrated_tier1) -> None:
        """So an as-of read of any past order finds a policy in effect."""
        with migrated_tier1.connect() as conn:
            effective_from = (
                conn.execute(text("SELECT effective_from FROM tenant_pricing_policy"))
            ).scalar_one()
        assert str(effective_from) == TENANT_CREATED_ON

    def test_the_overhead_method_stays_the_one_their_costs_were_built_from(
        self, migrated_tier1
    ) -> None:
        """FR-050: switching the method silently would move every cost."""
        with migrated_tier1.connect() as conn:
            method = (
                conn.execute(text("SELECT overhead_method FROM tenant_pricing_policy"))
            ).scalar_one()
        assert method == "percentage"


class TestExistingSpoolAndModelDataSurvives:
    def test_the_deprecated_labor_figure_is_copied_not_moved(self, migrated_tier1) -> None:
        with migrated_tier1.connect() as conn:
            row = (conn.execute(text("SELECT labor_hours, labor_hours_per_item FROM models"))).one()
        assert Decimal(str(row[0])) == MODEL_LABOR_HOURS
        assert Decimal(str(row[1])) == MODEL_LABOR_HOURS, (
            "the per-item column must carry the figure the model already had"
        )

    def test_the_new_columns_default_to_a_no_op(self, migrated_tier1) -> None:
        """A tenant who changes no setting must see no figure move (FR-050)."""
        with migrated_tier1.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT waste_grams, expected_yield, failure_mode, "
                        "labor_hours_per_plate, finishing_hours_per_item, "
                        "packing_hours_per_item FROM models"
                    )
                )
            ).one()
        assert Decimal(str(row[0])) == Decimal("0")
        assert Decimal(str(row[1])) == Decimal("1")
        assert row[2] == "per_part"
        assert Decimal(str(row[3])) == Decimal("0")
        assert Decimal(str(row[4])) == Decimal("0")
        assert Decimal(str(row[5])) == Decimal("0")

    def test_a_spool_with_no_parent_purchase_is_still_valid(self, migrated_tier1) -> None:
        """FR-008e: the purchase link is nullable, and nothing backfills it."""
        with migrated_tier1.connect() as conn:
            nullable = (
                conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'spools' "
                        "AND column_name = 'filament_purchase_id'"
                    )
                )
            ).scalar_one()
        assert nullable == "YES"


class TestProvenanceIsSeededForWhatAlreadyExisted:
    def test_every_existing_numeric_input_gets_a_row(self, migrated_tier1) -> None:
        with migrated_tier1.connect() as conn:
            fields = set(
                (
                    conn.execute(
                        text(
                            "SELECT field_name FROM pricing_input_provenance "
                            "WHERE entity_type = 'model'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert {"labor_hours", "labor_hours_per_item", "print_time_minutes"} <= fields

    def test_an_estimate_is_recorded_as_assumed_and_dated_to_its_own_row(
        self, migrated_tier1
    ) -> None:
        """Dated when the figure was set, not when the migration ran (FR-001)."""
        with migrated_tier1.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT source, as_of FROM pricing_input_provenance "
                        "WHERE entity_type = 'model' AND field_name = 'labor_hours'"
                    )
                )
            ).one()
        assert row[0] == "assumed"
        assert str(row[1]) == MODEL_CREATED_ON

    def test_the_seeded_policy_levers_are_recorded_as_decisions(self, migrated_tier1) -> None:
        """A policy lever is a decision (FR-002), not a guess about the world."""
        with migrated_tier1.connect() as conn:
            sources = set(
                (
                    conn.execute(
                        text(
                            "SELECT DISTINCT source FROM pricing_input_provenance "
                            "WHERE entity_type = 'tenant_pricing_policy'"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert sources == {"policy"}

    def test_a_column_this_migration_created_empty_gets_no_row(self, migrated_tier1) -> None:
        """A row claiming a date for a NULL would be a fabrication."""
        with migrated_tier1.connect() as conn:
            count = (
                conn.execute(
                    text(
                        "SELECT count(*) FROM pricing_input_provenance "
                        "WHERE entity_type = 'printer'"
                    )
                )
            ).scalar_one()
        assert count == 0


class TestRowLevelSecurityIsEnabledOnEveryNewTable:
    @pytest.mark.parametrize(
        "table",
        ["tenant_pricing_policy", "pricing_input_provenance", "filament_purchases"],
    )
    def test_the_table_has_a_tenant_isolation_policy(self, migrated_tier1, table: str) -> None:
        with migrated_tier1.connect() as conn:
            enabled = (
                conn.execute(
                    text("SELECT relrowsecurity FROM pg_class WHERE relname = :table"),
                    {"table": table},
                )
            ).scalar_one()
            policies = (
                (
                    conn.execute(
                        text(
                            "SELECT polname FROM pg_policy "
                            "JOIN pg_class ON pg_class.oid = pg_policy.polrelid "
                            "WHERE relname = :table"
                        ),
                        {"table": table},
                    )
                )
                .scalars()
                .all()
            )
        assert enabled is True, f"{table} does not have row-level security enabled"
        assert f"{table}_tenant_isolation" in policies


class TestTheDowngradeIsReversible:
    def test_downgrading_removes_what_it_added_and_keeps_the_rest(self, migrated_tier1) -> None:
        """The copied labor figure stays where it came from."""
        url = migrated_tier1.url.render_as_string(hide_password=False)
        with alembic_against(url) as config:
            command.downgrade(config, TIER1_PARENT)

        with migrated_tier1.connect() as conn:
            tables = (
                (
                    conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_name IN ('tenant_pricing_policy', "
                            "'pricing_input_provenance', 'filament_purchases')"
                        )
                    )
                )
                .scalars()
                .all()
            )
            labor_hours = (conn.execute(text("SELECT labor_hours FROM models"))).scalar_one()

        assert tables == []
        assert Decimal(str(labor_hours)) == MODEL_LABOR_HOURS
