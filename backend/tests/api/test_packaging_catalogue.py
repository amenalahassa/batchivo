"""The standard packaging catalogue endpoints and the seeding notice (spec 006 US2, T023)."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.models.consumable import ConsumableType
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import catalogue_data as cd

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _cad(db_session, test_tenant):
    test_tenant.currency_code = "CAD"
    test_tenant.settings = {}
    await db_session.commit()
    cd.clear_caches()


async def _rows(db, tenant) -> list[ConsumableType]:
    return list(
        (await db.execute(select(ConsumableType).where(ConsumableType.tenant_id == tenant.id)))
        .scalars()
        .all()
    )


class TestCatalogue:
    async def test_lists_items_with_tenant_currency_cost(self, client: AsyncClient):
        response = await client.get("/api/v1/packaging/catalogue")
        assert response.status_code == 200
        body = response.json()
        catalogue = cd.load_packaging_catalogue()
        assert body["version"] == catalogue.version and body["currency"] == "CAD"
        item = next(i for i in body["items"] if i["key"] == "box-cube-100")
        assert item["typical_cost"] == str(catalogue.by_key()["box-cube-100"].typical_cost["CAD"])
        assert item["present"] is False and item["previously_removed"] is False

    async def test_present_and_previously_removed(self, client, db_session, test_tenant):
        await client.post(
            "/api/v1/packaging/catalogue/apply", json={"keys": ["box-cube-100", "box-cube-150"]}
        )
        row = next(
            r for r in await _rows(db_session, test_tenant) if r.catalogue_key == "box-cube-150"
        )
        await db_session.delete(row)
        await db_session.commit()
        items = {
            i["key"]: i for i in (await client.get("/api/v1/packaging/catalogue")).json()["items"]
        }
        assert items["box-cube-100"]["present"] is True and items["box-cube-100"]["present_as"]
        assert items["box-cube-150"]["present"] is False
        assert items["box-cube-150"]["previously_removed"] is True

    async def test_no_token_401(self, unauthenticated_client):
        assert (await unauthenticated_client.get("/api/v1/packaging/catalogue")).status_code == 401


class TestApply:
    async def test_adds_all_then_reports_present(self, client, db_session, test_tenant):
        first = await client.post("/api/v1/packaging/catalogue/apply", json={})
        assert first.status_code == 200
        total = len(cd.load_packaging_catalogue().items)
        assert len(first.json()["added"]) == total
        again = (await client.post("/api/v1/packaging/catalogue/apply", json={"keys": []})).json()
        assert again["added"] == [] and len(again["skipped"]) == total
        assert {s["reason"] for s in again["skipped"]} == {"already_present"}
        assert len(await _rows(db_session, test_tenant)) == total

    async def test_unknown_key_422(self, client):
        response = await client.post(
            "/api/v1/packaging/catalogue/apply", json={"keys": ["box-nope"]}
        )
        assert response.status_code == 422
        assert "box-nope" in response.json()["detail"]

    async def test_no_token_401(self, unauthenticated_client):
        response = await unauthenticated_client.post("/api/v1/packaging/catalogue/apply", json={})
        assert response.status_code == 401

    async def test_viewer_403(self, as_role, db_session, test_tenant):
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post("/api/v1/packaging/catalogue/apply", json={})
        assert response.status_code == 403
        assert await _rows(db_session, test_tenant) == []

    async def test_member_may_seed(self, as_role):
        async with as_role(UserRole.MEMBER) as member:
            response = await member.post(
                "/api/v1/packaging/catalogue/apply", json={"keys": ["box-cube-100"]}
            )
        assert response.status_code == 200


class TestNotice:
    async def test_notice_then_acknowledge(self, client):
        assert (await client.get("/api/v1/catalogue-notice")).json() == {}
        await client.post("/api/v1/packaging/catalogue/apply", json={"keys": ["box-cube-100"]})
        notice = (await client.get("/api/v1/catalogue-notice")).json()
        assert notice["packaging"]["added"] == ["box-cube-100"]
        ack = await client.post("/api/v1/catalogue-notice/acknowledge", json={"part": "packaging"})
        assert ack.status_code == 204
        assert (await client.get("/api/v1/catalogue-notice")).json() == {}

    async def test_bad_part_422(self, client):
        response = await client.post(
            "/api/v1/catalogue-notice/acknowledge", json={"part": "labels"}
        )
        assert response.status_code == 422

    async def test_no_token_401(self, unauthenticated_client):
        assert (await unauthenticated_client.get("/api/v1/catalogue-notice")).status_code == 401
        response = await unauthenticated_client.post(
            "/api/v1/catalogue-notice/acknowledge", json={"part": "packaging"}
        )
        assert response.status_code == 401


class TestTenantIsolation:
    async def test_another_tenant_sees_nothing(self, client, db_session, test_tenant):
        """FR-024: tenant B never sees tenant A's seeded rows or notice."""
        from app.auth.dependencies import get_current_tenant
        from app.main import app

        await client.post("/api/v1/packaging/catalogue/apply", json={})
        other = Tenant(
            id=uuid4(), name="B", slug=f"b-{uuid4().hex[:8]}", settings={}, currency_code="CAD"
        )
        db_session.add(other)
        await db_session.commit()

        async def tenant_b():
            return other

        previous = app.dependency_overrides[get_current_tenant]
        app.dependency_overrides[get_current_tenant] = tenant_b
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as b:
                catalogue = (await b.get("/api/v1/packaging/catalogue")).json()
                assert not any(i["present"] for i in catalogue["items"])
                assert (await b.get("/api/v1/catalogue-notice")).json() == {}
                listed = await b.get(
                    "/api/v1/consumables/types",
                    params={"packaging_kind": "box,mailer,void_fill,wrap"},
                )
                assert listed.json()["consumables"] == []
        finally:
            app.dependency_overrides[get_current_tenant] = previous
