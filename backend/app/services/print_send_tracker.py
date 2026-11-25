"""Following a sent print through the printer's MQTT status (spec 011, FR-010, FR-020).

The tracker listens to ``status_update`` from :class:`BambuMQTTService` and
reacts only when a printer's ``gcode_state`` changes, so status messages
arriving every second cost no database query. On a change it loads the send
being printed on that printer, through a session scoped to the printer's
tenant, and moves its print job:

- ``PREPARE``/``RUNNING``/``PAUSE`` showing our file → the printer has started it;
- ``FINISH`` → completed; ``FAILED`` → cancelled when ``print_error`` says the
  task was cancelled, failed otherwise; ``IDLE`` after our start → cancelled.

Our file is recognised by name: right after the start command the printer
still reports the previous print's ``FINISH``, which must not complete the new
job. Updates are conditional on the job still printing, so two backend pods
listening to the same printer apply a transition once.

When the job ends, the spool deduction proposal is opened: one line per plate
filament with the grams the sliced file expected. Nothing is deducted here;
the operator accepts or dismisses it (``PrintSendService``).
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.rls import set_rls_context
from app.models.print_job import JobStatus, PrintJob, PrinterStatus
from app.models.print_send import ConsumptionStatus, PrintSend, PrintSendStatus
from app.models.printer import Printer
from app.services.bambu_mqtt import (
    PRINT_ERROR_CANCELLED,
    BambuMQTTService,
    BambuPrinterState,
)

logger = logging.getLogger(__name__)

RUNNING_STATES = frozenset({"PREPARE", "RUNNING", "PAUSE", "SLICING"})

SessionFactory = Callable[[], Any]


def _default_session_factory() -> Any:
    from app.database import async_session_maker

    return async_session_maker()


def _matches(send: PrintSend, state: BambuPrinterState) -> bool:
    """Whether the printer's report names this send's file."""
    stem = send.remote_file_name.removesuffix(".gcode.3mf")
    names = [state.current_file or "", state.subtask_name or ""]
    return any(stem and stem in name for name in names)


def _end_status(gcode_state: str, state: BambuPrinterState) -> Optional[JobStatus]:
    if gcode_state == "FINISH":
        return JobStatus.COMPLETED
    if gcode_state == "FAILED":
        return (
            JobStatus.CANCELLED if state.print_error == PRINT_ERROR_CANCELLED else JobStatus.FAILED
        )
    if gcode_state == "IDLE":
        return JobStatus.CANCELLED
    return None


def proposal_lines(send: PrintSend) -> list[dict[str, Any]]:
    """Deduction lines from the confirmed summary: one per filament with grams."""
    lines = []
    for line in (send.summary or {}).get("lines", []):
        grams = (line.get("expected") or {}).get("grams")
        if grams is None:
            continue
        spool = line.get("mapped_spool") or {}
        lines.append(
            {
                "filament_id": line["filament_id"],
                "spool_id": spool.get("id"),
                "proposed_grams": grams,
                "accepted_grams": None,
                "transaction_id": None,
            }
        )
    return lines


class PrintSendTracker:
    """Moves print jobs started by a print send as their printer reports progress."""

    def __init__(
        self,
        mqtt: BambuMQTTService,
        session_factory: Optional[SessionFactory] = None,
    ) -> None:
        self.mqtt = mqtt
        self._session_factory = session_factory or _default_session_factory
        self._last_state: dict[UUID, Optional[str]] = {}

    async def on_status(self, printer_id: UUID, state: BambuPrinterState) -> None:
        """``status_update`` callback: act only when ``gcode_state`` changes."""
        gcode_state = (state.print_status or "").upper() or None
        if self._last_state.get(printer_id, "<unseen>") == gcode_state:
            return
        self._last_state[printer_id] = gcode_state
        if gcode_state is None:
            return
        config = self.mqtt.get_config(printer_id)
        tenant_id = config.tenant_id if config else None
        if tenant_id is None:
            logger.debug(f"Printer {printer_id} has no known tenant: not tracking print sends")
            return
        try:
            async with self._session_factory() as session:
                await set_rls_context(session, tenant_id=tenant_id)
                await self.apply(session, tenant_id, printer_id, gcode_state, state)
        except Exception as e:
            logger.error(f"Failed to track print send on printer {printer_id}: {e}")

    async def apply(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        printer_id: UUID,
        gcode_state: str,
        state: BambuPrinterState,
    ) -> Optional[JobStatus]:
        """Apply one state change; returns the job's new end status when it ended."""
        send = (
            await session.execute(
                select(PrintSend)
                .join(PrintJob, PrintJob.id == PrintSend.print_job_id)
                .where(
                    PrintSend.tenant_id == tenant_id,
                    PrintSend.printer_id == printer_id,
                    PrintSend.status == PrintSendStatus.STARTED.value,
                    PrintJob.status == JobStatus.PRINTING,
                )
                .order_by(PrintSend.confirmed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if send is None or not _matches(send, state):
            return None

        now = clock.now()
        if gcode_state in RUNNING_STATES:
            if send.printer_started_at is None:
                send.printer_started_at = now
                await session.commit()
            return None

        end = _end_status(gcode_state, state)
        if end is None or (gcode_state == "IDLE" and send.printer_started_at is None):
            return None

        result = await session.execute(
            update(PrintJob)
            .where(
                PrintJob.id == send.print_job_id,
                PrintJob.tenant_id == tenant_id,
                PrintJob.status == JobStatus.PRINTING,
            )
            .values(
                status=end,
                completed_at=now,
                error_message=(
                    f"Printer reported {gcode_state} (error {state.print_error})"
                    if end == JobStatus.FAILED
                    else None
                ),
            )
        )
        if result.rowcount == 0:
            await session.rollback()
            return None  # Another listener applied it first

        await session.execute(
            update(Printer)
            .where(Printer.id == printer_id, Printer.tenant_id == tenant_id)
            .where(Printer.current_job_id == send.print_job_id)
            .values(current_status=PrinterStatus.IDLE.value, current_job_id=None)
        )
        if send.printer_started_at is None:
            send.printer_started_at = _earliest(send.confirmed_at, now)
        lines = proposal_lines(send)
        if lines and send.consumption_status == ConsumptionStatus.NONE.value:
            send.consumption_lines = lines
            send.consumption_status = ConsumptionStatus.PENDING.value
        await session.commit()
        logger.info(f"Print job {send.print_job_id} from print send {send.id}: {end.value}")
        return end


def _earliest(first: Optional[datetime], second: datetime) -> datetime:
    return first if first is not None and first < second else second


_tracker: Optional[PrintSendTracker] = None


def register_print_send_tracker(mqtt: BambuMQTTService) -> PrintSendTracker:
    """Attach the tracker to the MQTT service (called once at application start)."""
    global _tracker
    if _tracker is None or _tracker.mqtt is not mqtt:
        _tracker = PrintSendTracker(mqtt)
        mqtt.register_callback("status_update", _tracker.on_status)
    return _tracker
