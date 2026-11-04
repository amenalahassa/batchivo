"""The shop's country in general settings (spec 006, FR-017a, T039)."""

import pytest
from sqlalchemy import func, select

from app.models.shipping_profile import ShippingProfile
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

URL = "/api/v1/settings/tenant"


class TestCountry:
    async def test_set_and_clear(self, client, db_session, test_tenant):
        response = await client.put(URL, json={"country_code": "ca"})
        assert response.status_code == 200
        assert response.json()["country_code"] == "CA"
        assert (await client.get(URL)).json()["country_code"] == "CA"
        cleared = await client.put(URL, json={"country_code": None})
        assert cleared.json()["country_code"] is None

    async def test_other_fields_leave_it_alone(self, client):
        await client.put(URL, json={"country_code": "GB"})
        response = await client.put(URL, json={"name": "Renamed"})
        assert response.json()["country_code"] == "GB"

    @pytest.mark.parametrize("code", ["FRA", "1A", "F"])
    async def test_bad_code_422(self, client, code):
        assert (await client.put(URL, json={"country_code": code})).status_code == 422

    async def test_no_token_401(self, unauthenticated_client):
        response = await unauthenticated_client.put(URL, json={"country_code": "CA"})
        assert response.status_code == 401

    async def test_viewer_403(self, as_role):
        async with as_role(UserRole.VIEWER) as viewer:
            assert (await viewer.put(URL, json={"country_code": "CA"})).status_code == 403

    async def test_changing_it_seeds_nothing(self, client, db_session, test_tenant):
        await client.put(URL, json={"country_code": "FR"})
        count = (
            await db_session.execute(
                select(func.count())
                .select_from(ShippingProfile)
                .where(ShippingProfile.tenant_id == test_tenant.id)
            )
        ).scalar_one()
        assert count == 0
