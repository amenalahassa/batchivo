"""`/printers/{id}/cost-policy` — the machine rate and its parts (task T034).

FR-010 defines the hourly occupancy rate; FR-018 says a figure must be
explainable without recomputing it, which is why the read returns the
components and not only the total. FR-019 is the reason an unset policy
reports a missing rate rather than zero: a 40-hour print on a free machine is
a figure that looks real and is not.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.printer import Printer
from app.models.user import UserRole

pytestmark = pytest.mark.asyncio


def _url(printer: Printer) -> str:
    return f"/api/v1/printers/{printer.id}/cost-policy"


# ============================================================================
# Reading
# ============================================================================


class TestReadingTheCostPolicy:
    async def test_an_unset_policy_reports_a_missing_rate_not_zero(
        self, client: AsyncClient, test_printer: Printer
    ) -> None:
        response = await client.get(_url(test_printer))

        assert response.status_code == 200
        body = response.json()
        assert body["machine_rate_per_hour"] is None, (
            "an unconfigured machine must not cost zero per hour"
        )
        assert "purchase_price" in body["missing"]
        assert "expected_lifetime_hours" in body["missing"]

    async def test_a_configured_policy_returns_the_rate_and_its_parts(
        self, client: AsyncClient, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        """The golden case's machine: CA$1,100 over 6,000 h, CA$220 reserve, 95 W."""
        test_printer.purchase_price = Decimal("1100.00")
        test_printer.expected_lifetime_hours = 6000
        test_printer.maintenance_reserve_total = Decimal("220.00")
        test_printer.measured_watts = Decimal("95.00")
        test_printer.electricity_rate_per_kwh = Decimal("0.1300")
        await db_session.commit()

        response = await client.get(_url(test_printer))

        assert response.status_code == 200
        body = response.json()
        components = body["components"]
        expected_depreciation = Decimal("1100.00") / Decimal(6000)
        expected_maintenance = Decimal("220.00") / Decimal(6000)
        expected_power = (Decimal("95.00") / Decimal("1000")) * Decimal("0.1300")

        assert Decimal(components["depreciation_per_hour"]) == expected_depreciation
        assert Decimal(components["maintenance_per_hour"]) == expected_maintenance
        assert Decimal(components["power_per_hour"]) == expected_power
        assert Decimal(body["machine_rate_per_hour"]) == (
            expected_depreciation + expected_maintenance + expected_power
        )
        assert body["missing"] == []

    async def test_a_partly_configured_policy_still_reports_what_it_knows(
        self, client: AsyncClient, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        """A known purchase price is a real cost even with power unmeasured."""
        test_printer.purchase_price = Decimal("1100.00")
        test_printer.expected_lifetime_hours = 6000
        await db_session.commit()

        body = (await client.get(_url(test_printer))).json()

        assert Decimal(body["machine_rate_per_hour"]) > 0
        assert "measured_watts" in body["missing"]

    async def test_the_tenant_electricity_rate_is_the_fallback(
        self, client: AsyncClient, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        """FR-011: a printer with no rate of its own uses the tenant policy's."""
        test_printer.purchase_price = Decimal("1100.00")
        test_printer.expected_lifetime_hours = 6000
        test_printer.measured_watts = Decimal("95.00")
        test_printer.electricity_rate_per_kwh = None
        await db_session.commit()

        without_policy = (await client.get(_url(test_printer))).json()
        assert "electricity_rate_per_kwh" in without_policy["missing"]

        await client.put(
            "/api/v1/settings/pricing-policy",
            json={"electricity_rate_per_kwh": "0.1300"},
        )

        with_policy = (await client.get(_url(test_printer))).json()
        assert "electricity_rate_per_kwh" not in with_policy["missing"]
        assert Decimal(with_policy["components"]["power_per_hour"]) == (
            Decimal("95.00") / Decimal("1000") * Decimal("0.1300")
        )

    async def test_money_crosses_the_wire_as_a_string(
        self, client: AsyncClient, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        test_printer.purchase_price = Decimal("1100.00")
        test_printer.expected_lifetime_hours = 6000
        await db_session.commit()

        body = (await client.get(_url(test_printer))).json()
        assert isinstance(body["machine_rate_per_hour"], str)
        assert isinstance(body["purchase_price"], str)

    @pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.VIEWER])
    async def test_every_role_may_read(
        self, as_role, role: UserRole, test_printer: Printer
    ) -> None:
        async with as_role(role) as ac:
            response = await ac.get(_url(test_printer))
        assert response.status_code == 200

    async def test_an_unknown_printer_is_a_404(self, client: AsyncClient) -> None:
        response = await client.get(f"/api/v1/printers/{uuid4()}/cost-policy")
        assert response.status_code == 404

    async def test_unauthenticated_is_refused(
        self, unauthenticated_client: AsyncClient, test_printer: Printer
    ) -> None:
        response = await unauthenticated_client.get(_url(test_printer))
        assert response.status_code == 401


# ============================================================================
# Writing
# ============================================================================


class TestWritingTheCostPolicy:
    async def test_an_admin_write_stores_the_policy_and_returns_the_rate(
        self, client: AsyncClient, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        response = await client.put(
            _url(test_printer),
            json={
                "purchase_price": "1100.00",
                "expected_lifetime_hours": 6000,
                "maintenance_reserve_total": "220.00",
                "measured_watts": "95.00",
                "electricity_rate_per_kwh": "0.1300",
            },
        )

        assert response.status_code == 200
        assert Decimal(response.json()["machine_rate_per_hour"]) > 0

        await db_session.refresh(test_printer)
        assert test_printer.purchase_price == Decimal("1100.00")
        assert test_printer.expected_lifetime_hours == 6000

    async def test_a_partial_write_leaves_untouched_fields_alone(
        self, client: AsyncClient, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        await client.put(
            _url(test_printer),
            json={"purchase_price": "1100.00", "expected_lifetime_hours": 6000},
        )
        await client.put(_url(test_printer), json={"measured_watts": "95.00"})

        await db_session.refresh(test_printer)
        assert test_printer.purchase_price == Decimal("1100.00")
        assert test_printer.measured_watts == Decimal("95.00")

    @pytest.mark.parametrize("role", [UserRole.MEMBER, UserRole.VIEWER])
    async def test_a_write_is_refused_for_member_and_viewer(
        self,
        as_role,
        role: UserRole,
        db_session: AsyncSession,
        test_printer: Printer,
    ) -> None:
        async with as_role(role) as ac:
            response = await ac.put(_url(test_printer), json={"purchase_price": "9999.00"})

        assert response.status_code == 403
        await db_session.refresh(test_printer)
        assert test_printer.purchase_price is None, (
            "a refused write must leave the figure untouched"
        )

    async def test_unauthenticated_write_is_refused(
        self, unauthenticated_client: AsyncClient, test_printer: Printer
    ) -> None:
        response = await unauthenticated_client.put(
            _url(test_printer), json={"purchase_price": "1100.00"}
        )
        assert response.status_code == 401

    async def test_a_zero_lifetime_is_refused(
        self, client: AsyncClient, test_printer: Printer
    ) -> None:
        """Depreciation over zero hours is a division, not a rate."""
        response = await client.put(
            _url(test_printer),
            json={"purchase_price": "1100.00", "expected_lifetime_hours": 0},
        )
        assert response.status_code == 422

    async def test_a_negative_purchase_price_is_refused(
        self, client: AsyncClient, test_printer: Printer
    ) -> None:
        response = await client.put(_url(test_printer), json={"purchase_price": "-1.00"})
        assert response.status_code == 422

    async def test_an_unknown_field_is_refused_rather_than_ignored(
        self, client: AsyncClient, test_printer: Printer
    ) -> None:
        response = await client.put(_url(test_printer), json={"watts": "95.00"})
        assert response.status_code == 422

    async def test_an_unknown_printer_is_a_404(self, client: AsyncClient) -> None:
        response = await client.put(
            f"/api/v1/printers/{uuid4()}/cost-policy", json={"purchase_price": "1100.00"}
        )
        assert response.status_code == 404
