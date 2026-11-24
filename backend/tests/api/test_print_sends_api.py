"""Print send API (spec 011, contracts/print-send-api.md).

Success, auth (401), role (403), validation (422) and not found (404) for each
endpoint, plus the confirmation codes. FTPS and MQTT are mocked.
"""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.print_job import PrintJob
from app.models.print_send import ConsumptionStatus, PrintSend
from app.models.printer import Printer
from app.models.tenant import Tenant
from app.models.user import UserRole
from tests.fixtures.print_sends import *  # noqa: F401,F403
from tests.fixtures.print_sends import ACCESS_CODE, GOOD_MAPPING, SAMPLE, WRONG_MAPPING

pytestmark = pytest.mark.asyncio


def _base(printer_id) -> str:
    return f"/api/v1/printers/{printer_id}"


def _form(mapping=GOOD_MAPPING, plate="1", **extra):
    data = {"plate": plate, "ams_mapping": json.dumps(mapping), **extra}
    files = {"file": ("dragon.gcode.3mf", SAMPLE, "model/3mf")}
    return data, files


async def _prepare(client: AsyncClient, printer_id, mapping=GOOD_MAPPING):
    data, files = _form(mapping)
    return await client.post(f"{_base(printer_id)}/prints/prepare", data=data, files=files)


# ============================================
# Prepare
# ============================================


class TestPrepare:
    async def test_201_with_token_and_summary(self, client, bambu_setup, wired, ftps):
        response = await _prepare(client, bambu_setup.printer.id)

        assert response.status_code == 201, response.text
        body = response.json()
        assert len(body["confirmation_token"]) >= 40
        assert body["plate"] == {
            "index": 1,
            "print_time_minutes": 95,
            "filament_weight_grams": "35.10",
        }
        assert body["lines"][0]["expected"]["grams"] == "30.10"
        assert body["requires_acknowledgement"] is False
        assert body["status"] == "prepared"
        ftps.upload.assert_not_called()

    async def test_401_without_auth(self, unauthenticated_client, bambu_setup):
        response = await _prepare(unauthenticated_client, bambu_setup.printer.id)
        assert response.status_code == 401

    async def test_403_for_viewer(self, as_role, bambu_setup, wired, ftps):
        async with as_role(UserRole.VIEWER) as viewer:
            response = await _prepare(viewer, bambu_setup.printer.id)
        assert response.status_code == 403

    @pytest.mark.parametrize(
        "data",
        [
            {"plate": "1", "ams_mapping": "not json"},
            {"plate": "1", "ams_mapping": json.dumps([{"filament_id": 1}])},
            {"plate": "0", "ams_mapping": json.dumps(GOOD_MAPPING)},
        ],
    )
    async def test_422_invalid_form(self, client, bambu_setup, wired, ftps, data):
        files = {"file": ("dragon.gcode.3mf", SAMPLE, "model/3mf")}
        response = await client.post(
            f"{_base(bambu_setup.printer.id)}/prints/prepare", data=data, files=files
        )
        assert response.status_code == 422

    async def test_422_both_or_no_source(self, client, bambu_setup, wired, ftps):
        url = f"{_base(bambu_setup.printer.id)}/prints/prepare"
        data, files = _form(model_file_id=str(uuid4()))
        assert (await client.post(url, data=data, files=files)).status_code == 422
        data, _ = _form()
        response = await client.post(url, data=data)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_source"

    async def test_413_file_too_large(self, client, bambu_setup, wired, ftps):
        with patch("app.services.print_send_service.MAX_FILE_SIZE", 10):
            response = await _prepare(client, bambu_setup.printer.id)
        assert response.status_code == 413

    async def test_404_unknown_printer(self, client, bambu_setup, wired, ftps):
        response = await _prepare(client, uuid4())
        assert response.status_code == 404

    async def test_404_other_tenants_printer(
        self, client, db_session: AsyncSession, bambu_setup, wired, ftps
    ):
        other = Tenant(id=uuid4(), name="Other", slug=f"other-{uuid4().hex[:6]}")
        db_session.add(other)
        printer = Printer(id=uuid4(), tenant_id=other.id, name="Theirs", is_active=True)
        db_session.add(printer)
        await db_session.commit()

        response = await _prepare(client, printer.id)
        assert response.status_code == 404

    async def test_409_developer_mode_off(self, client, db_session, bambu_setup, wired, ftps):
        bambu_setup.connection.developer_mode = False
        await db_session.commit()
        response = await _prepare(client, bambu_setup.printer.id)
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "send_not_available"


# ============================================
# Confirm
# ============================================


class TestConfirm:
    async def test_200_starts_print(self, client, db_session, bambu_setup, wired, ftps, test_user):
        token = (await _prepare(client, bambu_setup.printer.id)).json()["confirmation_token"]

        response = await client.post(
            f"{_base(bambu_setup.printer.id)}/prints/confirm",
            json={"confirmation_token": token},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "started"
        assert body["print_job"]["status"] == "printing"
        assert "confirmation_token" not in body
        assert body["confirmed_by"]["id"] == str(test_user.id)
        assert body["confirmed_by"]["name"]
        ftps.upload.assert_awaited_once()

    async def test_401(self, unauthenticated_client, bambu_setup):
        response = await unauthenticated_client.post(
            f"{_base(bambu_setup.printer.id)}/prints/confirm",
            json={"confirmation_token": "x" * 43},
        )
        assert response.status_code == 401

    async def test_403_for_viewer(self, client, as_role, bambu_setup, wired, ftps):
        token = (await _prepare(client, bambu_setup.printer.id)).json()["confirmation_token"]
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(
                f"{_base(bambu_setup.printer.id)}/prints/confirm",
                json={"confirmation_token": token},
            )
        assert response.status_code == 403
        ftps.upload.assert_not_called()

    @pytest.mark.parametrize(
        "body",
        [
            {"confirmation_token": "short"},
            {"confirmation_token": "x" * 43, "plate": 2},
            {"confirmation_token": "x" * 43, "ams_mapping": []},
        ],
    )
    async def test_422(self, client, bambu_setup, wired, ftps, body):
        response = await client.post(f"{_base(bambu_setup.printer.id)}/prints/confirm", json=body)
        assert response.status_code == 422

    async def test_404_unknown_token(self, client, bambu_setup, wired, ftps):
        response = await client.post(
            f"{_base(bambu_setup.printer.id)}/prints/confirm",
            json={"confirmation_token": "x" * 43},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "send_not_found"

    async def test_409_acknowledgement_then_already_used(self, client, bambu_setup, wired, ftps):
        token = (await _prepare(client, bambu_setup.printer.id, WRONG_MAPPING)).json()[
            "confirmation_token"
        ]
        url = f"{_base(bambu_setup.printer.id)}/prints/confirm"

        first = await client.post(url, json={"confirmation_token": token})
        assert first.status_code == 409
        assert first.json()["detail"]["code"] == "acknowledgement_required"

        second = await client.post(
            url, json={"confirmation_token": token, "acknowledge_warnings": True}
        )
        assert second.status_code == 200
        assert second.json()["warnings_acknowledged"] is True

        third = await client.post(
            url, json={"confirmation_token": token, "acknowledge_warnings": True}
        )
        assert third.status_code == 409
        assert third.json()["detail"]["code"] == "send_already_used"

    async def test_410_expired(self, client, bambu_setup, wired, ftps):
        from datetime import timedelta

        from app.core import clock

        token = (await _prepare(client, bambu_setup.printer.id)).json()["confirmation_token"]
        later = clock.now() + timedelta(minutes=6)
        with patch("app.services.print_send_service.clock.now", return_value=later):
            response = await client.post(
                f"{_base(bambu_setup.printer.id)}/prints/confirm",
                json={"confirmation_token": token},
            )
        assert response.status_code == 410

    async def test_502_transfer_failed(self, client, db_session, bambu_setup, wired, ftps):
        from app.services.bambu_ftps import BambuFileTransferError

        token = (await _prepare(client, bambu_setup.printer.id)).json()["confirmation_token"]
        ftps.upload.side_effect = BambuFileTransferError("The printer did not answer in time")
        response = await client.post(
            f"{_base(bambu_setup.printer.id)}/prints/confirm",
            json={"confirmation_token": token},
        )
        assert response.status_code == 502
        assert response.json()["detail"]["code"] == "transfer_failed"
        assert ACCESS_CODE not in response.text
        assert (await db_session.execute(select(func.count(PrintJob.id)))).scalar() == 0

    async def test_503_unreachable(self, client, bambu_setup, wired, ftps):
        token = (await _prepare(client, bambu_setup.printer.id)).json()["confirmation_token"]
        wired.state = None
        response = await client.post(
            f"{_base(bambu_setup.printer.id)}/prints/confirm",
            json={"confirmation_token": token},
        )
        assert response.status_code == 503


# ============================================
# Reads
# ============================================


class TestReads:
    async def test_list_and_get_without_token(self, client, bambu_setup, wired, ftps):
        prepared = (await _prepare(client, bambu_setup.printer.id)).json()

        listing = await client.get(f"{_base(bambu_setup.printer.id)}/prints")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert [item["id"] for item in items] == [prepared["id"]]
        assert "confirmation_token" not in items[0]
        assert items[0]["consumption"] == {"status": "none", "lines": [], "decided_at": None}

        single = await client.get(f"{_base(bambu_setup.printer.id)}/prints/{prepared['id']}")
        assert single.status_code == 200
        assert single.json()["file"]["name"] == "dragon.gcode.3mf"

    async def test_401(self, unauthenticated_client, bambu_setup):
        response = await unauthenticated_client.get(f"{_base(bambu_setup.printer.id)}/prints")
        assert response.status_code == 401

    async def test_422_limit(self, client, bambu_setup):
        response = await client.get(f"{_base(bambu_setup.printer.id)}/prints?limit=0")
        assert response.status_code == 422

    async def test_404(self, client, bambu_setup):
        assert (await client.get(f"{_base(uuid4())}/prints")).status_code == 404
        response = await client.get(f"{_base(bambu_setup.printer.id)}/prints/{uuid4()}")
        assert response.status_code == 404

    async def test_other_tenants_sends_hidden(
        self, client, db_session, bambu_setup, wired, ftps, test_tenant
    ):
        prepared = (await _prepare(client, bambu_setup.printer.id)).json()
        send = (
            await db_session.execute(select(PrintSend).where(PrintSend.id == prepared["id"]))
        ).scalar_one()
        other = Tenant(id=uuid4(), name="Other", slug=f"other-{uuid4().hex[:6]}")
        db_session.add(other)
        await db_session.flush()
        send.tenant_id = other.id
        await db_session.commit()

        listing = await client.get(f"{_base(bambu_setup.printer.id)}/prints")
        assert listing.json()["items"] == []


# ============================================
# Deduction proposal
# ============================================


async def _pending(client, db_session, setup) -> str:
    token = (await _prepare(client, setup.printer.id)).json()["confirmation_token"]
    send_id = (
        await client.post(
            f"{_base(setup.printer.id)}/prints/confirm", json={"confirmation_token": token}
        )
    ).json()["id"]
    send = (await db_session.execute(select(PrintSend).where(PrintSend.id == send_id))).scalar_one()
    send.consumption_status = ConsumptionStatus.PENDING.value
    send.consumption_lines = [
        {
            "filament_id": 1,
            "spool_id": str(setup.pla_spool.id),
            "proposed_grams": "30.10",
            "accepted_grams": None,
            "transaction_id": None,
        }
    ]
    await db_session.commit()
    return send_id


class TestConsumption:
    async def test_accept_then_conflict(self, client, db_session, bambu_setup, wired, ftps):
        send_id = await _pending(client, db_session, bambu_setup)
        url = f"{_base(bambu_setup.printer.id)}/prints/{send_id}/consumption/accept"
        body = {
            "lines": [
                {"filament_id": 1, "spool_id": str(bambu_setup.pla_spool.id), "grams": "28.50"}
            ]
        }

        response = await client.post(url, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["consumption"]["status"] == "accepted"
        assert response.json()["consumption"]["lines"][0]["accepted_grams"] == "28.50"

        again = await client.post(url, json=body)
        assert again.status_code == 409

    async def test_dismiss(self, client, db_session, bambu_setup, wired, ftps):
        send_id = await _pending(client, db_session, bambu_setup)
        response = await client.post(
            f"{_base(bambu_setup.printer.id)}/prints/{send_id}/consumption/dismiss"
        )
        assert response.status_code == 200
        assert response.json()["consumption"]["status"] == "dismissed"

    @pytest.mark.parametrize("grams", ["0", "-1", "abc"])
    async def test_422_grams(self, client, db_session, bambu_setup, wired, ftps, grams):
        send_id = await _pending(client, db_session, bambu_setup)
        response = await client.post(
            f"{_base(bambu_setup.printer.id)}/prints/{send_id}/consumption/accept",
            json={
                "lines": [
                    {"filament_id": 1, "spool_id": str(bambu_setup.pla_spool.id), "grams": grams}
                ]
            },
        )
        assert response.status_code == 422

    async def test_422_foreign_spool(self, client, db_session, bambu_setup, wired, ftps):
        send_id = await _pending(client, db_session, bambu_setup)
        response = await client.post(
            f"{_base(bambu_setup.printer.id)}/prints/{send_id}/consumption/accept",
            json={"lines": [{"filament_id": 1, "spool_id": str(uuid4()), "grams": "1.00"}]},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "spool_not_found"

    async def test_401(self, unauthenticated_client, bambu_setup):
        url = f"{_base(bambu_setup.printer.id)}/prints/{uuid4()}/consumption/dismiss"
        assert (await unauthenticated_client.post(url)).status_code == 401

    async def test_404(self, client, bambu_setup):
        url = f"{_base(bambu_setup.printer.id)}/prints/{uuid4()}/consumption/dismiss"
        assert (await client.post(url)).status_code == 404


# ============================================
# Developer Mode: connection fields and transfer test
# ============================================


class TestConnection:
    async def test_connection_persists_developer_mode(self, client, test_printer):
        url = f"{_base(test_printer.id)}/connection"
        created = await client.post(
            url,
            json={
                "connection_type": "bambu_lan",
                "serial_number": "01S00C123456789",
                "ip_address": "192.168.1.50",
                "access_code": ACCESS_CODE,
                "developer_mode": True,
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["developer_mode"] is True
        assert body["can_send_prints"] is True
        assert ACCESS_CODE not in created.text

        updated = await client.post(
            url, json={"connection_type": "bambu_lan", "developer_mode": False}
        )
        assert updated.json()["can_send_prints"] is False

    async def test_transfer_test_ok_and_refused(self, client, bambu_setup):
        url = f"{_base(bambu_setup.printer.id)}/connection/test-file-transfer"
        with patch(
            "app.api.v1.print_sends.bambu_ftps.check_login",
            new_callable=AsyncMock,
            return_value=(True, "The printer accepted the file connection"),
        ) as check:
            response = await client.post(url)
        assert response.json() == {
            "ok": True,
            "message": "The printer accepted the file connection",
        }
        check.assert_awaited_once_with("192.168.1.50", ACCESS_CODE)

        with patch(
            "app.api.v1.print_sends.bambu_ftps.check_login",
            new_callable=AsyncMock,
            return_value=(False, "Login refused: check the access code"),
        ):
            response = await client.post(url)
        assert response.status_code == 200
        assert response.json()["ok"] is False

    async def test_transfer_test_401(self, unauthenticated_client, bambu_setup):
        url = f"{_base(bambu_setup.printer.id)}/connection/test-file-transfer"
        assert (await unauthenticated_client.post(url)).status_code == 401

    async def test_transfer_test_404_409(self, client, db_session, bambu_setup):
        url = f"{_base(bambu_setup.printer.id)}/connection/test-file-transfer"
        assert (
            await client.post(f"{_base(uuid4())}/connection/test-file-transfer")
        ).status_code == 404
        bambu_setup.connection.connection_type = "moonraker"
        await db_session.commit()
        assert (await client.post(url)).status_code == 409

    async def test_connect_passes_tenant_and_accessor(self, client, bambu_setup, test_tenant):
        with patch("app.api.v1.printer_bambu.get_bambu_mqtt_service") as factory:
            factory.return_value.connect = AsyncMock(return_value=True)
            response = await client.post(f"{_base(bambu_setup.printer.id)}/connection/connect")
        assert response.status_code == 200, response.text
        config = factory.return_value.connect.await_args.args[0]
        assert config.tenant_id == test_tenant.id
        assert config.access_code == ACCESS_CODE
