"""The setup wizard a new tenant runs after verifying their email.

Bug onboarding-wizard-steps-missing: the frontend called six wizard routes the
backend never had, so every new tenant was stuck on step 1. These tests hold
each route to success, authentication, validation and the edge cases the
assessment named: a tenant from before the wizard counts as finished, the
business type is a setup-only choice, and the books currency records who chose
it.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pricing_input_provenance import PricingInputProvenance
from app.models.product import Product
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services.onboarding_wizard import new_wizard_progress

pytestmark = pytest.mark.asyncio

WIZARD = "/api/v1/onboarding/wizard"


@pytest.fixture
async def open_wizard(db_session: AsyncSession, test_tenant: Tenant) -> Tenant:
    """The test tenant, freshly verified: the wizard is open at step 1."""
    settings = {**(test_tenant.settings or {}), "onboarding": new_wizard_progress()}
    await db_session.execute(
        update(Tenant).where(Tenant.id == test_tenant.id).values(settings=settings)
    )
    await db_session.commit()
    await db_session.refresh(test_tenant)
    return test_tenant


async def _tenant(db_session: AsyncSession, tenant_id) -> Tenant:
    db_session.expire_all()
    return (await db_session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()


# ============================================
# Status
# ============================================


class TestStatus:
    async def test_a_tenant_from_before_the_wizard_is_finished(self, client: AsyncClient) -> None:
        response = await client.get(f"{WIZARD}/status")

        assert response.status_code == 200
        assert response.json()["is_completed"] is True

    async def test_a_fresh_tenant_starts_at_step_one(
        self, client: AsyncClient, open_wizard
    ) -> None:
        response = await client.get(f"{WIZARD}/status")

        body = response.json()
        assert body["is_completed"] is False
        assert body["current_step"] == 1
        assert body["tenant_id"] == str(open_wizard.id)

    async def test_requires_authentication(self, unauthenticated_client: AsyncClient) -> None:
        response = await unauthenticated_client.get(f"{WIZARD}/status")

        assert response.status_code == 401

    async def test_a_member_cannot_run_setup(self, as_role) -> None:
        async with as_role(UserRole.MEMBER) as member:
            response = await member.get(f"{WIZARD}/status")

        assert response.status_code == 403


# ============================================
# Steps
# ============================================


class TestSteps:
    async def test_step_one_renames_the_business_and_advances(
        self, client: AsyncClient, db_session: AsyncSession, open_wizard
    ) -> None:
        response = await client.put(
            f"{WIZARD}/step/1",
            json={"business_name": "Ember & Ash", "business_description": "Dragons"},
        )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "message": "Step 1 saved",
            "step_completed": 1,
            "next_step": 2,
            "is_completed": False,
        }
        tenant = await _tenant(db_session, open_wizard.id)
        assert tenant.name == "Ember & Ash"
        assert tenant.settings["onboarding"]["current_step"] == 2

    async def test_step_one_refuses_a_taken_address(
        self, client: AsyncClient, db_session: AsyncSession, open_wizard
    ) -> None:
        db_session.add(Tenant(name="Other", slug="taken-address", settings={}))
        await db_session.commit()

        response = await client.put(
            f"{WIZARD}/step/1", json={"business_name": "Mine", "slug": "taken-address"}
        )

        assert response.status_code == 409

    async def test_step_one_validates(self, client: AsyncClient, open_wizard) -> None:
        response = await client.put(f"{WIZARD}/step/1", json={"business_name": ""})

        assert response.status_code == 422

    async def test_step_two_sets_the_business_type(
        self, client: AsyncClient, db_session: AsyncSession, open_wizard
    ) -> None:
        response = await client.put(f"{WIZARD}/step/2", json={"tenant_type": "hand_knitting"})

        assert response.status_code == 200, response.text
        tenant = await _tenant(db_session, open_wizard.id)
        assert tenant.tenant_type == "hand_knitting"
        assert tenant.settings["tenant_type"] == "hand_knitting"

    async def test_step_two_is_refused_once_setup_is_finished(self, client: AsyncClient) -> None:
        # The test tenant has no wizard progress: it predates the wizard.
        response = await client.put(f"{WIZARD}/step/2", json={"tenant_type": "hand_knitting"})

        assert response.status_code == 409

    async def test_step_three_sets_the_currency_and_records_who_chose_it(
        self, client: AsyncClient, db_session: AsyncSession, open_wizard, test_user
    ) -> None:
        response = await client.put(
            f"{WIZARD}/step/3",
            json={
                "currency": "CAD",
                "currency_symbol": "C$",
                "shop_display_name": "Ember Shop",
                "timezone": "Asia/Tokyo",
                "primary_color": "#aa3300",
            },
        )

        assert response.status_code == 200, response.text
        tenant = await _tenant(db_session, open_wizard.id)
        assert tenant.currency_code == "CAD"
        assert tenant.currency_symbol == "C$"
        assert tenant.settings["shop"]["shop_name"] == "Ember Shop"
        assert tenant.settings["localization"]["timezone"] == "Asia/Tokyo"
        assert tenant.settings["branding"]["primary_color"] == "#aa3300"
        origin = (
            await db_session.execute(
                select(PricingInputProvenance).where(
                    PricingInputProvenance.tenant_id == open_wizard.id,
                    PricingInputProvenance.entity_type == "tenant",
                    PricingInputProvenance.field_name == "currency_code",
                )
            )
        ).scalar_one()
        assert origin.source != "observed"

    async def test_step_three_validates_the_currency(
        self, client: AsyncClient, open_wizard
    ) -> None:
        response = await client.put(f"{WIZARD}/step/3", json={"currency": "pounds"})

        assert response.status_code == 422

    async def test_step_three_refuses_a_currency_without_cents(
        self, client: AsyncClient, open_wizard
    ) -> None:
        response = await client.put(f"{WIZARD}/step/3", json={"currency": "JPY"})

        assert response.status_code == 422
        assert "two decimal places" in response.text

    async def test_an_unknown_step_is_not_found(self, client: AsyncClient, open_wizard) -> None:
        response = await client.put(f"{WIZARD}/step/5", json={})

        assert response.status_code == 404


# ============================================
# Step 4: the first product
# ============================================


class TestFirstProduct:
    async def test_skipping_finishes_the_wizard(
        self, client: AsyncClient, db_session: AsyncSession, open_wizard
    ) -> None:
        response = await client.put(f"{WIZARD}/step/4", json={"skip": True})

        assert response.status_code == 200
        assert response.json()["is_completed"] is True
        assert response.json()["next_step"] is None
        tenant = await _tenant(db_session, open_wizard.id)
        assert tenant.settings["onboarding"]["is_completed"] is True

    async def test_a_product_needs_a_name_unless_skipped(
        self, client: AsyncClient, open_wizard
    ) -> None:
        response = await client.put(f"{WIZARD}/step/4", json={"skip": False})

        assert response.status_code == 422

    async def test_the_product_is_created_and_the_price_lands_on_a_channel(
        self, client: AsyncClient, db_session: AsyncSession, open_wizard
    ) -> None:
        channel = SalesChannel(
            tenant_id=open_wizard.id, name="Market", platform_type="fair", is_active=True
        )
        db_session.add(channel)
        await db_session.commit()

        response = await client.put(
            f"{WIZARD}/step/4",
            json={"product_name": "Ember Dragon", "product_price": "24.50"},
        )

        assert response.status_code == 200, response.text
        product = (
            await db_session.execute(
                select(Product).where(
                    Product.tenant_id == open_wizard.id, Product.name == "Ember Dragon"
                )
            )
        ).scalar_one()
        pricing = (
            await db_session.execute(
                select(ProductPricing).where(ProductPricing.product_id == product.id)
            )
        ).scalar_one()
        assert pricing.sales_channel_id == channel.id
        assert pricing.list_price == Decimal("24.50")

    async def test_without_a_channel_the_price_is_not_stored(
        self, client: AsyncClient, db_session: AsyncSession, open_wizard
    ) -> None:
        response = await client.put(
            f"{WIZARD}/step/4",
            json={"product_name": "Ash Wyrm", "product_price": "10.00"},
        )

        assert response.status_code == 200, response.text
        tenant = await _tenant(db_session, open_wizard.id)
        assert tenant.settings["onboarding"]["step_data"]["step_4"]["price_stored"] is False
