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

import logging
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
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


__all__ = ["PowerReading", "ingest_power_readings"]
