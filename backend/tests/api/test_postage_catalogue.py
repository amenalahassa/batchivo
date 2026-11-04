"""Carrier postage endpoints (spec 006 US3, T036)."""

import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core import clock
from app.models.product import Product
from app.models.shipping_profile import ShippingProfile
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import catalogue_data as cd

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 11, 4)


@pytest.fixture(autouse=True)
async def _cad(db_session, test_tenant, monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    test_tenant.currency_code = "CAD"
    test_tenant.country_code = None
    test_tenant.settings = {}
    await db_session.commit()
    cd.clear_caches()
    yield
    cd.clear_caches()


async def _profiles(db, tenant) -> list[ShippingProfile]:
    return list(
        (await db.execute(select(ShippingProfile).where(ShippingProfile.tenant_id == tenant.id)))
        .scalars()
        .all()
    )


def _tariff_dir(root, effective: str, price: str) -> None:
    folder = root / "canada_post"
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "carrier": "canada_post",
        "name": "Canada Post",
        "currency": "CAD",
        "effective_date": effective,
        "source": f"test {effective}",
        "services": [
            {
                "key": "small_packet",
                "name": "Small Packet",
                "zones": [
                    {
                        "zone": "us",
                        "brackets": [{"min_grams": "0", "max_grams": "2000", "price": price}],
                    }
                ],
            }
        ],
    }
    (folder / f"{effective}.json").write_text(json.dumps(data), encoding="utf-8")


class TestCarriers:
    async def test_suggests_from_currency(self, client):
        body = (await client.get("/api/v1/postage/carriers")).json()
        assert body["suggested_carrier"] == "canada_post"
        assert body["chosen_from"] == "currency" and body["reason"] is None
        carriers = {c["key"]: c for c in body["carriers"]}
        assert set(carriers) == set(cd.CARRIER_NAMES)
        assert carriers["canada_post"]["usable"] is True
        assert carriers["usps"]["usable"] is False
        assert {s["key"] for s in carriers["canada_post"]["services"]} == set(
            cd.CARRIER_SERVICES["canada_post"]
        )

    async def test_suggests_from_country_and_reports_mismatch(
        self, client, db_session, test_tenant
    ):
        test_tenant.country_code = "US"
        await db_session.commit()
        body = (await client.get("/api/v1/postage/carriers")).json()
        assert body["suggested_carrier"] is None
        assert body["candidate_carrier"] == "usps"
        assert (body["chosen_from"], body["reason"]) == ("country", "carrier_currency_mismatch")

    async def test_no_token_401(self, unauthenticated_client):
        assert (await unauthenticated_client.get("/api/v1/postage/carriers")).status_code == 401


class TestApply:
    async def test_seeds_and_marks_services_seeded(self, client, db_session, test_tenant):
        response = await client.post(
            "/api/v1/postage/carriers/apply",
            json={"carrier": "canada_post", "services": ["small_packet"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["added"] == len(await _profiles(db_session, test_tenant)) > 0
        body = (await client.get("/api/v1/postage/carriers")).json()
        canada = next(c for c in body["carriers"] if c["key"] == "canada_post")
        seeded = {s["key"]: s["seeded"] for s in canada["services"]}
        assert seeded["small_packet"] is True and seeded["lettermail"] is False
        assert body["current"]["carrier"] == "canada_post"
        profiles = (await client.get("/api/v1/shipping-profiles")).json()["profiles"]
        assert profiles[0]["catalogue_carrier"] == "canada_post"
        assert profiles[0]["tariff_version"] and profiles[0]["source"]

    @pytest.mark.parametrize(
        "body",
        [
            {"carrier": "canada_post", "services": ["teleport"]},
            {"carrier": "usps"},
            {"carrier": "pigeon_post"},
            {"services": ["small_packet"]},
        ],
        ids=["unknown-service", "currency-mismatch", "unknown-carrier", "no-carrier"],
    )
    async def test_validation_422(self, client, body):
        response = await client.post("/api/v1/postage/carriers/apply", json=body)
        assert response.status_code == 422

    async def test_unknown_tariff_version_404(self, client):
        response = await client.post(
            "/api/v1/postage/carriers/apply",
            json={"carrier": "canada_post", "tariff_version": "2001-01-01"},
        )
        assert response.status_code == 404

    async def test_no_token_401(self, unauthenticated_client):
        response = await unauthenticated_client.post(
            "/api/v1/postage/carriers/apply", json={"carrier": "canada_post"}
        )
        assert response.status_code == 401

    async def test_viewer_403(self, as_role, db_session, test_tenant):
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(
                "/api/v1/postage/carriers/apply", json={"carrier": "canada_post"}
            )
        assert response.status_code == 403
        assert await _profiles(db_session, test_tenant) == []

    async def test_another_tenant_sees_nothing(self, client, db_session):
        """FR-024: applying for tenant A creates nothing visible to tenant B."""
        from app.auth.dependencies import get_current_tenant
        from app.main import app

        await client.post("/api/v1/postage/carriers/apply", json={"carrier": "canada_post"})
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
                assert (await b.get("/api/v1/shipping-profiles")).json()["profiles"] == []
                assert (await b.get("/api/v1/postage/tariff-updates")).json() == {"updates": []}
        finally:
            app.dependency_overrides[get_current_tenant] = previous


class TestTariffUpdates:
    async def test_offers_a_newer_tariff(self, client, tmp_path, monkeypatch):
        _tariff_dir(tmp_path, "2026-01-12", "9.00")
        _tariff_dir(tmp_path, "2027-01-11", "9.50")
        monkeypatch.setattr(cd, "TARIFF_ROOT", tmp_path)
        cd.clear_caches()
        await client.post(
            "/api/v1/postage/carriers/apply",
            json={"carrier": "canada_post", "tariff_version": "2026-01-12"},
        )
        (update,) = (await client.get("/api/v1/postage/tariff-updates")).json()["updates"]
        assert update["current"] == "2026-01-12" and update["latest"] == "2027-01-11"
        accepted = await client.post(
            "/api/v1/postage/carriers/apply",
            json={"carrier": "canada_post", "tariff_version": update["latest"]},
        )
        assert accepted.json()["superseded"] == 1 and accepted.json()["added"] == 1
        assert (await client.get("/api/v1/postage/tariff-updates")).json() == {"updates": []}

    async def test_none_without_seeded_postage(self, client):
        assert (await client.get("/api/v1/postage/tariff-updates")).json() == {"updates": []}

    async def test_no_token_401(self, unauthenticated_client):
        assert (
            await unauthenticated_client.get("/api/v1/postage/tariff-updates")
        ).status_code == 401


class TestRemoveService:
    async def test_supersedes_seeded_rows_only(self, client, db_session, test_tenant):
        mine = ShippingProfile(
            tenant_id=test_tenant.id,
            name="Courier",
            destination_zone="local",
            weight_bracket_min_grams=Decimal("0"),
            postage_cost=Decimal("4"),
            effective_from=date(2026, 1, 1),
            service="lettermail",
        )
        db_session.add(mine)
        await db_session.commit()
        await client.post("/api/v1/postage/carriers/apply", json={"carrier": "canada_post"})
        response = await client.delete("/api/v1/postage/carriers/services/lettermail")
        assert response.status_code == 204
        await db_session.refresh(mine)
        assert mine.effective_to is None
        remaining = {
            p.service for p in await _profiles(db_session, test_tenant) if p.catalogue_carrier
        }
        assert "lettermail" not in remaining

    async def test_not_seeded_404(self, client):
        response = await client.delete("/api/v1/postage/carriers/services/lettermail")
        assert response.status_code == 404

    async def test_no_token_401(self, unauthenticated_client):
        response = await unauthenticated_client.delete(
            "/api/v1/postage/carriers/services/lettermail"
        )
        assert response.status_code == 401

    async def test_viewer_403(self, as_role):
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.delete("/api/v1/postage/carriers/services/lettermail")
        assert response.status_code == 403


class TestDefaultService:
    async def test_set_and_clear(self, client, db_session, test_tenant):
        await client.post("/api/v1/postage/carriers/apply", json={"carrier": "canada_post"})
        response = await client.put(
            "/api/v1/settings/postage", json={"default_service": "canada_post:small_packet"}
        )
        assert response.status_code == 200
        assert response.json() == {
            "carrier": "canada_post",
            "default_service": "canada_post:small_packet",
        }
        cleared = await client.put("/api/v1/settings/postage", json={"default_service": None})
        assert cleared.json()["default_service"] is None

    async def test_unpriced_service_422(self, client):
        response = await client.put(
            "/api/v1/settings/postage", json={"default_service": "canada_post:small_packet"}
        )
        assert response.status_code == 422

    async def test_no_token_401(self, unauthenticated_client):
        response = await unauthenticated_client.put(
            "/api/v1/settings/postage", json={"default_service": None}
        )
        assert response.status_code == 401


class TestProductOverride:
    async def _product(self, db, tenant) -> Product:
        product = Product(tenant_id=tenant.id, sku=f"P-{uuid4().hex[:6]}", name="Dragon")
        db.add(product)
        await db.commit()
        return product

    async def test_set_known_service(self, client, db_session, test_tenant):
        await client.post("/api/v1/postage/carriers/apply", json={"carrier": "canada_post"})
        product = await self._product(db_session, test_tenant)
        response = await client.put(
            f"/api/v1/products/{product.id}",
            json={"postage_service": "canada_post:expedited_parcel"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["postage_service"] == "canada_post:expedited_parcel"
        cleared = await client.put(f"/api/v1/products/{product.id}", json={"postage_service": None})
        assert cleared.json()["postage_service"] is None

    async def test_unknown_service_422(self, client, db_session, test_tenant):
        product = await self._product(db_session, test_tenant)
        response = await client.put(
            f"/api/v1/products/{product.id}", json={"postage_service": "usps:priority_mail"}
        )
        assert response.status_code == 422

    async def test_unknown_product_404(self, client):
        response = await client.put(f"/api/v1/products/{uuid4()}", json={"postage_service": None})
        assert response.status_code == 404
