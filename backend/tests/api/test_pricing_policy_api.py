"""`/settings/pricing-policy` — read for everyone, write for admin (task T034).

FR-002 makes every lever here an operator decision, and FR-007a says a change
carries the role that authorised it. The tests therefore check two things a
status code alone does not: that a refused write leaves the stored figure
exactly as it was, and that an accepted write *adds* a row rather than editing
one (FR-003).
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio

ENDPOINT = "/api/v1/settings/pricing-policy"


async def _rows(db_session: AsyncSession, tenant: Tenant) -> int:
    result = await db_session.execute(
        select(func.count())
        .select_from(TenantPricingPolicy)
        .where(TenantPricingPolicy.tenant_id == tenant.id)
    )
    return int(result.scalar_one())


async def _current(db_session: AsyncSession, tenant: Tenant) -> TenantPricingPolicy:
    result = await db_session.execute(
        select(TenantPricingPolicy).where(
            TenantPricingPolicy.tenant_id == tenant.id,
            TenantPricingPolicy.effective_to.is_(None),
        )
    )
    return result.scalars().one()


# ============================================================================
# Reading
# ============================================================================


class TestReadingThePolicy:
    async def test_a_tenant_with_no_row_still_gets_its_policy(
        self, client: AsyncClient, test_tenant: Tenant
    ) -> None:
        """A tenant the Tier 1 migration has not reached is not a 404.

        Their labor rate lives in the legacy settings blob, and FR-050 says a
        figure on screen must not change silently — so the read falls back to
        it and says where it came from.
        """
        response = await client.get(ENDPOINT)

        assert response.status_code == 200
        body = response.json()
        assert body["origin"] == "legacy_settings"
        # test_tenant's settings carry default_labor_rate 20.0
        assert Decimal(body["print_labor_rate"]) == Decimal("20")

    @pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.VIEWER])
    async def test_every_role_may_read(self, as_role, role: UserRole) -> None:
        """A viewer who cannot see the rates cannot check a single figure."""
        async with as_role(role) as ac:
            response = await ac.get(ENDPOINT)
        assert response.status_code == 200

    async def test_unauthenticated_is_refused(self, unauthenticated_client: AsyncClient) -> None:
        response = await unauthenticated_client.get(ENDPOINT)
        assert response.status_code == 401

    async def test_the_read_reports_every_lever_as_a_decimal_string(
        self, client: AsyncClient
    ) -> None:
        """Money crosses the wire as a string, never a JSON float (T012)."""
        response = await client.get(ENDPOINT)
        body = response.json()

        for field in (
            "print_labor_rate",
            "finishing_labor_rate",
            "margin_alert_threshold_pct",
            "estimate_divergence_threshold_pct",
        ):
            assert isinstance(body[field], str), f"{field} crossed the wire as {type(body[field])}"

    async def test_an_as_of_read_returns_the_row_in_effect_then(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        old = TenantPricingPolicy(
            tenant_id=test_tenant.id,
            print_labor_rate=Decimal("18.0000"),
            finishing_labor_rate=Decimal("18.0000"),
            overhead_method="percentage",
            margin_basis="customer_total",
            effective_from=date(2024, 1, 1),
            effective_to=date(2024, 12, 31),
        )
        current = TenantPricingPolicy(
            tenant_id=test_tenant.id,
            print_labor_rate=Decimal("25.0000"),
            finishing_labor_rate=Decimal("25.0000"),
            overhead_method="percentage",
            margin_basis="customer_total",
            effective_from=date(2025, 1, 1),
            effective_to=None,
        )
        db_session.add_all([old, current])
        await db_session.commit()

        then = await client.get(ENDPOINT, params={"as_of": "2024-06-01"})
        now = await client.get(ENDPOINT)

        assert Decimal(then.json()["print_labor_rate"]) == Decimal("18")
        assert Decimal(now.json()["print_labor_rate"]) == Decimal("25")


# ============================================================================
# Writing
# ============================================================================


class TestWritingThePolicy:
    async def test_an_admin_write_creates_a_new_effective_row(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        first = await client.put(ENDPOINT, json={"print_labor_rate": "25.00"})
        assert first.status_code == 200

        before = await _rows(db_session, test_tenant)
        second = await client.put(ENDPOINT, json={"print_labor_rate": "30.00"})
        assert second.status_code == 200
        after = await _rows(db_session, test_tenant)

        assert after == before + 1, "a policy change must add a row, never edit one"
        assert Decimal(second.json()["print_labor_rate"]) == Decimal("30")

    async def test_an_unchanged_lever_is_carried_forward(self, client: AsyncClient) -> None:
        await client.put(
            ENDPOINT,
            json={"print_labor_rate": "25.00", "finishing_labor_rate": "32.00"},
        )
        response = await client.put(ENDPOINT, json={"print_labor_rate": "26.00"})

        body = response.json()
        assert Decimal(body["print_labor_rate"]) == Decimal("26")
        assert Decimal(body["finishing_labor_rate"]) == Decimal("32"), (
            "a lever the operator did not touch must survive the write"
        )

    async def test_the_write_records_the_role_that_authorised_it(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ) -> None:
        await client.put(ENDPOINT, json={"print_labor_rate": "25.00"})

        row = await _current(db_session, test_tenant)
        assert row.set_by_role == "admin"
        assert row.set_by_user_id is not None

    @pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.VIEWER])
    async def test_a_write_is_refused_for_member_and_viewer(
        self,
        as_role,
        role: UserRole,
        db_session: AsyncSession,
        test_tenant: Tenant,
    ) -> None:
        """403, and — the part that matters — the figure is untouched."""
        async with as_role(role) as ac:
            response = await ac.put(ENDPOINT, json={"print_labor_rate": "999.00"})

        assert response.status_code == 403
        assert await _rows(db_session, test_tenant) == 0, (
            "a refused write must not leave a policy row behind"
        )

    async def test_a_refused_write_leaves_an_existing_figure_alone(
        self,
        client: AsyncClient,
        as_role,
        db_session: AsyncSession,
        test_tenant: Tenant,
    ) -> None:
        await client.put(ENDPOINT, json={"print_labor_rate": "25.00"})
        rows_before = await _rows(db_session, test_tenant)

        async with as_role(UserRole.MEMBER) as member:
            refused = await member.put(ENDPOINT, json={"print_labor_rate": "1.00"})

        assert refused.status_code == 403
        row = await _current(db_session, test_tenant)
        assert Decimal(str(row.print_labor_rate)) == Decimal("25")
        assert await _rows(db_session, test_tenant) == rows_before

    async def test_unauthenticated_write_is_refused(
        self, unauthenticated_client: AsyncClient
    ) -> None:
        response = await unauthenticated_client.put(ENDPOINT, json={"print_labor_rate": "25.00"})
        assert response.status_code == 401


# ============================================================================
# Validation
# ============================================================================


class TestValidation:
    async def test_an_unknown_margin_basis_is_refused(self, client: AsyncClient) -> None:
        response = await client.put(ENDPOINT, json={"margin_basis": "whatever_sounds_good"})
        assert response.status_code == 422

    async def test_an_unknown_overhead_method_is_refused(self, client: AsyncClient) -> None:
        response = await client.put(ENDPOINT, json={"overhead_method": "vibes"})
        assert response.status_code == 422

    async def test_per_machine_hour_without_a_capacity_is_refused(
        self, client: AsyncClient
    ) -> None:
        """A capacity of zero is a misconfiguration, not a divisor."""
        response = await client.put(
            ENDPOINT,
            json={
                "overhead_method": "per_machine_hour",
                "overhead_monthly_pool": "180.00",
                "expected_monthly_machine_hours": "0",
            },
        )
        assert response.status_code == 422

    async def test_a_negative_labor_rate_is_refused(self, client: AsyncClient) -> None:
        response = await client.put(ENDPOINT, json={"print_labor_rate": "-1.00"})
        assert response.status_code == 422

    async def test_an_unknown_lever_is_refused_rather_than_ignored(
        self, client: AsyncClient
    ) -> None:
        """A silently dropped lever is a policy the operator believes they set."""
        response = await client.put(ENDPOINT, json={"labour_rate": "25.00"})
        assert response.status_code == 422

    async def test_an_empty_body_is_refused(self, client: AsyncClient) -> None:
        """Nothing to change is not a change; it must not open a new period."""
        response = await client.put(ENDPOINT, json={})
        assert response.status_code == 422
