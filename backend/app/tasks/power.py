"""Smart-plug readings onto the machine's power draw.

``printer.measured_watts`` is the one cost input where a twenty-pound sensor
beats any estimate. The nameplate rating of a printer is roughly twice its
printing draw, so an operator who typed the nameplate figure is over-costing
every print, and one who guessed is guessing.

## Why a reading does not simply overwrite the figure

A plug that reports kilowatts where watts were expected gives a reading ten
times too high, and applied directly it would reprice every product that
machine prints. So readings go through ``variance_service`` exactly as any
other observation does: a rolling average once enough of them agree (FR-042a),
held as a proposal beyond the operator's divergence threshold (FR-042b), and
never overriding a figure the operator set themselves (FR-042g).

That also means this module contains no policy of its own. The minimum number
of readings and the divergence threshold are the operator's settings, read from
their pricing policy when the caller does not pass them.
"""

import asyncio
import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.tasks.celery_app import celery_app
from app.services.variance_service import (
    NotLearnable,
    Outcome,
    VarianceDecision,
    consider_outcomes,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.printer import Printer
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.pricing_policy import CostPolicy

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

#: One reading: the identifier it is attributed to, the draw, and the day.
#:
#: The identifier matters as much as the figure. FR-042d compares proposals by
#: the outcomes behind them, so a rejected reading must stay identifiable or
#: the same question gets asked again tomorrow.
PowerReading = tuple[str, Decimal, Optional[date]]


def _outcomes_from(readings: Iterable[PowerReading]) -> list[Outcome]:
    """The usable readings, dated, with the faults dropped.

    A zero or negative reading is discarded rather than averaged in. A plug
    reporting zero watts while a print ran is a disconnected plug, and taken
    as a measurement it would cost every print at no power -- the one error
    this mechanism could make that an operator would never think to check.
    """
    outcomes: list[Outcome] = []
    for reading_id, watts, observed_on in readings:
        try:
            value = Decimal(str(watts))
        except (ArithmeticError, TypeError, ValueError):
            logger.warning(f"Power reading {reading_id!r} is not a number; discarded")
            continue
        if value <= ZERO:
            logger.warning(f"Power reading {reading_id!r} is {value} W; discarded as a fault")
            continue
        outcomes.append(
            Outcome(run_id=str(reading_id), value=value, observed_on=observed_on or clock.today())
        )
    return outcomes


async def ingest_power_readings(
    db: AsyncSession,
    tenant: "Tenant",
    printer: "Printer",
    readings: Iterable[PowerReading],
    *,
    min_outcomes: Optional[int] = None,
    divergence_threshold_pct: Optional[Decimal] = None,
    policy: Optional["CostPolicy"] = None,
    user: Optional["User"] = None,
) -> VarianceDecision:
    """Consider what these readings say about this machine's draw.

    Returns the decision rather than a boolean: an operator asking why their
    power figure did not move needs the reason, and a held proposal needs to
    reach the review list rather than being discovered later.

    Nothing is committed. The caller's transaction decides, so a sweep across
    a shelf of printers commits once.
    """
    outcomes = _outcomes_from(readings)

    if min_outcomes is None or divergence_threshold_pct is None:
        from app.services.pricing_policy import resolve_cost_policy

        resolved = policy or await resolve_cost_policy(db, tenant)
        if min_outcomes is None:
            min_outcomes = resolved.min_outcomes_before_auto_update
        if divergence_threshold_pct is None:
            divergence_threshold_pct = resolved.estimate_divergence_threshold_pct

    try:
        return await consider_outcomes(
            db,
            tenant,
            printer,
            entity_type="printer",
            field_name="measured_watts",
            outcomes=outcomes,
            min_outcomes=min_outcomes,
            divergence_threshold_pct=divergence_threshold_pct,
            user=user,
        )
    except NotLearnable as exc:
        # The operator set this draw themselves. Reported, not raised: a sweep
        # over many machines must keep going, and the reason belongs in the
        # result where somebody can read it.
        return VarianceDecision(
            applied=False,
            reason=str(exc),
            run_ids=frozenset(outcome.run_id for outcome in outcomes),
        )


# ---------------------------------------------------------------------------
# The entry point (task T148)
#
# :func:`ingest_power_readings` was written, tested and never called: no
# `@celery_app.task`, no place in `celery_app.include`, no caller in `app/`.
# This is the dispatchable form of it, so a plug integration has something to
# hand its readings to rather than a function only a test can reach.
#
# ## Why this is dispatched and not scheduled
#
# A sweep needs somewhere to read from, and there is no store of plug readings
# in this system: `PowerReading` is a tuple a caller supplies, and no table,
# endpoint or adapter produces one. Putting this on `beat_schedule` would wake
# a worker every hour to find nothing, which reads in the log as a working
# integration and is not one.
#
# So the task takes its readings as its argument. Its producer is
# `POST /printers/{printer_id}/power-readings` (task T159), which a plug or a
# person posts readings to; there is still no schedule, because nothing here
# polls a plug, and `measured_watts` moves only through the proposal that
# endpoint raises.
# ---------------------------------------------------------------------------


@celery_app.task(name="power.ingest", bind=True, max_retries=0)
def ingest_power_readings_task(
    self: Any,
    printer_id: str,
    readings: list[list[Any]],
) -> dict[str, Any]:
    """Consider what a set of plug readings says about one machine's draw.

    ``readings`` arrives over JSON as ``[[source_id, watts, "YYYY-MM-DD"], …]``
    with the wattage as a **string**: a draw is a figure the engine multiplies
    by an electricity rate, so it must not cross the broker as a float
    (Constitution IV). A malformed reading is dropped with a warning rather
    than failing the batch — one bad line from a plug must not discard the
    readings beside it.

    ``max_retries=0``: a retry would reconsider the same readings, and a
    proposal already rejected is not re-raised from them (FR-042d), so a retry
    buys nothing.
    """
    return asyncio.run(_ingest(uuid.UUID(str(printer_id)), readings))


def _parse(readings: list[list[Any]]) -> list[PowerReading]:
    """Readings off the wire, dropping what cannot be read."""
    parsed: list[PowerReading] = []
    for entry in readings:
        try:
            source_id, watts, *rest = entry
            observed = date.fromisoformat(rest[0]) if rest and rest[0] else None
            parsed.append((str(source_id), Decimal(str(watts)), observed))
        except (ArithmeticError, IndexError, TypeError, ValueError):
            logger.warning("Discarding an unreadable power reading: %r", entry)
    return parsed


async def _ingest(printer_id: uuid.UUID, readings: list[list[Any]]) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.rls import set_rls_context
    from app.database import async_session_maker, privileged_session_maker
    from app.models.printer import Printer
    from app.models.tenant import Tenant

    parsed = _parse(readings)

    # A reading names a printer, not a tenant. Finding the printer's tenant is
    # the one cross-tenant step, done on the privileged connection; everything
    # after it is scoped to that tenant.
    async with privileged_session_maker()() as lookup:
        owner = (
            await lookup.execute(select(Printer.tenant_id).where(Printer.id == printer_id))
        ).scalar_one_or_none()
    if owner is None:
        logger.warning("No printer %s to attribute power readings to", printer_id)
        return {"applied": False, "reason": "printer not found"}

    async with async_session_maker() as db:
        await set_rls_context(db, tenant_id=owner)
        printer = (await db.execute(select(Printer).where(Printer.id == printer_id))).scalar_one()

        tenant = (
            await db.execute(select(Tenant).where(Tenant.id == printer.tenant_id))
        ).scalar_one_or_none()
        if tenant is None:  # pragma: no cover - a printer cannot outlive its tenant
            return {"applied": False, "reason": "tenant not found"}

        decision = await ingest_power_readings(db, tenant, printer, parsed)
        await db.commit()

        if decision.applied:
            logger.info(
                "Printer %s: measured draw updated from %d reading(s) -- %s",
                printer_id,
                len(decision.run_ids),
                decision.reason,
            )
        elif decision.proposal is not None:
            # A plug reporting kilowatts where watts were expected lands here,
            # which is the whole reason a reading does not simply overwrite the
            # figure (FR-042b).
            logger.warning(
                "Printer %s: measured draw diverges beyond the threshold and is "
                "held for review -- %s",
                printer_id,
                decision.reason,
            )

        return {
            "applied": decision.applied,
            "reason": decision.reason,
            "observed_value": (
                str(decision.observed_value) if decision.observed_value is not None else None
            ),
            "readings_used": len(parsed),
        }


__all__ = ["PowerReading", "ingest_power_readings", "ingest_power_readings_task"]
