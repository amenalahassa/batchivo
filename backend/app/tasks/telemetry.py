"""What the machine reported, onto the run — and from there into the estimates.

Two steps, deliberately separate:

1. :func:`ingest_run_actuals` records what one finished job actually used.
2. :func:`learn_from_runs` turns a set of recorded runs into a decision about
   an estimate, through ``variance_service`` and nothing else.

## Why the two are not one function

A run's actuals are a fact about that run and are worth recording whether or
not anybody ever learns from them. An estimate change is a decision about
future pricing, made against the operator's own thresholds, and it needs
several runs to be worth making at all (FR-042a). Fusing them would mean one
reading could move a price, which is the failure FR-042b exists to prevent.

## What is written, and what is never written

Telemetry fills the **actual** columns. The slicer fallback fills the
**estimate** columns. That boundary is the point of this module: a 3MF file
holds a prediction, and a prediction written into ``actual_total_weight_grams``
destroys the one comparison a production run exists to make, then gets learned
from as though a machine had weighed it. The fallback supplies figures when a
printer is silent; it does not manufacture evidence.

A figure already recorded is never overwritten. Somebody weighing a plate by
hand outranks a machine's guess at the same thing, and a sweep that ran twice
must be indistinguishable from one that ran once.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.services.printer_adapter import JobActuals, ReportsJobActuals
from app.services.provenance import UnknownProvenanceField
from app.services.variance_service import (
    NotLearnable,
    Outcome,
    VarianceDecision,
    consider_outcomes,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.model import Model
    from app.models.production_run import ProductionRun
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.services.pricing_policy import CostPolicy

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
MINUTES_PER_HOUR = Decimal("60")

#: Statuses that mean "this machine did not answer". An offline printer is a
#: failed read, never a reading of zero.
UNREACHABLE_STATUSES: frozenset[str] = frozenset({"offline", "unknown", "error"})


@dataclass(frozen=True)
class RunActuals:
    """What one ingestion pass found and what it did with it.

    ``source`` says where the figures came from -- ``telemetry``, ``slicer``,
    or ``none`` -- because a caller cannot otherwise tell a measurement from a
    prediction, and the two must never be learned from alike.

    ``written`` names the columns that actually changed, so a sweep can report
    what it did rather than how many runs it looked at. ``reason`` is in words
    and is set whenever nothing was written: "the machine was offline" and
    "nothing was missing" are different facts to an operator chasing a gap.
    """

    source: str
    grams: Optional[Decimal] = None
    print_hours: Optional[Decimal] = None
    written: tuple[str, ...] = ()
    reason: Optional[str] = None


def _positive(value: Any) -> Optional[Decimal]:
    """A strictly positive decimal, or ``None``.

    Zero and negative figures are discarded rather than stored. A printer
    reporting zero grams for a finished plate, or a plug reporting zero watts
    during a print, is a fault in the sensor; taken as a measurement it would
    cost the print at no material and no power.
    """
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    return amount if amount > ZERO else None


async def _actuals_from_adapter(adapter: object) -> tuple[Optional[JobActuals], Optional[str]]:
    """Ask a machine what it used, or say why it could not be asked."""
    get_status = getattr(adapter, "get_status", None)
    if get_status is None:
        return (None, "the adapter cannot report a status")

    try:
        state = await get_status()
    except Exception as exc:  # noqa: BLE001 - one machine must not end a sweep
        # A transport failure is reported, never raised. A sweep over thirty
        # printers must survive one of them being unplugged.
        logger.warning(f"Printer telemetry unavailable: {exc}")
        return (None, f"the machine could not be reached ({exc})")

    status = (getattr(state, "status", "") or "").lower()
    if status in UNREACHABLE_STATUSES:
        return (None, f"the machine is {status}")

    if not isinstance(adapter, ReportsJobActuals):
        return (None, "this machine does not report what a job used")

    try:
        return (await adapter.get_job_actuals(), None)
    except Exception as exc:  # noqa: BLE001 - as above
        logger.warning(f"Printer reported no job actuals: {exc}")
        return (None, f"the machine reported no usage figures ({exc})")


def _slicer_figures(metadata: object) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """Weight and hours from parsed 3MF metadata, where present."""
    grams = _positive(getattr(metadata, "filament_weight_grams", None))
    minutes = _positive(getattr(metadata, "print_time_minutes", None))
    hours = (minutes / MINUTES_PER_HOUR) if minutes is not None else None
    return (grams, hours)


async def ingest_run_actuals(
    db: AsyncSession,
    tenant: "Tenant",
    run: "ProductionRun",
    *,
    adapter: Optional[object] = None,
    slicer_metadata: Optional[object] = None,
) -> RunActuals:
    """Record what one finished run used.

    The machine is asked first. If it answers, its figures are actuals and go
    in the actual columns. If it is reachable but says nothing about
    consumption, the slicer metadata fills the **estimate** columns instead.
    If it is offline or unreachable, nothing is written at all and the slicer
    is **not** consulted: an unreachable machine is a problem to surface, and
    filling the gap from a 3MF would hide a printer that has been down for a
    week.

    Nothing is committed. The caller's transaction decides, so a sweep over
    many runs commits once or not at all.
    """
    telemetry, unavailable = (
        await _actuals_from_adapter(adapter) if adapter is not None else (None, "no adapter")
    )

    written: list[str] = []

    measured_grams = _positive(telemetry.grams) if telemetry is not None else None
    measured_hours = _positive(telemetry.print_hours) if telemetry is not None else None

    if measured_grams is not None or measured_hours is not None:
        if measured_grams is not None and run.actual_total_weight_grams is None:
            run.actual_total_weight_grams = measured_grams
            written.append("actual_total_weight_grams")
        if measured_hours is not None and run.duration_hours is None:
            run.duration_hours = measured_hours
            written.append("duration_hours")

        if written:
            db.add(run)
        return RunActuals(
            source="telemetry",
            grams=measured_grams,
            print_hours=measured_hours,
            written=tuple(written),
            reason=None if written else "every figure the machine reported was already recorded",
        )

    # A machine that could not be reached is a problem to surface, so the
    # slicer is not consulted: filling the gap from a 3MF would hide a printer
    # that has been down for a week. A machine that answered but reported no
    # usage figures is a different case -- it is working, it simply cannot
    # weigh filament -- and that one does fall through.
    if telemetry is None and unavailable is not None and unavailable != "no adapter":
        if "does not report" not in unavailable:
            return RunActuals(source="none", reason=unavailable)

    if slicer_metadata is None:
        return RunActuals(
            source="none",
            reason=unavailable or "no machine reading and no slicer metadata",
        )

    grams, hours = _slicer_figures(slicer_metadata)
    if grams is not None and run.estimated_total_weight_grams is None:
        run.estimated_total_weight_grams = grams
        written.append("estimated_total_weight_grams")
    if hours is not None and run.estimated_print_time_hours is None:
        run.estimated_print_time_hours = hours
        written.append("estimated_print_time_hours")

    if written:
        db.add(run)
    return RunActuals(
        source="slicer",
        grams=grams,
        print_hours=hours,
        written=tuple(written),
        reason=None if written else "the slicer figures were already recorded",
    )


# ---------------------------------------------------------------------------
# From recorded runs to a decision about an estimate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _LearnableField:
    """One model field a run can bear witness to, and how to read it.

    The reader returns the figure **per plate**, which is the unit the model's
    own estimate is in. A run covering four plates that took forty hours is
    evidence of ten hours a plate, not of forty.
    """

    field_name: str
    read: Any
    label: str


def _plates(run: "ProductionRun") -> Decimal:
    """How many plates a run covered, never zero.

    A legacy item-based run carries ``total_plates == 0``, which means one bed
    load rather than none, so it is read as one. Dividing by zero here would
    turn a recorded run into a crash in a background sweep.
    """
    count = _positive(getattr(run, "total_plates", None))
    return count if count is not None else Decimal("1")


def _print_minutes_per_plate(run: "ProductionRun") -> Optional[Decimal]:
    hours = _positive(getattr(run, "duration_hours", None))
    if hours is None:
        return None
    return hours * MINUTES_PER_HOUR / _plates(run)


def _waste_grams_per_plate(run: "ProductionRun") -> Optional[Decimal]:
    """Purge and tower filament per plate, where the run split it out.

    Only the two purge columns, never ``actual_total_weight_grams``: the total
    includes the part itself, and treating it as waste would price every item
    as though its own filament had been thrown away.
    """
    flushed = getattr(run, "actual_flushed_grams", None)
    tower = getattr(run, "actual_tower_grams", None)
    if flushed is None and tower is None:
        return None
    total = (Decimal(str(flushed or 0))) + (Decimal(str(tower or 0)))
    if total < ZERO:
        return None
    return total / _plates(run)


#: What a production run can move, and nothing else.
#:
#: Part weight is deliberately absent. It belongs to ``model_material``, one
#: row per filament the item uses, and a run's total weight cannot be
#: attributed across several materials without the per-material actuals that
#: ``ProductionRunMaterial`` carries. Guessing the split here would move a
#: figure on evidence that does not bear on it.
LEARNABLE_FROM_RUNS: tuple[_LearnableField, ...] = (
    _LearnableField("print_time_minutes", _print_minutes_per_plate, "machine occupancy"),
    _LearnableField("waste_grams", _waste_grams_per_plate, "purge and priming filament"),
)


async def learn_from_runs(
    db: AsyncSession,
    tenant: "Tenant",
    model: "Model",
    runs: Sequence["ProductionRun"],
    *,
    min_outcomes: Optional[int] = None,
    divergence_threshold_pct: Optional[Decimal] = None,
    policy: Optional["CostPolicy"] = None,
    user: Optional["User"] = None,
) -> dict[str, VarianceDecision]:
    """Consider what these runs say about the model's estimates.

    The thresholds are the operator's (FR-042a, FR-042b). They are read from
    the policy when not passed, never defaulted here: a default in this module
    would be code deciding how much evidence is enough.

    Returns one decision per learnable field, including the fields nothing
    moved, so a caller can report "five runs, no change" rather than silence.
    Nothing is committed.
    """
    if min_outcomes is None or divergence_threshold_pct is None:
        from app.services.pricing_policy import resolve_cost_policy

        resolved = policy or await resolve_cost_policy(db, tenant)
        if min_outcomes is None:
            min_outcomes = resolved.min_outcomes_before_auto_update
        if divergence_threshold_pct is None:
            divergence_threshold_pct = resolved.estimate_divergence_threshold_pct

    decisions: dict[str, VarianceDecision] = {}

    for learnable in LEARNABLE_FROM_RUNS:
        outcomes: list[Outcome] = []
        for run in runs:
            value = learnable.read(run)
            if value is None:
                # A run nobody recorded anything against is not evidence of a
                # zero, so it is not an outcome at all.
                continue
            observed_on = getattr(run, "completed_at", None) or getattr(run, "started_at", None)
            outcomes.append(
                Outcome(
                    run_id=str(run.id),
                    value=value,
                    observed_on=observed_on.date() if observed_on else clock.today(),
                )
            )

        try:
            decisions[learnable.field_name] = await consider_outcomes(
                db,
                tenant,
                model,
                entity_type="model",
                field_name=learnable.field_name,
                outcomes=outcomes,
                min_outcomes=min_outcomes,
                divergence_threshold_pct=divergence_threshold_pct,
                user=user,
            )
        except NotLearnable as exc:
            # The operator set this deliberately (FR-002, FR-042g). Reported
            # rather than raised: the rest of the fields still deserve a look.
            decisions[learnable.field_name] = VarianceDecision(
                applied=False,
                reason=str(exc),
                run_ids=frozenset(outcome.run_id for outcome in outcomes),
            )
        except UnknownProvenanceField as exc:  # pragma: no cover - registry drift
            logger.error(f"Telemetry names an unregistered field: {exc}")

    return decisions


__all__ = [
    "LEARNABLE_FROM_RUNS",
    "RunActuals",
    "ingest_run_actuals",
    "learn_from_runs",
]
