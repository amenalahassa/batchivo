"""Row-level security on the spec 009 tables, as `app_user` (spec 009, T009).

Reuses the scratch database of `test_rls_enforced` (migrations to head, two
tenants, `app_user` with a known password). Rows of both tenants are written
as the owner; the application connection then sees only its own tenant's rows,
and the API answers 404 for the other tenant's brief.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration import test_rls_enforced as _rls

API = _rls.API
_login = _rls._login
database = _rls.database
rls_app = _rls.rls_app

TABLES = ("design_briefs", "design_brief_revisions", "calibrations", "print_test_results")

pytestmark = [
    pytest.mark.skipif(
        "postgres" not in __import__("os").environ.get("DATABASE_URL", ""),
        reason="row-level security needs PostgreSQL; set DATABASE_URL to run it",
    ),
    pytest.mark.asyncio,
]


def _seed(owner, tenant_id: str) -> dict:
    """One row of every 009 table for ``tenant_id``, written as the owner."""
    ids = {k: str(uuid.uuid4()) for k in ("brief", "rev", "printer", "material", "cal", "result")}
    ids["tenant"] = tenant_id
    with owner.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO design_briefs (id, tenant_id, step_status, plan_md) VALUES"
                " (:brief, :tenant, CAST('{}' AS JSONB), 'secret plan')"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO design_brief_revisions (id, tenant_id, brief_id, part, content)"
                " VALUES (:rev, :tenant, :brief, 'plan', CAST('{}' AS JSONB))"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO printers (id, tenant_id, name, is_active, current_status, created_at,"
                " updated_at) VALUES (:printer, :tenant, :pname, true, 'offline', now(), now())"
            ),
            {**ids, "pname": f"P {ids['printer']}"},
        )
        conn.execute(
            text(
                "INSERT INTO material_types (id, name, code, is_active, created_at, updated_at)"
                " VALUES (:material, :code, :code, true, now(), now())"
            ),
            {**ids, "code": f"R{uuid.uuid4().hex[:6]}"},
        )
        conn.execute(
            text(
                "INSERT INTO calibrations (id, tenant_id, printer_id, material_type_id,"
                " orientation, fit_type, value_mm, provenance, measured_at) VALUES"
                " (:cal, :tenant, :printer, :material, 'vertical', 'slide', 0.15, 'measured', now())"
            ),
            ids,
        )
        conn.execute(
            text(
                "INSERT INTO print_test_results (id, tenant_id, kind, outcome, measurements)"
                " VALUES (:result, :tenant, 'clearance_grid', 'pass', CAST('[]' AS JSONB))"
            ),
            ids,
        )
    return ids


async def test_app_user_sees_only_its_tenant(rls_app):
    mine = _seed(rls_app["owner"], rls_app["tenant_a"])
    _seed(rls_app["owner"], rls_app["tenant_b"])

    async with rls_app["app_maker"]() as session:
        for table in TABLES:
            # No tenant set: nothing at all.
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            assert count == 0, table
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": rls_app["tenant_a"]},
        )
        for table in TABLES:
            tenants = (
                (await session.execute(text(f"SELECT DISTINCT tenant_id::text FROM {table}")))
                .scalars()
                .all()
            )
            assert tenants == [rls_app["tenant_a"]], table
        brief = (await session.execute(text("SELECT id::text FROM design_briefs"))).scalar_one()
        assert brief == mine["brief"]


async def test_app_user_cannot_write_into_another_tenant(rls_app):
    theirs = _seed(rls_app["owner"], rls_app["tenant_b"])
    async with rls_app["app_maker"]() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :t, true)"),
            {"t": rls_app["tenant_a"]},
        )
        updated = await session.execute(
            text("UPDATE design_briefs SET plan_md = 'mine now' WHERE id = :id"),
            {"id": theirs["brief"]},
        )
        assert updated.rowcount == 0
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO design_briefs (id, tenant_id, step_status) VALUES"
                    " (:id, :tenant, CAST('{}' AS JSONB))"
                ),
                {"id": str(uuid.uuid4()), "tenant": rls_app["tenant_b"]},
            )
        await session.rollback()


async def test_api_answers_404_for_another_tenants_brief(rls_app):
    client = rls_app["client"]
    theirs = _seed(rls_app["owner"], rls_app["tenant_b"])
    mine = _seed(rls_app["owner"], rls_app["tenant_a"])
    headers = await _login(client, rls_app["user_a_email"])

    response = await client.get(f"{API}/design-briefs/{theirs['brief']}", headers=headers)
    assert response.status_code == 404
    response = await client.get(f"{API}/design-briefs/{mine['brief']}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["plan_md"] == "secret plan"
    results = await client.get(f"{API}/print-test-results", headers=headers)
    assert {r["id"] for r in results.json()["items"]} >= {mine["result"]}
    assert theirs["result"] not in {r["id"] for r in results.json()["items"]}
