"""PrintSendService (spec 011): mismatch rules, prepare, confirm, deduction proposal.

FTPS and MQTT are always mocked (tests/fixtures/print_sends.py).
"""

import logging
import pathlib
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.utils.model_files import active_version_id
from app.core import clock
from app.models.inventory_transaction import InventoryTransaction
from app.models.model_file import ModelFile
from app.models.print_job import JobStatus, PrintJob
from app.models.print_send import ConsumptionStatus, PrintSend, PrintSendStatus
from app.models.spool import Spool
from app.schemas.print_send import AmsMapping, ConsumptionAcceptLine
from app.services.bambu_ftps import BambuFileTransferError
from app.services.print_send_service import (
    PrintSendError,
    PrintSendService,
    SlotFacts,
    colors_differ,
    command_ams_mapping,
    line_warnings,
    material_key,
)
from tests.fixtures.print_sends import *  # noqa: F401,F403
from tests.fixtures.print_sends import (
    ACCESS_CODE,
    GOOD_MAPPING,
    SAMPLE,
    WRONG_MAPPING,
    idle_state,
)
from tests.fixtures.sliced_3mf import unsliced_project

pytestmark = pytest.mark.asyncio


# ============================================
# Mismatch rules (research R9)
# ============================================


class TestMismatchRules:
    def test_material_key(self):
        assert material_key("PLA Basic") == "PLA"
        assert material_key("pla-cf") == "PLA-CF"
        assert material_key(None) is None
        assert material_key("  ") is None

    def test_colour_distance_threshold(self):
        assert colors_differ("#000000", "#500000") is False  # distance 80
        assert colors_differ("#000000", "#510000") is True  # distance 81
        assert colors_differ("#FF0000", None) is False
        assert colors_differ("#FF0000FF", "FF0000") is False

    def test_material_and_colour_mismatch(self):
        facts = SlotFacts(
            kind="ams", spool_known=True, spool_material="PETG", spool_color="#00FF00"
        )
        assert line_warnings("PLA", "#FF0000", facts) == ["material_mismatch", "color_mismatch"]

    def test_pla_cf_is_not_pla(self):
        facts = SlotFacts(kind="ams", spool_known=True, spool_material="PLA-CF")
        assert line_warnings("PLA", None, facts) == ["material_mismatch"]

    def test_unknown_spool_and_empty_slot(self):
        facts = SlotFacts(kind="ams", spool_known=False, reported_present=False)
        assert line_warnings("PLA", "#FF0000", facts) == ["unknown_spool", "empty_slot"]

    def test_reported_mismatch(self):
        facts = SlotFacts(
            kind="ams",
            spool_known=True,
            spool_material="PLA",
            spool_color="#FF0000",
            reported_present=True,
            reported_type="PETG",
            reported_color="FF0000FF",
        )
        assert line_warnings("PLA", "#FF0000", facts) == ["reported_mismatch"]

    def test_external_spool_has_no_ams_check(self):
        assert line_warnings("PLA", "#FF0000", SlotFacts(kind="external", spool_known=False)) == []

    def test_command_mapping(self):
        entries = [
            {"filament_id": 1, "slot": {"kind": "ams", "ams_id": 0, "tray_id": 2}},
            {"filament_id": 3, "slot": {"kind": "external"}},
            {"filament_id": 4, "slot": {"kind": "ams", "ams_id": 1, "tray_id": 3}},
        ]
        assert command_ams_mapping(entries) == [2, -1, 254, 7]


# ============================================
# Prepare (US1)
# ============================================


async def _prepare(db, tenant, user, setup, mapping=GOOD_MAPPING, **kwargs):
    service = PrintSendService(db, tenant, user)
    kwargs.setdefault("upload_name", "dragon.gcode.3mf")
    kwargs.setdefault("upload_content", SAMPLE)
    return await service.prepare(
        setup.printer.id,
        plate=kwargs.pop("plate", 1),
        mapping=AmsMapping(entries=mapping),
        **kwargs,
    )


class TestPrepare:
    async def test_summary_content(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        send, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)

        assert len(token) >= 40
        summary = send.summary
        assert summary["printer"]["name"] == bambu_setup.printer.name
        assert summary["file"]["name"] == "dragon.gcode.3mf"
        assert summary["plate"] == {
            "index": 1,
            "print_time_minutes": 95,
            "filament_weight_grams": "35.10",
        }
        first, second = summary["lines"]
        assert first["expected"] == {"type": "PLA", "color": "#FF0000", "grams": "30.10"}
        assert first["slot"]["label"] == "AMS 1 · slot 1"
        assert first["mapped_spool"]["spool_id"] == "SP-PLA"
        assert first["reported"] == {"type": "PLA", "color": "#FF0000", "present": True}
        assert first["warnings"] == []
        assert second["mapped_spool"]["material"] == "PETG"
        assert summary["warnings"] == [] and summary["blockers"] == []
        assert send.warning_count == 0
        assert send.status == PrintSendStatus.PREPARED.value
        assert send.token_hash != token
        assert send.remote_file_name == f"batchivo-{send.id.hex[:8]}.gcode.3mf"
        expires_in = send.expires_at - send.created_at
        assert timedelta(minutes=4) < expires_in <= timedelta(minutes=5, seconds=5)

    async def test_nothing_reaches_the_printer_and_no_job(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        await _prepare(db_session, test_tenant, test_user, bambu_setup)

        ftps.upload.assert_not_called()
        assert wired.start_calls == []
        assert (await db_session.execute(select(func.count(PrintJob.id)))).scalar() == 0

    async def test_mismatch_requires_acknowledgement(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        send, _ = await _prepare(db_session, test_tenant, test_user, bambu_setup, WRONG_MAPPING)

        codes = {(w["filament_id"], w["code"]) for w in send.summary["warnings"]}
        assert (1, "material_mismatch") in codes
        assert (1, "reported_mismatch") in codes
        assert send.warning_count >= 2

    async def test_unsliced_file_refused(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        with pytest.raises(PrintSendError) as excinfo:
            await _prepare(
                db_session, test_tenant, test_user, bambu_setup, upload_content=unsliced_project()
            )
        assert excinfo.value.status_code == 422 and excinfo.value.code == "not_sliced"
        assert (await db_session.execute(select(func.count(PrintSend.id)))).scalar() == 0

    async def test_unknown_plate_lists_available(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        with pytest.raises(PrintSendError) as excinfo:
            await _prepare(db_session, test_tenant, test_user, bambu_setup, plate=3)
        assert excinfo.value.code == "plate_not_found"
        assert "1, 2" in excinfo.value.message

    async def test_mapping_must_cover_the_plate(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        with pytest.raises(PrintSendError) as excinfo:
            await _prepare(db_session, test_tenant, test_user, bambu_setup, GOOD_MAPPING[:1])
        assert excinfo.value.code == "mapping_mismatch"

    def test_same_slot_twice_is_invalid(self):
        with pytest.raises(ValueError):
            AmsMapping(
                entries=[
                    {"filament_id": 1, "slot": {"kind": "ams", "ams_id": 0, "tray_id": 0}},
                    {"filament_id": 3, "slot": {"kind": "ams", "ams_id": 0, "tray_id": 0}},
                ]
            )

    async def test_developer_mode_off_refused(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        bambu_setup.connection.developer_mode = False
        await db_session.commit()
        with pytest.raises(PrintSendError) as excinfo:
            await _prepare(db_session, test_tenant, test_user, bambu_setup)
        assert excinfo.value.status_code == 409 and excinfo.value.code == "send_not_available"

    async def test_printer_not_connected_marks_reports_unknown(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        wired.state = None
        send, _ = await _prepare(db_session, test_tenant, test_user, bambu_setup)

        assert all(line["reported"] is None for line in send.summary["lines"])
        assert [b["code"] for b in send.summary["blockers"]] == ["printer_unreachable"]

    async def test_busy_printer_is_a_blocker(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        wired.state = idle_state("RUNNING")
        send, _ = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        assert [b["code"] for b in send.summary["blockers"]] == ["printer_busy"]

    async def test_upload_stored_then_cleaned_when_expired(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps, memory_uploads
    ):
        first, _ = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        assert first.upload_url in memory_uploads.files

        later = clock.now() + timedelta(minutes=6)
        with patch("app.services.print_send_service.clock.now", return_value=later):
            await _prepare(db_session, test_tenant, test_user, bambu_setup)

        await db_session.refresh(first)
        assert first.upload_url is None
        assert len(memory_uploads.files) == 1

    async def test_attach_upload_to_model(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps, test_model, tmp_path
    ):
        with patch("app.services.model_file_service.ModelFileService._save_local") as save:
            save.return_value = "/uploads/models/x/dragon.gcode.3mf"
            send, _ = await _prepare(
                db_session, test_tenant, test_user, bambu_setup, attach_to_model_id=test_model.id
            )

        stored = (
            await db_session.execute(select(ModelFile).where(ModelFile.id == send.model_file_id))
        ).scalar_one()
        assert stored.model_id == test_model.id
        assert send.model_id == test_model.id
        assert send.upload_url is None

    async def test_stored_model_file_source(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps, test_model
    ):
        file_id = uuid4()
        fake_file = ModelFile(
            id=file_id,
            tenant_id=test_tenant.id,
            model_id=test_model.id,
            version_id=await active_version_id(db_session, test_tenant.id, test_model.id),
            file_type="slicer_project",
            is_sliced=True,
            original_filename="stored.gcode.3mf",
        )
        db_session.add(fake_file)
        await db_session.commit()
        with (
            patch(
                "app.services.model_file_service.ModelFileService.get_file", return_value=fake_file
            ),
            patch(
                "app.services.model_file_service.ModelFileService.get_file_content",
                return_value=(SAMPLE, "model/3mf", "stored.gcode.3mf"),
            ),
        ):
            service = PrintSendService(db_session, test_tenant, test_user)
            send, _ = await service.prepare(
                bambu_setup.printer.id,
                plate=1,
                mapping=AmsMapping(entries=GOOD_MAPPING),
                model_file_id=file_id,
            )
        assert send.model_file_id == file_id
        assert send.model_id == test_model.id
        assert send.summary["file"]["name"] == "stored.gcode.3mf"

    async def test_both_or_no_source_refused(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        service = PrintSendService(db_session, test_tenant, test_user)
        with pytest.raises(PrintSendError) as excinfo:
            await service.prepare(
                bambu_setup.printer.id, plate=1, mapping=AmsMapping(entries=GOOD_MAPPING)
            )
        assert excinfo.value.code == "invalid_source"


# ============================================
# Confirm (US2)
# ============================================


async def _confirm(db, tenant, user, setup, token, ack=False):
    service = PrintSendService(db, tenant, user)
    return await service.confirm(setup.printer.id, token, acknowledge_warnings=ack)


class TestConfirm:
    async def test_happy_path(self, db_session, test_tenant, test_user, bambu_setup, wired, ftps):
        prepared, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)

        send = await _confirm(db_session, test_tenant, test_user, bambu_setup, token)

        ftps.upload.assert_awaited_once()
        host, code, remote, data = ftps.upload.await_args.args
        assert (host, code, remote, data) == (
            "192.168.1.50",
            ACCESS_CODE,
            prepared.remote_file_name,
            SAMPLE,
        )
        assert wired.start_calls == [
            {
                "printer_id": bambu_setup.printer.id,
                "remote_file_name": prepared.remote_file_name,
                "plate_index": 1,
                "ams_mapping": [0, -1, 1],
                "md5": prepared.file_md5,
            }
        ]
        assert send.status == PrintSendStatus.STARTED.value
        assert send.confirmed_by_user_id == test_user.id
        assert send.upload_url is None
        job = (
            await db_session.execute(select(PrintJob).where(PrintJob.id == send.print_job_id))
        ).scalar_one()
        assert job.status == JobStatus.PRINTING
        assert job.assigned_printer_id == bambu_setup.printer.id
        assert job.estimated_duration_hours == Decimal("1.58")
        await db_session.refresh(bambu_setup.printer)
        assert bambu_setup.printer.current_status == "printing"
        assert bambu_setup.printer.current_job_id == job.id
        assert wired.configs[bambu_setup.printer.id].tenant_id == test_tenant.id

    async def test_missing_acknowledgement_keeps_token_usable(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        _, token = await _prepare(db_session, test_tenant, test_user, bambu_setup, WRONG_MAPPING)

        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, test_tenant, test_user, bambu_setup, token)
        assert excinfo.value.code == "acknowledgement_required"
        ftps.upload.assert_not_called()

        send = await _confirm(db_session, test_tenant, test_user, bambu_setup, token, ack=True)
        assert send.status == "started" and send.warnings_acknowledged is True

    async def test_second_confirmation_refused(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        _, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        await _confirm(db_session, test_tenant, test_user, bambu_setup, token)

        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, test_tenant, test_user, bambu_setup, token)
        assert excinfo.value.code == "send_already_used"
        assert ftps.upload.await_count == 1

    async def test_expired(self, db_session, test_tenant, test_user, bambu_setup, wired, ftps):
        _, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        later = clock.now() + timedelta(minutes=6)
        with patch("app.services.print_send_service.clock.now", return_value=later):
            with pytest.raises(PrintSendError) as excinfo:
                await _confirm(db_session, test_tenant, test_user, bambu_setup, token)
        assert excinfo.value.status_code == 410
        ftps.upload.assert_not_called()

    async def test_other_tenant_token_not_found(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        from app.models.tenant import Tenant

        _, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        other = Tenant(id=uuid4(), name="Other", slug=f"other-{uuid4().hex[:6]}")
        db_session.add(other)
        await db_session.commit()

        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, other, None, bambu_setup, token)
        assert excinfo.value.status_code == 404

    async def test_busy_printer_refused(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        _, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        wired.state = idle_state("PAUSE")
        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, test_tenant, test_user, bambu_setup, token)
        assert excinfo.value.code == "printer_busy"
        ftps.upload.assert_not_called()

    async def test_second_confirmation_refused_while_first_prints(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        """Two operators: the printer's report still says IDLE, the first send wins."""
        _, first = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        _, second = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        await _confirm(db_session, test_tenant, test_user, bambu_setup, first)
        ftps.upload.reset_mock()

        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, test_tenant, test_user, bambu_setup, second)
        assert excinfo.value.code == "printer_busy"
        ftps.upload.assert_not_called()

    async def test_confirming_send_blocks_another(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        first, _ = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        _, second = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        first.status = PrintSendStatus.CONFIRMING.value
        first.confirmed_at = clock.now()
        await db_session.commit()

        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, test_tenant, test_user, bambu_setup, second)
        assert excinfo.value.code == "printer_busy"

    async def test_abandoned_confirming_send_does_not_block(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        first, _ = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        _, second = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        first.status = PrintSendStatus.CONFIRMING.value
        first.confirmed_at = clock.now() - timedelta(hours=1)
        await db_session.commit()

        again = await _confirm(db_session, test_tenant, test_user, bambu_setup, second)
        assert again.status == PrintSendStatus.STARTED.value

    async def test_finished_send_does_not_block(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        _, first = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        _, second = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        started = await _confirm(db_session, test_tenant, test_user, bambu_setup, first)
        job = await db_session.get(PrintJob, started.print_job_id)
        job.status = JobStatus.COMPLETED
        await db_session.commit()

        again = await _confirm(db_session, test_tenant, test_user, bambu_setup, second)
        assert again.status == PrintSendStatus.STARTED.value

    async def test_unreachable_printer_refused(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        _, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        wired.state = None
        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, test_tenant, test_user, bambu_setup, token)
        assert excinfo.value.status_code == 503

    async def test_developer_mode_turned_off_after_prepare(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        _, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        bambu_setup.connection.developer_mode = False
        await db_session.commit()
        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, test_tenant, test_user, bambu_setup, token)
        assert excinfo.value.code == "send_not_available"

    async def test_transfer_failure_leaves_no_job(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps, caplog
    ):
        caplog.set_level(logging.DEBUG)
        prepared, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        ftps.upload.side_effect = BambuFileTransferError("The printer did not answer in time")

        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, test_tenant, test_user, bambu_setup, token)

        assert excinfo.value.status_code == 502 and excinfo.value.code == "transfer_failed"
        assert wired.start_calls == []
        assert (await db_session.execute(select(func.count(PrintJob.id)))).scalar() == 0
        await db_session.refresh(prepared)
        assert prepared.status == PrintSendStatus.TRANSFER_FAILED.value
        assert prepared.error_message == "The printer did not answer in time"
        assert ACCESS_CODE not in caplog.text

    async def test_start_failure_leaves_no_job_and_deletes_file(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        prepared, token = await _prepare(db_session, test_tenant, test_user, bambu_setup)
        wired.start_ok = False

        with pytest.raises(PrintSendError) as excinfo:
            await _confirm(db_session, test_tenant, test_user, bambu_setup, token)

        assert excinfo.value.code == "start_failed"
        ftps.delete.assert_awaited_once()
        assert ftps.delete.await_args.args[2] == prepared.remote_file_name
        assert (await db_session.execute(select(func.count(PrintJob.id)))).scalar() == 0
        await db_session.refresh(prepared)
        assert prepared.status == PrintSendStatus.START_FAILED.value


def test_only_the_send_service_starts_a_print():
    """SC-002: no other module calls the start command."""
    app_dir = pathlib.Path(__file__).resolve().parents[2] / "app"
    callers = sorted(
        str(path.relative_to(app_dir)).replace("\\", "/")
        for path in app_dir.rglob("*.py")
        if "start_project_print(" in path.read_text(encoding="utf-8")
    )
    assert callers == ["services/bambu_mqtt.py", "services/print_send_service.py"]


# ============================================
# Deduction proposal (US4)
# ============================================


async def _pending_send(db, tenant, user, setup) -> PrintSend:
    _, token = await _prepare(db, tenant, user, setup)
    send = await _confirm(db, tenant, user, setup, token)
    send.consumption_status = ConsumptionStatus.PENDING.value
    send.consumption_lines = [
        {
            "filament_id": 1,
            "spool_id": str(setup.pla_spool.id),
            "proposed_grams": "30.10",
            "accepted_grams": None,
            "transaction_id": None,
        },
        {
            "filament_id": 3,
            "spool_id": str(setup.petg_spool.id),
            "proposed_grams": "5.00",
            "accepted_grams": None,
            "transaction_id": None,
        },
    ]
    await db.commit()
    return send


class TestConsumption:
    async def test_accept_with_correction(
        self, db_session: AsyncSession, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        send = await _pending_send(db_session, test_tenant, test_user, bambu_setup)
        service = PrintSendService(db_session, test_tenant, test_user)

        send = await service.accept_consumption(
            bambu_setup.printer.id,
            send.id,
            [
                ConsumptionAcceptLine(
                    filament_id=1, spool_id=bambu_setup.pla_spool.id, grams=Decimal("12.50")
                )
            ],
        )

        assert send.consumption_status == "accepted"
        pla = (
            await db_session.execute(select(Spool).where(Spool.id == bambu_setup.pla_spool.id))
        ).scalar_one()
        petg = (
            await db_session.execute(select(Spool).where(Spool.id == bambu_setup.petg_spool.id))
        ).scalar_one()
        await db_session.refresh(pla)
        await db_session.refresh(petg)
        assert Decimal(str(pla.current_weight)) == Decimal("787.50")
        assert Decimal(str(petg.current_weight)) == Decimal("800")  # left out: not deducted
        lines = {line["filament_id"]: line for line in send.consumption_lines}
        assert lines[1]["accepted_grams"] == "12.50"
        assert lines[1]["transaction_id"] is not None
        assert lines[3]["accepted_grams"] is None
        count = (await db_session.execute(select(func.count(InventoryTransaction.id)))).scalar()
        assert count == 1

        with pytest.raises(PrintSendError) as excinfo:
            await service.accept_consumption(
                bambu_setup.printer.id,
                send.id,
                [
                    ConsumptionAcceptLine(
                        filament_id=1, spool_id=bambu_setup.pla_spool.id, grams=Decimal("1")
                    )
                ],
            )
        assert excinfo.value.code == "consumption_not_pending"

    async def test_dismiss_moves_nothing(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        send = await _pending_send(db_session, test_tenant, test_user, bambu_setup)
        service = PrintSendService(db_session, test_tenant, test_user)

        send = await service.dismiss_consumption(bambu_setup.printer.id, send.id)

        assert send.consumption_status == "dismissed"
        assert (await db_session.execute(select(func.count(InventoryTransaction.id)))).scalar() == 0

    async def test_unknown_filament_or_foreign_spool(
        self, db_session, test_tenant, test_user, bambu_setup, wired, ftps
    ):
        send = await _pending_send(db_session, test_tenant, test_user, bambu_setup)
        service = PrintSendService(db_session, test_tenant, test_user)
        with pytest.raises(PrintSendError) as excinfo:
            await service.accept_consumption(
                bambu_setup.printer.id,
                send.id,
                [ConsumptionAcceptLine(filament_id=9, spool_id=uuid4(), grams=Decimal("1"))],
            )
        assert excinfo.value.code == "unknown_filament"

        with pytest.raises(PrintSendError) as excinfo:
            await service.accept_consumption(
                bambu_setup.printer.id,
                send.id,
                [ConsumptionAcceptLine(filament_id=1, spool_id=uuid4(), grams=Decimal("1"))],
            )
        assert excinfo.value.code == "spool_not_found"
