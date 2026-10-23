"""`POST /printers/{id}/power-readings` — a measured draw gets a way in (task T159).

`printers.measured_watts` is the one cost input where a cheap sensor beats any
estimate, and the ingestion that turns a reading into an observed figure was
written, tested and left with no caller: no endpoint, no schedule, nothing in
`app/`. So the figure could never acquire an observed origin and the
power-draw share SC-010 counts was unreachable in a running system.

These tests pin the route and, more importantly, the rule that a reading does
not simply overwrite the figure (FR-042a, FR-042b, FR-042g).
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
    return f"/api/v1/printers/{printer.id}/power-readings"


def _readings(*watts: str) -> dict:
    return {
        "readings": [
            {"source_id": f"plug-{index}", "watts": value, "observed_on": "2026-10-01"}
            for index, value in enumerate(watts)
        ]
    }


class TestRecordingReadings:
    async def test_enough_agreeing_readings_update_the_draw(
        self, client: AsyncClient, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        """FR-042a: a rolling average once the minimum is reached."""
        test_printer.measured_watts = Decimal("95.00")
        await db_session.commit()

        response = await client.post(
            _url(test_printer),
            json=_readings("94.0", "96.0", "95.0", "97.0", "93.0"),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["printer_id"] == str(test_printer.id)
        assert body["readings_accepted"] == 5
        assert body["applied"] is True, body["reason"]

        await db_session.refresh(test_printer)
        assert test_printer.measured_watts == Decimal("95.00")

    async def test_a_wildly_divergent_reading_is_held_rather_than_applied(
        self, client: AsyncClient, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        """FR-042b: a plug reporting kilowatts must not reprice the machine."""
        test_printer.measured_watts = Decimal("95.00")
        await db_session.commit()

        response = await client.post(
            _url(test_printer),
            json=_readings("950.0", "960.0", "940.0", "955.0", "945.0"),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["applied"] is False
        assert body["reason"]

        await db_session.refresh(test_printer)
        assert test_printer.measured_watts == Decimal("95.00"), (
            "pricing must keep using the current estimate while a proposal is pending (FR-042e)"
        )

    async def test_the_figure_crosses_the_wire_as_a_decimal_string(
        self, client: AsyncClient, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        """Constitution IV: a draw is multiplied by an electricity rate."""
        test_printer.measured_watts = Decimal("95.00")
        await db_session.commit()

        response = await client.post(_url(test_printer), json=_readings("95.5", "95.5"))

        assert response.status_code == 200
        body = response.json()
        if body["observed_value"] is not None:
            assert isinstance(body["observed_value"], str)
        if body["measured_watts"] is not None:
            assert isinstance(body["measured_watts"], str)


class TestRefusals:
    async def test_unauthenticated_is_refused(
        self, unauthenticated_client: AsyncClient, test_printer: Printer
    ) -> None:
        response = await unauthenticated_client.post(_url(test_printer), json=_readings("95.0"))
        assert response.status_code == 401

    async def test_an_unknown_printer_is_not_found(self, client: AsyncClient) -> None:
        response = await client.post(
            f"/api/v1/printers/{uuid4()}/power-readings", json=_readings("95.0")
        )
        assert response.status_code == 404

    async def test_an_empty_batch_is_rejected(
        self, client: AsyncClient, test_printer: Printer
    ) -> None:
        response = await client.post(_url(test_printer), json={"readings": []})
        assert response.status_code == 422

    async def test_a_negative_draw_is_rejected(
        self, client: AsyncClient, test_printer: Printer
    ) -> None:
        response = await client.post(
            _url(test_printer),
            json={"readings": [{"source_id": "plug-0", "watts": "-5"}]},
        )
        assert response.status_code == 422


class TestRole:
    async def test_a_member_may_record_a_reading(
        self, as_role, db_session: AsyncSession, test_printer: Printer
    ) -> None:
        """FR-007b: a measured draw is a measurement, not monetary policy."""
        test_printer.measured_watts = Decimal("95.00")
        await db_session.commit()

        async with as_role(UserRole.MEMBER) as member_client:
            response = await member_client.post(_url(test_printer), json=_readings("95.0", "95.0"))

        assert response.status_code == 200, response.text
