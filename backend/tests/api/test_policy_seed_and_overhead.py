"""Every tenant has a policy row, and its figures say who chose them.

Task T219: a tenant created since the Tier 1 migration had no policy row and was
costed at a labour rate nobody chose, while every policy line was labelled
``policy`` -- an operator decision -- with no date. A tenant is now seeded an
``assumed`` row when it is created, and a line built from the policy reads
``policy`` only once an administrator has written it.

Task T222: the percentage overhead method read its percentage from a settings
blob nothing wrote. It is a dated, admin-only lever on the policy row.
"""

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.tenant import Tenant
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.models.user import UserRole
from app.services.pricing_policy import (
    POLICYLESS_LABOR_RATE,
    resolve_cost_policy,
    seed_policy_row,
    write_policy,
)

pytestmark = pytest.mark.asyncio

POLICY = "/api/v1/settings/pricing-policy"


async def _rows(db: AsyncSession, tenant_id) -> list[TenantPricingPolicy]:
    return list(
        (
            await db.execute(
                select(TenantPricingPolicy).where(TenantPricingPolicy.tenant_id == tenant_id)
            )
        )
        .scalars()
        .all()
    )


def _line(body: dict, key: str) -> dict:
    [line] = [line for line in body["lines"] if line["key"] == key]
    return line


# ============================================================================
# A tenant is seeded an assumed row
# ============================================================================


class TestATenantIsSeededAnAssumedPolicy:
    async def test_seeding_writes_one_dated_row_with_no_author(
        self, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        tenant_id = test_tenant.id

        await seed_policy_row(db_session, test_tenant)
        await db_session.commit()

        [row] = await _rows(db_session, tenant_id)
        assert row.set_by_user_id is None
        assert row.effective_from is not None
        assert row.print_labor_rate == POLICYLESS_LABOR_RATE

    async def test_seeding_twice_does_not_open_a_second_row(
        self, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        tenant_id = test_tenant.id

        await seed_policy_row(db_session, test_tenant)
        await seed_policy_row(db_session, test_tenant)
        await db_session.commit()

        assert len(await _rows(db_session, tenant_id)) == 1

    async def test_a_seeded_policy_is_assumed_and_a_written_one_is_policy(
        self, db_session: AsyncSession, test_tenant: Tenant, test_user
    ) -> None:
        await seed_policy_row(db_session, test_tenant)
        assert (await resolve_cost_policy(db_session, test_tenant)).source == "assumed"

        await write_policy(
            db_session,
            test_tenant,
            {"print_labor_rate": Decimal("31.00")},
            user=test_user,
            role="owner",
        )

        assert (await resolve_cost_policy(db_session, test_tenant)).source == "policy"

    async def test_completing_onboarding_seeds_the_new_tenant(
        self, db_session: AsyncSession
    ) -> None:
        import json

        from app.models.email_verification import EmailVerificationToken
        from app.services.onboarding_service import OnboardingService

        token = EmailVerificationToken.create_email_verification(
            email="seeded-owner@example.com",
            registration_data=json.dumps(
                {
                    "email": "seeded-owner@example.com",
                    "password_hash": "not-a-real-hash",
                    "full_name": "Seeded Owner",
                    "business_name": "Seeded Workspace",
                    "tenant_type": "three_d_print",
                    "slug": "seeded-workspace",
                }
            ),
            expires_hours=24,
        )
        db_session.add(token)
        await db_session.commit()

        await OnboardingService(db_session).verify_email(token.token)

        tenant = (
            await db_session.execute(select(Tenant).where(Tenant.slug == "seeded-workspace"))
        ).scalar_one()
        [row] = await _rows(db_session, tenant.id)
        assert row.set_by_user_id is None


# ============================================================================
# The labour line says whether anyone chose the rate
# ============================================================================


class TestTheLabourLineSaysWhoChoseTheRate:
    async def test_a_fresh_tenants_labour_reads_assumed_until_an_admin_sets_it(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_model: Model,
    ) -> None:
        await seed_policy_row(db_session, test_tenant)
        await db_session.commit()
        # The hours and the plate are measured, so the rate decides the line.
        await client.put(
            f"/api/v1/models/{test_model.id}/cost-profile",
            json={"labor_hours_per_item": "0.25", "prints_per_plate": 1},
        )

        before = (await client.get(f"/api/v1/models/{test_model.id}/cost")).json()
        assert _line(before, "labor_handling")["source"] == "assumed"

        written = await client.put(POLICY, json={"print_labor_rate": "31.00"})
        assert written.status_code == 200, written.text
        assert written.json()["source"] == "policy"

        after = (await client.get(f"/api/v1/models/{test_model.id}/cost")).json()
        line = _line(after, "labor_handling")
        assert line["source"] == "policy"
        assert line["as_of"] is not None

    async def test_one_lever_written_on_an_assumed_row_leaves_the_rest_assumed(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        """T260: changing the margin basis does not relabel the carried labour rate."""
        await seed_policy_row(db_session, test_tenant)
        await db_session.commit()

        written = await client.put(POLICY, json={"margin_basis": "item_price"})

        assert written.status_code == 200, written.text
        levers = written.json()["levers"]
        assert levers["margin_basis"]["source"] == "policy"
        assert levers["margin_basis"]["as_of"] is not None
        assert levers["margin_basis"]["set_by_role"] in {"admin", "owner"}
        for carried in ("print_labor_rate", "finishing_labor_rate", "overhead_percentage"):
            assert levers[carried]["source"] == "assumed", carried
            assert levers[carried]["as_of"] is None

        # And the next write carries the decided lever forward as decided.
        again = (await client.put(POLICY, json={"print_labor_rate": "31.00"})).json()
        assert again["levers"]["margin_basis"]["source"] == "policy"
        assert again["levers"]["print_labor_rate"]["source"] == "policy"
        assert again["levers"]["finishing_labor_rate"]["source"] == "assumed"

    async def test_a_carried_default_does_not_reach_a_cost_line_as_policy(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_model: Model,
    ) -> None:
        """The labour line built from a carried rate stays assumed (T260)."""
        await seed_policy_row(db_session, test_tenant)
        await db_session.commit()
        await client.put(
            f"/api/v1/models/{test_model.id}/cost-profile",
            json={"labor_hours_per_item": "0.25", "prints_per_plate": 1},
        )

        await client.put(POLICY, json={"margin_basis": "item_price"})

        body = (await client.get(f"/api/v1/models/{test_model.id}/cost")).json()
        assert _line(body, "labor_handling")["source"] == "assumed"

    async def test_the_policy_read_reports_a_seeded_row_as_assumed(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        await seed_policy_row(db_session, test_tenant)
        await db_session.commit()

        body = (await client.get(POLICY)).json()

        assert body["source"] == "assumed"
        assert body["origin"] == "policy_row"


# ============================================================================
# The overhead percentage is a dated, admin-only lever
# ============================================================================


class TestTheOverheadPercentageIsALever:
    async def test_the_percentage_method_costs_the_configured_percentage(
        self,
        client: AsyncClient,
        test_model: Model,
    ) -> None:
        written = await client.put(
            POLICY, json={"overhead_method": "percentage", "overhead_percentage": "12.5"}
        )
        assert written.status_code == 200, written.text
        assert Decimal(written.json()["overhead_percentage"]) == Decimal("12.5")

        body = (await client.get(f"/api/v1/models/{test_model.id}/cost")).json()

        overhead = _line(body, "overhead")
        base = sum(
            Decimal(line["amount"])
            for line in body["lines"]
            if line["key"]
            in ("material", "waste", "labor_handling", "labor_finishing", "labor_packing")
        )
        assert Decimal(overhead["amount"]) == pytest.approx(base * Decimal("0.125"), abs=0.01)
        assert overhead["source"] == "policy"

    async def test_a_change_is_dated_and_the_old_percentage_stays_readable(
        self, client: AsyncClient
    ) -> None:
        await client.put(POLICY, json={"overhead_percentage": "10", "effective_from": "2026-01-01"})
        await client.put(POLICY, json={"overhead_percentage": "15", "effective_from": "2026-06-01"})

        january = (await client.get(POLICY, params={"as_of": "2026-02-01"})).json()
        june = (await client.get(POLICY, params={"as_of": "2026-06-02"})).json()

        assert Decimal(january["overhead_percentage"]) == Decimal("10")
        assert Decimal(june["overhead_percentage"]) == Decimal("15")

    async def test_a_member_cannot_set_it(self, client: AsyncClient, as_role) -> None:
        async with as_role(UserRole.MEMBER):
            response = await client.put(POLICY, json={"overhead_percentage": "20"})

        assert response.status_code == 403

    async def test_a_negative_percentage_is_refused(self, client: AsyncClient) -> None:
        response = await client.put(POLICY, json={"overhead_percentage": "-1"})

        assert response.status_code == 422

    async def test_no_tenant_settings_blob_is_read_for_it(self) -> None:
        import importlib.util

        assert importlib.util.find_spec("app.services.tenant_cost_settings") is None
