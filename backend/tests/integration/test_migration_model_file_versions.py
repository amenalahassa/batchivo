"""The model-file-versions migration groups existing files without moving a cost (T008).

Every model with files must come out with exactly one active version "1" that
holds all of them, a print file chosen from its sliced files, and -- the part
that fails quietly -- not one changed byte in any row the cost engine reads
(FR-016, SC-004). Runs the real chain on a scratch PostgreSQL database, with data
inserted between the parent revision and this one; synchronous like the other
migration suites, because psycopg's async mode cannot run on Windows' loop.
"""

import os
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from tests.integration.migration_support import alembic_against, database_named, sync_url

REVISION = "model_file_versions_v1"
PARENT = "packaging_advisor_v2"

#: Tables whose rows the cost engine reads for a model; the migration must not touch them.
COST_INPUT_TABLES = (
    "models",
    "model_materials",
    "model_printer_configs",
    "pricing_input_provenance",
)


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


pytestmark = pytest.mark.skipif(
    "postgres" not in _database_url(),
    reason="the backfill needs PostgreSQL (gen_random_uuid, partial indexes, RLS)",
)


def _snapshot(conn) -> dict[str, list]:
    return {
        table: [tuple(row) for row in conn.execute(text(f"SELECT * FROM {table} ORDER BY id"))]
        for table in COST_INPUT_TABLES
    }


def _insert_file(conn, model_id, name, file_type, *, primary=False, uploaded="2026-01-01"):
    conn.execute(
        text(
            """
            INSERT INTO model_files (id, tenant_id, model_id, file_type, file_location,
                                     file_url, original_filename, is_primary, uploaded_at,
                                     created_at, updated_at)
            SELECT gen_random_uuid(), tenant_id, id, :file_type, 'uploaded',
                   '/files/' || :name, :name, :primary, CAST(:uploaded AS timestamptz),
                   now(), now()
            FROM models WHERE id = :model_id
            """
        ),
        {
            "model_id": model_id,
            "name": name,
            "file_type": file_type,
            "primary": primary,
            "uploaded": uploaded,
        },
    )


@pytest.fixture(scope="module")
def migrated():
    base_url = _database_url()
    scratch = f"mfv_{uuid.uuid4().hex[:10]}"
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
            command.upgrade(config, PARENT)

        ids = {"with_files": uuid.uuid4(), "no_sliced": uuid.uuid4(), "no_files": uuid.uuid4()}
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO tenants (id, name, slug, is_active, settings, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), 'T', 't-mfv', true, '{}'::jsonb, now(), now())"
                )
            )
            for key, model_id in ids.items():
                conn.execute(
                    text(
                        """
                        INSERT INTO models (id, tenant_id, sku, name, print_time_minutes,
                                            prints_per_plate, is_active, created_at, updated_at)
                        SELECT :id, tenants.id, :sku, :sku, 95, 4, true, now(), now()
                        FROM tenants WHERE slug = 't-mfv'
                        """
                    ),
                    {"id": model_id, "sku": key.upper()},
                )
            _insert_file(conn, ids["with_files"], "part.stl", "source_stl", uploaded="2026-01-01")
            _insert_file(
                conn, ids["with_files"], "plate_old.gcode.3mf", "source_3mf", uploaded="2026-01-02"
            )
            _insert_file(conn, ids["with_files"], "plate_new.gcode", "gcode", uploaded="2026-01-03")
            _insert_file(conn, ids["no_sliced"], "only.stl", "source_stl")
            before = _snapshot(conn)

        with alembic_against(scratch_url) as config:
            command.upgrade(config, REVISION)

        yield engine, ids, before, scratch_url
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)'))
        admin.dispose()


class TestBackfill:
    def test_each_model_with_files_gets_one_active_version_one(self, migrated) -> None:
        engine, ids, _, _ = migrated
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT model_id, sequence, label, is_active FROM model_file_versions")
            ).all()
        by_model = {row[0]: row for row in rows}
        assert set(by_model) == {ids["with_files"], ids["no_sliced"]}
        for row in rows:
            assert (row[1], row[2], row[3]) == (1, "1", True)

    def test_a_model_without_files_gets_no_version(self, migrated) -> None:
        engine, ids, _, _ = migrated
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM model_file_versions WHERE model_id = :m"),
                {"m": ids["no_files"]},
            ).scalar_one()
        assert count == 0

    def test_every_file_is_in_its_models_version(self, migrated) -> None:
        engine, _, _, _ = migrated
        with engine.connect() as conn:
            stray = conn.execute(
                text(
                    """
                    SELECT count(*) FROM model_files f
                    JOIN model_file_versions v ON v.id = f.version_id
                    WHERE v.model_id <> f.model_id OR f.version <> '1'
                    """
                )
            ).scalar_one()
            unversioned = conn.execute(
                text("SELECT count(*) FROM model_files WHERE version_id IS NULL")
            ).scalar_one()
        assert (stray, unversioned) == (0, 0)

    def test_sliced_files_are_flagged_by_name_and_type(self, migrated) -> None:
        engine, _, _, _ = migrated
        with engine.connect() as conn:
            flags = dict(
                conn.execute(text("SELECT original_filename, is_sliced FROM model_files")).all()
            )
        assert flags == {
            "part.stl": False,
            "plate_old.gcode.3mf": True,
            "plate_new.gcode": True,
            "only.stl": False,
        }

    def test_print_file_is_the_newest_sliced_file(self, migrated) -> None:
        engine, ids, _, _ = migrated
        with engine.connect() as conn:
            name = conn.execute(
                text(
                    """
                    SELECT f.original_filename FROM model_file_versions v
                    JOIN model_files f ON f.id = v.print_file_id
                    WHERE v.model_id = :m
                    """
                ),
                {"m": ids["with_files"]},
            ).scalar_one()
            none = conn.execute(
                text("SELECT print_file_id FROM model_file_versions WHERE model_id = :m"),
                {"m": ids["no_sliced"]},
            ).scalar_one()
        assert name == "plate_new.gcode"
        assert none is None


class TestNothingTheCostEngineReadsMoves:
    def test_cost_input_rows_are_identical(self, migrated) -> None:
        """SC-004: the per-record difference must be empty."""
        engine, _, before, _ = migrated
        with engine.connect() as conn:
            after = _snapshot(conn)
        for table in COST_INPUT_TABLES:
            assert after[table] == before[table], f"{table} changed during the migration"


class TestIsolationAndReversal:
    def test_both_new_tables_are_under_forced_rls(self, migrated) -> None:
        engine, _, _, _ = migrated
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
                    WHERE relname IN ('model_file_versions', 'model_file_notes')
                    """
                )
            ).all()
            policies = (
                conn.execute(
                    text(
                        "SELECT tablename FROM pg_policies WHERE tablename IN "
                        "('model_file_versions', 'model_file_notes')"
                    )
                )
                .scalars()
                .all()
            )
        assert sorted(rows) == [
            ("model_file_notes", True, True),
            ("model_file_versions", True, True),
        ]
        assert sorted(policies) == ["model_file_notes", "model_file_versions"]

    def test_downgrade_then_upgrade_reaches_the_revision_again(self, migrated) -> None:
        _, _, _, scratch_url = migrated
        with alembic_against(scratch_url) as config:
            command.downgrade(config, PARENT)
            command.upgrade(config, REVISION)
