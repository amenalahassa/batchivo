"""Every table carrying tenant_id has row-level security and a policy.

The RLS revisions enumerated tenant tables by hand, so six tables created later
were never covered (bug product-variants-rls). This suite asks the catalog of a
database built from migrations alone, so a table added tomorrow is held to the
same rule without anyone remembering to list it. It also checks the five
datetime columns and two others that `timestamptz_instants_v1` converts (bug
postgres-naive-datetime-writes), since both need the real migration chain.

Synchronous on purpose, like the other migration suites: psycopg's async mode
cannot run on Windows' default event loop.
"""

import os
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from tests.integration.migration_support import (
    alembic_against,
    database_named,
    sync_url,
)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


pytestmark = pytest.mark.skipif(
    "postgres" not in _database_url(),
    reason="RLS and timestamptz need PostgreSQL; set DATABASE_URL to a PostgreSQL instance",
)


#: Tables keyed by tenant_id that are deliberately not tenant-isolated, each with
#: the reason. Adding one here is a decision, not a way to make the test pass.
NOT_TENANT_ISOLATED_BY_DESIGN: dict[str, str] = {
    "commerce_handover": (
        "a platform write fence: app/services/commerce_handover.py reads it on its "
        "own engine under an advisory lock, before and outside any tenant session"
    ),
}


@pytest.fixture(scope="module")
def migrated():
    """A scratch database upgraded to head, yielded as a sync engine."""
    base_url = _database_url()
    scratch = f"rls_catalog_{uuid.uuid4().hex[:10]}"
    admin = create_engine(
        sync_url(database_named(base_url, "postgres")), isolation_level="AUTOCOMMIT"
    )
    scratch_url = database_named(base_url, scratch)
    engine = None
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{scratch}"'))
        engine = create_engine(sync_url(scratch_url), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        with alembic_against(scratch_url) as config:
            command.upgrade(config, "head")
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


def test_every_tenant_table_has_rls_enabled_and_a_policy(migrated) -> None:
    with migrated.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.relname,
                       c.relrowsecurity,
                       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                  AND a.attname = 'tenant_id' AND NOT a.attisdropped
                ORDER BY c.relname
                """
            )
        ).all()
    assert rows, "no tenant tables found; the migration chain did not run"
    uncovered = [
        name
        for name, enabled, policies in rows
        if (not enabled or policies == 0) and name not in NOT_TENANT_ISOLATED_BY_DESIGN
    ]
    assert uncovered == [], f"tenant tables without RLS or a policy: {uncovered}"


def test_every_by_design_exception_is_still_a_tenant_table(migrated) -> None:
    """An exception for a table that is gone, or lost its tenant_id, is stale."""
    with migrated.connect() as conn:
        present = set(
            conn.execute(
                text(
                    "SELECT table_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
                )
            ).scalars()
        )
    assert set(NOT_TENANT_ISOLATED_BY_DESIGN) <= present


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("platform_admin_audit_logs", "created_at"),
        ("platform_settings", "updated_at"),
        ("webhook_subscriptions", "last_triggered_at"),
        ("webhook_subscriptions", "last_success_at"),
        ("webhook_deliveries", "next_retry_at"),
        ("webhook_deliveries", "completed_at"),
        ("external_listings", "last_synced_at"),
    ],
)
def test_instant_columns_are_timestamptz(migrated, table: str, column: str) -> None:
    with migrated.connect() as conn:
        data_type = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        ).scalar_one()
    assert data_type == "timestamp with time zone"
