"""PrintSendTracker (spec 011, FR-010, FR-020): printer status → print job, proposal opening."""

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.print_job import JobStatus, PrintJob
from app.models.print_send import ConsumptionStatus, PrintSend
from app.models.spool import Spool
from app.schemas.print_send import AmsMapping
from app.services.bambu_mqtt import PRINT_ERROR_CANCELLED, BambuPrinterState
from app.services.print_send_service import PrintSendService
from app.services.print_send_tracker import PrintSendTracker
from tests.fixtures.print_sends import *  # noqa: F401,F403
from tests.fixtures.print_sends import GOOD_MAPPING, SAMPLE

pytestmark = pytest.mark.asyncio


def report(status: str, file: str = "", error: int = 0) -> BambuPrinterState:
    return BambuPrinterState(
        serial_number="01S00C123456789",
        is_online=True,
        print_status=status,
        current_file=file,
        subtask_name=file.removesuffix(".gcode.3mf"),
        print_error=error,
    )


class _Session:
    """Hands the test's session to the tracker without closing it."""

    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *exc):
        return False


async def _started(db, tenant, user, setup):
    service = PrintSendService(db, tenant, user)
    _, token = await service.prepare(
        setup.printer.id,
        plate=1,
        mapping=AmsMapping(entries=GOOD_MAPPING),
        upload_name="dragon.gcode.3mf",
        upload_content=SAMPLE,
    )
    return await service.confirm(setup.printer.id, token, acknowledge_warnings=False)


def _tracker(wired, db_session) -> PrintSendTracker:
    return PrintSendTracker(wired, session_factory=lambda: _Session(db_session))


async def _job(db, send) -> PrintJob:
    query = select(PrintJob).where(PrintJob.id == send.print_job_id)
    # Re-read the row the tracker changed, without expiring objects the test still reads.
    return (await db.execute(query.execution_options(populate_existing=True))).scalar_one()


async def test_previous_finish_before_start_is_ignored(
    db_session, test_tenant, test_user, bambu_setup, wired, ftps
):
    send = await _started(db_session, test_tenant, test_user, bambu_setup)
    tracker = _tracker(wired, db_session)

    await tracker.on_status(bambu_setup.printer.id, report("FINISH", "old_print.gcode.3mf"))

    assert (await _job(db_session, send)).status == JobStatus.PRINTING


async def test_running_then_finish_completes_and_opens_proposal(
    db_session, test_tenant, test_user, bambu_setup, wired, ftps
):
    send = await _started(db_session, test_tenant, test_user, bambu_setup)
    tracker = _tracker(wired, db_session)
    name = send.remote_file_name

    await tracker.on_status(bambu_setup.printer.id, report("RUNNING", name))
    await db_session.refresh(send)
    assert send.printer_started_at is not None
    await tracker.on_status(bambu_setup.printer.id, report("FINISH", name))

    job = await _job(db_session, send)
    assert job.status == JobStatus.COMPLETED
    assert job.completed_at is not None
    send = (
        await db_session.execute(
            select(PrintSend)
            .where(PrintSend.id == send.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert send.consumption_status == ConsumptionStatus.PENDING.value
    assert [(line["filament_id"], line["proposed_grams"]) for line in send.consumption_lines] == [
        (1, "30.10"),
        (3, "5.00"),
    ]
    assert send.consumption_lines[0]["spool_id"] == str(bambu_setup.pla_spool.id)
    await db_session.refresh(bambu_setup.printer)
    assert bambu_setup.printer.current_status == "idle"
    assert bambu_setup.printer.current_job_id is None
    spool = (
        await db_session.execute(select(Spool).where(Spool.id == bambu_setup.pla_spool.id))
    ).scalar_one()
    assert Decimal(str(spool.current_weight)) == Decimal("800")  # nothing deducted on its own


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        ("FAILED", PRINT_ERROR_CANCELLED, JobStatus.CANCELLED),
        ("FAILED", 12345, JobStatus.FAILED),
        ("IDLE", 0, JobStatus.CANCELLED),
    ],
)
async def test_end_states(
    db_session, test_tenant, test_user, bambu_setup, wired, ftps, status, error, expected
):
    send = await _started(db_session, test_tenant, test_user, bambu_setup)
    tracker = _tracker(wired, db_session)
    name = send.remote_file_name

    await tracker.on_status(bambu_setup.printer.id, report("RUNNING", name))
    await tracker.on_status(bambu_setup.printer.id, report(status, name, error))

    job = await _job(db_session, send)
    assert job.status == expected
    send = (
        await db_session.execute(
            select(PrintSend)
            .where(PrintSend.id == send.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert send.consumption_status == ConsumptionStatus.PENDING.value


async def test_unrelated_file_ignored(db_session, test_tenant, test_user, bambu_setup, wired, ftps):
    send = await _started(db_session, test_tenant, test_user, bambu_setup)
    tracker = _tracker(wired, db_session)

    await tracker.on_status(bambu_setup.printer.id, report("RUNNING", "other.gcode.3mf"))
    await tracker.on_status(bambu_setup.printer.id, report("FINISH", "other.gcode.3mf"))

    assert (await _job(db_session, send)).status == JobStatus.PRINTING


async def test_repeated_message_applies_once(
    db_session, test_tenant, test_user, bambu_setup, wired, ftps
):
    send = await _started(db_session, test_tenant, test_user, bambu_setup)
    tracker = _tracker(wired, db_session)
    name = send.remote_file_name
    await tracker.on_status(bambu_setup.printer.id, report("RUNNING", name))
    await tracker.on_status(bambu_setup.printer.id, report("FINISH", name))

    # A second listener (another pod) seeing the same change must not apply it again.
    other = _tracker(wired, db_session)
    result = await other.apply(
        db_session, test_tenant.id, bambu_setup.printer.id, "FINISH", report("FINISH", name)
    )
    assert result is None
    assert (await _job(db_session, send)).status == JobStatus.COMPLETED


async def test_unknown_tenant_is_skipped(
    db_session, test_tenant, test_user, bambu_setup, wired, ftps
):
    send = await _started(db_session, test_tenant, test_user, bambu_setup)
    wired.configs.clear()
    tracker = _tracker(wired, db_session)

    await tracker.on_status(bambu_setup.printer.id, report("FINISH", send.remote_file_name))

    assert (await _job(db_session, send)).status == JobStatus.PRINTING
