"""Onboarding step 5: standard packaging and carrier postage (spec 006, T024, T039)."""

import pytest
from sqlalchemy import select, update

from app.models.consumable import ConsumableType
from app.models.shipping_profile import ShippingProfile
from app.models.tenant import Tenant
from app.services import catalogue_data as cd
from app.services import catalogue_seed
from app.services.onboarding_wizard import new_wizard_progress

pytestmark = pytest.mark.asyncio

WIZARD = "/api/v1/onboarding/wizard"


@pytest.fixture
async def at_step5(db_session, test_tenant) -> Tenant:
    progress = {**new_wizard_progress(), "current_step": 5, "completed_steps": [1, 2, 3, 4]}
    await db_session.execute(
        update(Tenant)
        .where(Tenant.id == test_tenant.id)
        .values(settings={"onboarding": progress}, currency_code="CAD", country_code=None)
    )
    await db_session.commit()
    await db_session.refresh(test_tenant)
    cd.clear_caches()
    return test_tenant


async def _count(db, model, tenant) -> int:
    return len(
        (await db.execute(select(model).where(model.tenant_id == tenant.id))).scalars().all()
    )


class TestStep5:
    async def test_defaults_seed_packaging_and_postage(self, client, db_session, at_step5):
        response = await client.put(
            f"{WIZARD}/step/5", json={"default_service": "canada_post:small_packet"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["is_completed"] is True and body["warnings"] == []
        assert body["seed"]["packaging"]["added"] == len(cd.load_packaging_catalogue().items)
        assert body["seed"]["postage"]["carrier"] == "canada_post"
        assert await _count(db_session, ShippingProfile, at_step5) > 0
        await db_session.refresh(at_step5)
        assert at_step5.settings["postage"]["default_service"] == "canada_post:small_packet"

    async def test_selection_is_honoured(self, client, db_session, at_step5):
        response = await client.put(
            f"{WIZARD}/step/5",
            json={
                "packaging_keys": ["box-cube-100"],
                "carrier": "canada_post",
                "services": ["small_packet"],
            },
        )
        assert response.status_code == 200
        assert await _count(db_session, ConsumableType, at_step5) == 1
        services = {
            p.service
            for p in (
                await db_session.execute(
                    select(ShippingProfile).where(ShippingProfile.tenant_id == at_step5.id)
                )
            ).scalars()
        }
        assert services == {"small_packet"}

    async def test_skip_seeds_nothing(self, client, db_session, at_step5):
        response = await client.put(f"{WIZARD}/step/5", json={"skip": True})
        assert response.status_code == 200 and response.json()["is_completed"] is True
        assert await _count(db_session, ConsumableType, at_step5) == 0
        assert await _count(db_session, ShippingProfile, at_step5) == 0

    async def test_a_seeding_error_warns_and_completes(
        self, client, db_session, at_step5, monkeypatch
    ):
        async def broken(*args, **kwargs):
            raise cd.CatalogueDataError("catalogue unreadable")

        monkeypatch.setattr(catalogue_seed, "seed_packaging", broken)
        response = await client.put(f"{WIZARD}/step/5", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["is_completed"] is True
        assert any("Packaging page" in w for w in body["warnings"])
        assert await _count(db_session, ConsumableType, at_step5) == 0
        assert await _count(db_session, ShippingProfile, at_step5) > 0

    async def test_no_carrier_completes_and_says_why(self, client, db_session, at_step5):
        at_step5.currency_code = "AUD"
        await db_session.commit()
        response = await client.put(f"{WIZARD}/step/5", json={})
        assert response.status_code == 200
        assert response.json()["seed"]["postage"]["reason"] == cd.NO_CARRIER_FOR_CURRENCY

    async def test_unknown_key_422(self, client, db_session, at_step5):
        response = await client.put(f"{WIZARD}/step/5", json={"packaging_keys": ["box-nope"]})
        assert response.status_code == 422

    async def test_unknown_field_422(self, client, at_step5):
        response = await client.put(f"{WIZARD}/step/5", json={"colour": "red"})
        assert response.status_code == 422

    async def test_no_token_401(self, unauthenticated_client):
        response = await unauthenticated_client.put(f"{WIZARD}/step/5", json={"skip": True})
        assert response.status_code == 401


class TestStep3Country:
    async def test_stores_the_country(self, client, db_session, at_step5):
        response = await client.put(f"{WIZARD}/step/3", json={"country": "fr"})
        assert response.status_code == 200
        await db_session.refresh(at_step5)
        assert at_step5.country_code == "FR"

    async def test_bad_country_422(self, client, at_step5):
        assert (await client.put(f"{WIZARD}/step/3", json={"country": "FRA"})).status_code == 422
