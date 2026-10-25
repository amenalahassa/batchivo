"""The operator can set the currency the books are kept in (T242, FR-028).

Every cost is converted from `Tenant.currency_code` (`currency_edge`), but no
endpoint wrote it, so a workshop keeping its books in another currency was
costed as GBP. It is monetary policy, so only the owner or admin sets it
(FR-007a).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.pricing_input_provenance import PricingInputProvenance
from app.models.tenant import Tenant
from app.models.user import UserRole

API = "/api/v1/settings/tenant"


async def _stored(db_session: AsyncSession, tenant_id) -> Tenant:
    db_session.expire_all()
    return (await db_session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()


class TestSettingTheBooksCurrency:
    async def test_an_admin_sets_it_and_it_is_stored(
        self, client, test_tenant: Tenant, db_session: AsyncSession
    ) -> None:
        tenant_id = test_tenant.id
        response = await client.put(API, json={"currency_code": "cad", "currency_symbol": "C$"})
        assert response.status_code == 200, response.text
        assert response.json()["currency_code"] == "CAD"
        assert response.json()["currency_symbol"] == "C$"
        stored = await _stored(db_session, tenant_id)
        assert (stored.currency_code, stored.currency_symbol) == ("CAD", "C$")

    async def test_it_is_returned_on_read(self, client) -> None:
        body = (await client.get(API)).json()
        assert body["currency_code"] == "GBP"
        assert body["currency_symbol"] == "£"

    async def test_a_member_cannot_change_it(
        self, as_role, test_tenant: Tenant, db_session: AsyncSession
    ) -> None:
        tenant_id = test_tenant.id
        async with as_role(UserRole.MEMBER) as member:
            response = await member.put(API, json={"currency_code": "USD"})
        assert response.status_code == 403
        assert (await _stored(db_session, tenant_id)).currency_code == "GBP"

    async def test_a_code_that_is_not_three_letters_is_refused(self, client) -> None:
        assert (await client.put(API, json={"currency_code": "US"})).status_code == 422
        assert (await client.put(API, json={"currency_code": "US1"})).status_code == 422

    async def test_a_currency_without_two_decimals_is_refused(self, client) -> None:
        response = await client.put(API, json={"currency_code": "JPY"})
        assert response.status_code == 422
        assert "two decimal places" in response.text

    async def test_leaving_it_out_leaves_it_alone(
        self, client, test_tenant: Tenant, db_session: AsyncSession
    ) -> None:
        tenant_id = test_tenant.id
        await client.put(API, json={"currency_code": "EUR", "currency_symbol": "€"})
        await client.put(API, json={"description": "Renamed"})
        assert (await _stored(db_session, tenant_id)).currency_code == "EUR"


async def _origin(db_session: AsyncSession, tenant_id) -> PricingInputProvenance | None:
    db_session.expire_all()
    return (
        await db_session.execute(
            select(PricingInputProvenance).where(
                PricingInputProvenance.tenant_id == tenant_id,
                PricingInputProvenance.entity_type == "tenant",
                PricingInputProvenance.field_name == "currency_code",
            )
        )
    ).scalar_one_or_none()


class TestTheBooksCurrencySaysWhereItCameFrom:
    """A change of books currency is a decision with an author and a date (T272)."""

    async def test_a_change_is_recorded_as_the_operators_decision(
        self, client, test_tenant: Tenant, test_user, db_session: AsyncSession
    ) -> None:
        tenant_id, user_id = test_tenant.id, test_user.id
        response = await client.put(API, json={"currency_code": "CAD", "currency_symbol": "C$"})
        assert response.status_code == 200, response.text

        origin = await _origin(db_session, tenant_id)
        assert origin is not None
        assert origin.source == "policy"
        assert origin.entity_id == tenant_id
        assert origin.measured_by_user_id == user_id
        assert origin.as_of == clock.today()

    async def test_leaving_the_currency_alone_records_nothing(
        self, client, test_tenant: Tenant, db_session: AsyncSession
    ) -> None:
        tenant_id = test_tenant.id
        await client.put(API, json={"description": "Renamed"})
        await client.put(API, json={"currency_code": "GBP"})
        assert await _origin(db_session, tenant_id) is None

    async def test_a_refused_change_records_nothing(
        self, as_role, test_tenant: Tenant, db_session: AsyncSession
    ) -> None:
        tenant_id = test_tenant.id
        async with as_role(UserRole.MEMBER) as member:
            assert (await member.put(API, json={"currency_code": "USD"})).status_code == 403
        assert await _origin(db_session, tenant_id) is None

    async def test_an_anonymous_change_is_refused(self, unauthenticated_client) -> None:
        response = await unauthenticated_client.put(API, json={"currency_code": "USD"})
        assert response.status_code == 401
