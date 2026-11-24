"""Schema of `print_sends` and `printer_connections.developer_mode` (spec 011, T008).

CRUD, the unique confirmation hash, the check constraints, and what happens to
a send when its print job or printer is deleted.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.print_job import JobStatus, PrintJob
from app.models.print_send import ConsumptionStatus, PrintSend, PrintSendStatus
from app.models.printer_connection import PrinterConnection

pytestmark = pytest.mark.asyncio


def _send(tenant_id, printer_id, **overrides) -> PrintSend:
    values = dict(
        id=uuid4(),
        tenant_id=tenant_id,
        printer_id=printer_id,
        file_name="dragon.gcode.3mf",
        file_size=1234,
        file_md5="0" * 32,
        remote_file_name="batchivo-abcdef12.gcode.3mf",
        plate_index=1,
        ams_mapping=[{"filament_id": 1, "slot": {"kind": "external"}}],
        summary={"lines": []},
        token_hash=uuid4().hex + uuid4().hex,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        status=PrintSendStatus.PREPARED.value,
    )
    values.update(overrides)
    return PrintSend(**values)


async def test_create_read_update(db_session: AsyncSession, test_tenant, test_printer):
    send = _send(test_tenant.id, test_printer.id)
    db_session.add(send)
    await db_session.commit()

    loaded = (
        await db_session.execute(select(PrintSend).where(PrintSend.id == send.id))
    ).scalar_one()
    assert loaded.status == "prepared"
    assert loaded.consumption_status == ConsumptionStatus.NONE.value
    assert loaded.warnings_acknowledged is False
    assert loaded.ams_mapping == [{"filament_id": 1, "slot": {"kind": "external"}}]
    assert loaded.printer.id == test_printer.id

    loaded.status = PrintSendStatus.STARTED.value
    await db_session.commit()
    assert loaded.status == "started"


async def test_token_hash_is_unique(db_session: AsyncSession, test_tenant, test_printer):
    db_session.add(_send(test_tenant.id, test_printer.id, token_hash="a" * 64))
    await db_session.commit()
    db_session.add(_send(test_tenant.id, test_printer.id, token_hash="a" * 64))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.parametrize(
    "overrides",
    [{"plate_index": 0}, {"status": "exploded"}, {"consumption_status": "maybe"}],
)
async def test_check_constraints(db_session: AsyncSession, test_tenant, test_printer, overrides):
    db_session.add(_send(test_tenant.id, test_printer.id, **overrides))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_deleting_the_job_keeps_the_send(db_session: AsyncSession, test_tenant, test_printer):
    job = PrintJob(id=uuid4(), tenant_id=test_tenant.id, status=JobStatus.PRINTING, quantity=1)
    db_session.add(job)
    await db_session.flush()
    send = _send(test_tenant.id, test_printer.id, print_job_id=job.id)
    db_session.add(send)
    await db_session.commit()
    await db_session.refresh(job, ["print_send"])
    assert job.print_send is not None and job.print_send.id == send.id

    send_id = send.id
    await db_session.delete(job)
    await db_session.commit()
    db_session.expire_all()

    loaded = (
        await db_session.execute(select(PrintSend).where(PrintSend.id == send_id))
    ).scalar_one()
    assert loaded.print_job_id is None


async def test_deleting_the_printer_deletes_its_sends(
    db_session: AsyncSession, test_tenant, test_printer
):
    send = _send(test_tenant.id, test_printer.id)
    db_session.add(send)
    await db_session.commit()

    await db_session.delete(test_printer)
    await db_session.commit()

    remaining = (await db_session.execute(select(PrintSend))).scalars().all()
    assert remaining == []


async def test_developer_mode_defaults_off(db_session: AsyncSession, test_tenant, test_printer):
    connection = PrinterConnection(
        tenant_id=test_tenant.id, printer_id=test_printer.id, connection_type="bambu_lan"
    )
    db_session.add(connection)
    await db_session.commit()
    await db_session.refresh(connection)

    assert connection.developer_mode is False
    assert connection.can_send_prints is False
    connection.developer_mode = True
    assert connection.can_send_prints is True
    connection.connection_type = "bambu_cloud"
    assert connection.can_send_prints is False
