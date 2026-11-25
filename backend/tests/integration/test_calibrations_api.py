"""Fit calibrations per printer and material (spec 009, User Story 3).

A value is recorded, never edited: recording again for the same combination
supersedes the current value and keeps the old one readable. The lookup gives
the filament's value, else the material's, else nothing (research R6).
"""

import os
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calibration import Calibration
from app.models.printer import Printer
from app.models.user import User, UserRole
from tests.api_token_helpers import bearer, make_token
from tests.utils.ideas import other_tenant

PRINTERS = "/api/v1/printers"
CALIBRATIONS = "/api/v1/calibrations"
SLIDE = {
    "fit_type": "slide",
    "orientation": "vertical",
    "value_mm": "0.15",
    "provenance": "measured",
    "material": "PLA",
}


async def _record(client: AsyncClient, printer_id, **overrides) -> dict:
    response = await client.post(
        f"{PRINTERS}/{printer_id}/calibrations", json={**SLIDE, **overrides}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _lookup(client: AsyncClient, printer_id, **params) -> dict:
    query = {"printer_id": str(printer_id), "fit_type": "slide", "orientation": "vertical"}
    response = await client.get(f"{CALIBRATIONS}/lookup", params={**query, **params})
    assert response.status_code == 200, response.text
    return response.json()


class TestRecord:
    async def test_record_returns_an_exact_value(
        self, client: AsyncClient, test_printer, test_material_type
    ):
        body = await _record(client, test_printer.id, notes="Peigne de jeux, 3 essais")
        assert body["value_mm"] == "0.150"
        assert body["material_type_id"] == str(test_material_type.id)
        assert body["material_code"] == "PLA"
        assert body["printer_name"] == test_printer.name
        assert body["is_current"] is True and body["superseded_by_id"] is None
        assert body["recorded_by"]["name"] == "Test User"
        assert body["measured_at"] is not None

    async def test_recording_again_supersedes_and_keeps_history(
        self, client: AsyncClient, test_printer
    ):
        first = await _record(client, test_printer.id)
        second = await _record(client, test_printer.id, value_mm=0.2)
        assert second["value_mm"] == "0.200"

        old = (await client.get(f"{CALIBRATIONS}/{first['id']}")).json()
        assert old["superseded_by_id"] == second["id"]
        assert old["superseded_at"] is not None and old["is_current"] is False
        assert old["value_mm"] == "0.150"

        listed = (await client.get(f"{PRINTERS}/{test_printer.id}/calibrations")).json()
        assert [c["id"] for c in listed] == [second["id"], first["id"]]
        current = (
            await client.get(
                f"{PRINTERS}/{test_printer.id}/calibrations", params={"current_only": True}
            )
        ).json()
        assert [c["id"] for c in current] == [second["id"]]

    async def test_other_combinations_stay_current(
        self, client: AsyncClient, test_printer, test_filament_type
    ):
        slide = await _record(client, test_printer.id)
        await _record(client, test_printer.id, orientation="horizontal")
        await _record(client, test_printer.id, fit_type="press", value_mm="0.05")
        await _record(client, test_printer.id, filament_type_id=str(test_filament_type.id))
        assert (await client.get(f"{CALIBRATIONS}/{slide['id']}")).json()["is_current"]

    @pytest.mark.parametrize(
        "bad",
        [
            {"value_mm": "2.5"},
            {"value_mm": "-0.1"},
            {"value_mm": "0.1234"},
            {"fit_type": "glued"},
            {"orientation": "diagonal"},
            {"provenance": "guessed"},
            {"material": None},
            {"material_type_id": str(uuid.uuid4())},
            {"material": "UNOBTAINIUM"},
            {"notes": "x" * 2001},
        ],
    )
    async def test_bad_values_are_422(self, client: AsyncClient, test_printer, bad):
        response = await client.post(
            f"{PRINTERS}/{test_printer.id}/calibrations", json={**SLIDE, **bad}
        )
        assert response.status_code == 422, response.text

    async def test_filament_of_another_material_is_422(
        self, client: AsyncClient, test_printer, test_filament_type
    ):
        response = await client.post(
            f"{PRINTERS}/{test_printer.id}/calibrations",
            json={**SLIDE, "material": "PETG", "filament_type_id": str(test_filament_type.id)},
        )
        assert response.status_code == 422

    async def test_unknown_printer_job_or_result_is_404(self, client: AsyncClient, test_printer):
        assert (
            await client.post(f"{PRINTERS}/{uuid.uuid4()}/calibrations", json=SLIDE)
        ).status_code == 404
        for field in ("source_print_job_id", "source_test_result_id", "filament_type_id"):
            response = await client.post(
                f"{PRINTERS}/{test_printer.id}/calibrations",
                json={**SLIDE, field: str(uuid.uuid4())},
            )
            assert response.status_code == 404, field

    async def test_no_route_edits_or_deletes(self, client: AsyncClient, test_printer):
        body = await _record(client, test_printer.id)
        for method in ("PUT", "PATCH", "DELETE"):
            response = await client.request(
                method, f"{CALIBRATIONS}/{body['id']}", json={"value_mm": "0.3"}
            )
            assert response.status_code == 405, method

    @pytest.mark.skipif(
        "postgres" not in os.environ.get("DATABASE_URL", ""),
        reason="the immutability trigger is PostgreSQL only",
    )
    async def test_database_refuses_an_edit(
        self, client: AsyncClient, db_session: AsyncSession, test_printer
    ):
        """Principle VI: the trigger keeps a recorded value as it was."""
        body = await _record(client, test_printer.id)
        with pytest.raises(DBAPIError):
            await db_session.execute(
                update(Calibration)
                .where(Calibration.id == uuid.UUID(body["id"]))
                .values(notes="edited")
            )
        await db_session.rollback()


class TestLookup:
    async def test_filament_beats_material_beats_nothing(
        self, client: AsyncClient, test_printer, test_filament_type
    ):
        filament = {"material": "PLA", "filament_type_id": str(test_filament_type.id)}
        assert await _lookup(client, test_printer.id, **filament) == {
            "found": False,
            "calibration": None,
            "matched_on": None,
        }

        material = await _record(client, test_printer.id)
        found = await _lookup(client, test_printer.id, **filament)
        assert (found["matched_on"], found["calibration"]["id"]) == ("material", material["id"])

        own = await _record(
            client, test_printer.id, value_mm="0.12", filament_type_id=str(test_filament_type.id)
        )
        found = await _lookup(client, test_printer.id, **filament)
        assert (found["matched_on"], found["calibration"]["id"]) == ("filament", own["id"])
        assert found["calibration"]["filament_label"] == "Test Brand Red"

        by_filament_only = await _lookup(
            client, test_printer.id, filament_type_id=str(test_filament_type.id)
        )
        assert by_filament_only["calibration"]["id"] == own["id"]
        lower_case = await _lookup(client, test_printer.id, material="pla")
        assert lower_case["calibration"]["id"] == material["id"]

    async def test_lookup_returns_only_the_current_value(self, client: AsyncClient, test_printer):
        await _record(client, test_printer.id)
        newer = await _record(client, test_printer.id, value_mm="0.18")
        assert (await _lookup(client, test_printer.id, material="PLA"))["calibration"][
            "id"
        ] == newer["id"]

    async def test_lookup_needs_a_material(self, client: AsyncClient, test_printer):
        response = await client.get(
            f"{CALIBRATIONS}/lookup",
            params={
                "printer_id": str(test_printer.id),
                "fit_type": "slide",
                "orientation": "vertical",
            },
        )
        assert response.status_code == 422


class TestAtelierExport:
    async def test_current_values_in_atelier_shape(self, client: AsyncClient, test_printer):
        await _record(client, test_printer.id)
        current = await _record(client, test_printer.id, value_mm="0.175")
        await _record(
            client, test_printer.id, fit_type="snap", value_mm="0.3", provenance="assumed"
        )

        exported = (await client.get(f"{CALIBRATIONS}/atelier")).json()["calibrations"]
        assert len(exported) == 2
        slide = next(c for c in exported if c["fit"] == "slide")
        assert slide == {
            "id": current["id"],
            "printer": test_printer.name,
            "printer_id": str(test_printer.id),
            "material": "PLA",
            "filament": None,
            "orientation": "vertical",
            "fit": "slide",
            "value_mm": "0.175",
            "provenance": "measured",
            "measured_at": slide["measured_at"],
            "source_print_job_id": None,
        }
        by_printer = await client.get(
            f"{CALIBRATIONS}/atelier", params={"printer_id": str(test_printer.id)}
        )
        assert len(by_printer.json()["calibrations"]) == 2
        unknown = await client.get(
            f"{CALIBRATIONS}/atelier", params={"printer_id": str(uuid.uuid4())}
        )
        assert unknown.status_code == 404


class TestAccess:
    async def test_other_tenant_printer_is_404(self, client: AsyncClient, db_session: AsyncSession):
        theirs = await other_tenant(db_session)
        printer = Printer(id=uuid.uuid4(), tenant_id=theirs.id, name="Their printer")
        db_session.add(printer)
        await db_session.commit()
        assert (
            await client.post(f"{PRINTERS}/{printer.id}/calibrations", json=SLIDE)
        ).status_code == 404
        assert (await client.get(f"{PRINTERS}/{printer.id}/calibrations")).status_code == 404
        response = await client.get(
            f"{CALIBRATIONS}/lookup",
            params={
                "printer_id": str(printer.id),
                "fit_type": "slide",
                "orientation": "vertical",
                "material": "PLA",
            },
        )
        assert response.status_code == 404

    async def test_signed_out_is_401(self, unauthenticated_client: AsyncClient):
        response = await unauthenticated_client.get(f"{CALIBRATIONS}/atelier")
        assert response.status_code == 401

    async def test_viewer_reads_but_does_not_record(
        self, client: AsyncClient, test_printer, as_role
    ):
        await _record(client, test_printer.id)
        async with as_role(UserRole.VIEWER) as viewer:
            listed = await viewer.get(f"{PRINTERS}/{test_printer.id}/calibrations")
            assert listed.status_code == 200 and len(listed.json()) == 1
            refused = await viewer.post(f"{PRINTERS}/{test_printer.id}/calibrations", json=SLIDE)
            assert refused.status_code == 403

    async def test_tokens(
        self,
        unauthenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_tenant,
        test_user: User,
        test_printer,
    ):
        _, reader = await make_token(db_session, test_tenant, test_user, ["read"])
        _, writer = await make_token(db_session, test_tenant, test_user, ["read", "write"])
        url = f"{PRINTERS}/{test_printer.id}/calibrations"
        refused = await unauthenticated_client.post(url, json=SLIDE, headers=bearer(reader))
        assert refused.status_code == 403
        recorded = await unauthenticated_client.post(url, json=SLIDE, headers=bearer(writer))
        assert recorded.status_code == 201, recorded.text
        exported = await unauthenticated_client.get(
            f"{CALIBRATIONS}/atelier", headers=bearer(reader)
        )
        assert exported.status_code == 200
        rows = (await db_session.execute(select(Calibration))).scalars().all()
        assert len(rows) == 1
