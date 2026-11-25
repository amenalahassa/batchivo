"""The 009 migration on a database that already holds data (spec 009, T010).

Printer secrets stored in clear before 009 must come out encrypted (and a
second run must not encrypt them twice); typed-note columns must default so
that existing notes read as a person's "info" note; the new tables must carry
row-level security and their immutability triggers; the downgrade must give
the secrets back in clear and turn dismissed notes back to open.

Synchronous, like the other migration suites (psycopg async cannot run on
Windows' default event loop).
"""

import os
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.encryption import decrypt_value
from tests.integration.migration_support import alembic_against, database_named, sync_url

PARENT = "genai_v1"
REVISION = "preflight_v1"
NEW_TABLES = ("design_briefs", "design_brief_revisions", "print_test_results", "calibrations")


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "")


pytestmark = pytest.mark.skipif(
    "postgres" not in _database_url(),
    reason="the 009 migration needs PostgreSQL (RLS policies, triggers, JSONB); set DATABASE_URL",
)


def _seed(conn, ids: dict) -> None:
    conn.execute(
        text(
            "INSERT INTO tenants (id, name, slug, is_active, settings, created_at, updated_at)"
            " VALUES (:tenant, 'Mig', :slug, true, CAST('{}' AS JSONB), now(), now())"
        ),
        ids,
    )
    for printer in ("printer", "printer_2"):  # one connection per printer
        conn.execute(
            text(
                "INSERT INTO printers (id, tenant_id, name, is_active, current_status, created_at,"
                " updated_at) VALUES (:id, :tenant, :name, true, 'offline', now(), now())"
            ),
            {**ids, "id": ids[printer], "name": printer},
        )
    for connection, printer, code, token in (
        ("clear", "printer", "12345678", "cloud-token"),
        ("empty", "printer_2", None, None),
    ):
        conn.execute(
            text(
                "INSERT INTO printer_connections (id, tenant_id, printer_id, connection_type,"
                " access_code, cloud_token, port, ams_count, developer_mode, is_enabled,"
                " is_connected, created_at, updated_at) VALUES (:id, :tenant, :printer,"
                " 'bambu_lan', :code, :token, 8883, 0, false, true, false, now(), now())"
            ),
            {**ids, "id": ids[connection], "printer": ids[printer], "code": code, "token": token},
        )


@pytest.fixture(scope="module")
def scratch():
    base_url = _database_url()
    name = f"preflight_mig_{uuid.uuid4().hex[:10]}"
    admin = create_engine(
        sync_url(database_named(base_url, "postgres")), isolation_level="AUTOCOMMIT"
    )
    url = database_named(base_url, name)
    engine = None
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_engine(sync_url(url), isolation_level="AUTOCOMMIT")
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        with alembic_against(url) as config:
            command.upgrade(config, PARENT)
        ids = {k: str(uuid.uuid4()) for k in ("tenant", "printer", "printer_2", "clear", "empty")}
        ids["slug"] = f"mig-{uuid.uuid4().hex[:6]}"
        with engine.connect() as conn:
            _seed(conn, ids)
        with alembic_against(url) as config:
            command.upgrade(config, REVISION)
        yield engine, url, ids
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _secrets(engine, connection_id: str) -> tuple:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT access_code, cloud_token FROM printer_connections WHERE id = :id"),
            {"id": connection_id},
        ).one()


def test_clear_secrets_are_encrypted(scratch):
    engine, _, ids = scratch
    code, token = _secrets(engine, ids["clear"])
    assert code != "12345678" and token != "cloud-token"
    assert decrypt_value(code) == "12345678"
    assert decrypt_value(token) == "cloud-token"
    assert _secrets(engine, ids["empty"]) == (None, None)


def test_access_code_column_is_text(scratch):
    engine, _, _ = scratch
    with engine.connect() as conn:
        kind = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns"
                " WHERE table_name = 'printer_connections' AND column_name = 'access_code'"
            )
        ).scalar_one()
    assert kind == "text"


def test_typed_note_columns_default_to_a_person_info_note(scratch):
    engine, _, _ = scratch
    with engine.connect() as conn:
        defaults = dict(
            conn.execute(
                text(
                    "SELECT column_name, column_default FROM information_schema.columns"
                    " WHERE table_name = 'model_file_notes'"
                    " AND column_name IN ('source', 'severity')"
                )
            ).all()
        )
        checks = set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint"
                    " WHERE conrelid = 'model_file_notes'::regclass AND contype = 'c'"
                )
            ).scalars()
        )
        status_check = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE conname = 'ck_model_file_notes_status'"
            )
        ).scalar_one()
    assert "person" in defaults["source"] and "info" in defaults["severity"]
    assert "dismissed" in status_check
    assert {
        "ck_model_file_notes_source",
        "ck_model_file_notes_severity",
    } <= checks


def test_new_tables_have_rls_and_a_policy(scratch):
    engine, _, _ = scratch
    with engine.connect() as conn:
        for table in NEW_TABLES:
            enabled = conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"), {"t": table}
            ).scalar_one()
            policies = conn.execute(
                text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": table}
            ).scalar_one()
            assert enabled, table
            assert policies >= 1, table


def test_revisions_and_calibrations_refuse_edits(scratch):
    engine, _, ids = scratch
    brief, revision, material, calibration = (str(uuid.uuid4()) for _ in range(4))
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO design_briefs (id, tenant_id, step_status) VALUES"
                " (:brief, :tenant, CAST('{}' AS JSONB))"
            ),
            {**ids, "brief": brief},
        )
        conn.execute(
            text(
                "INSERT INTO design_brief_revisions (id, tenant_id, brief_id, part, content)"
                " VALUES (:rev, :tenant, :brief, 'plan', CAST('{\"plan_md\": \"x\"}' AS JSONB))"
            ),
            {**ids, "brief": brief, "rev": revision},
        )
        conn.execute(
            text(
                "INSERT INTO material_types (id, name, code, is_active, created_at, updated_at)"
                " VALUES (:m, :code, :code, true, now(), now())"
            ),
            {"m": material, "code": f"P{uuid.uuid4().hex[:6]}"},
        )
        conn.execute(
            text(
                "INSERT INTO calibrations (id, tenant_id, printer_id, material_type_id,"
                " orientation, fit_type, value_mm, provenance, measured_at) VALUES"
                " (:c, :tenant, :printer, :m, 'vertical', 'slide', 0.15, 'measured', now())"
            ),
            {**ids, "c": calibration, "m": material},
        )
        with pytest.raises(DBAPIError):
            conn.execute(
                text("UPDATE design_brief_revisions SET part = 'risk' WHERE id = :id"),
                {"id": revision},
            )
        with pytest.raises(DBAPIError):
            conn.execute(
                text("UPDATE calibrations SET value_mm = 0.2 WHERE id = :id"), {"id": calibration}
            )
        # Superseding is the one change allowed.
        conn.execute(
            text("UPDATE calibrations SET superseded_at = now() WHERE id = :id"),
            {"id": calibration},
        )
        # Deleting the author still works: ON DELETE SET NULL is the one other change allowed.
        user = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO users (id, email, full_name, hashed_password, is_active,"
                " is_platform_admin, created_at, updated_at) VALUES (:u, :email, 'Gone', 'x',"
                " true, false, now(), now())"
            ),
            {"u": user, "email": f"gone-{user[:8]}@example.com"},
        )
        authored = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO design_brief_revisions (id, tenant_id, brief_id, part, content,"
                " author_user_id) VALUES (:rev, :tenant, :brief, 'risk', CAST('{}' AS JSONB), :u)"
            ),
            {**ids, "brief": brief, "rev": authored, "u": user},
        )
        recorded = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO calibrations (id, tenant_id, printer_id, material_type_id,"
                " orientation, fit_type, value_mm, provenance, measured_at, recorded_by_user_id)"
                " VALUES (:c, :tenant, :printer, :m, 'horizontal', 'snap', 0.3, 'assumed', now(),"
                " :u)"
            ),
            {**ids, "c": recorded, "m": material, "u": user},
        )
        conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})
        assert (
            conn.execute(
                text("SELECT author_user_id FROM design_brief_revisions WHERE id = :id"),
                {"id": authored},
            ).scalar_one()
            is None
        )
        assert (
            conn.execute(
                text("SELECT recorded_by_user_id FROM calibrations WHERE id = :id"),
                {"id": recorded},
            ).scalar_one()
            is None
        )
        with pytest.raises(DBAPIError):
            conn.execute(
                text("UPDATE calibrations SET notes = 'edited' WHERE id = :id"), {"id": recorded}
            )

        conn.execute(text("DELETE FROM design_briefs WHERE id = :id"), {"id": brief})
        left = conn.execute(
            text("SELECT count(*) FROM design_brief_revisions WHERE id = :id"), {"id": revision}
        ).scalar_one()
    assert left == 0  # a brief's revisions go with it


def test_downgrade_decrypts_and_upgrade_encrypts_again(scratch):
    engine, url, ids = scratch
    severity_columns = None
    with alembic_against(url) as config:
        command.downgrade(config, PARENT)
        assert _secrets(engine, ids["clear"]) == ("12345678", "cloud-token")
        with engine.connect() as conn:
            for table in NEW_TABLES:
                assert (
                    conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar_one() is None
                )
            severity_columns = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns"
                    " WHERE table_name = 'model_file_notes' AND column_name = 'severity'"
                )
            ).scalar_one()
        command.upgrade(config, REVISION)
    assert severity_columns == 0
    code, _ = _secrets(engine, ids["clear"])
    assert decrypt_value(code) == "12345678"
