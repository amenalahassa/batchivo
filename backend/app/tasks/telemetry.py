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

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import clock
from app.tasks.celery_app import celery_app
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


#: The model fields a run's own columns bear witness to.
#:
#: Expected yield and part weight are learned too, but not from run columns:
#: yield from the parts each run attempted and lost for this model, and part
#: weight from a run's per-spool actuals where they attribute to one bill-of-
#: materials line. See :func:`_learn_yield` and :func:`_learn_part_weight`.
LEARNABLE_FROM_RUNS: tuple[_LearnableField, ...] = (
    _LearnableField("print_time_minutes", _print_minutes_per_plate, "machine occupancy"),
    _LearnableField("waste_grams", _waste_grams_per_plate, "purge and priming filament"),
)


# ---------------------------------------------------------------------------
# Yield and part weight (task T256, FR-015d, SC-010)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class YieldEvidence:
    """What one run says about one model's failures, in parts and in plates."""

    parts_attempted: int
    parts_succeeded: int
    plates_attempted: int
    plates_succeeded: int


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _tally(ok: int, lost: int, size: int) -> tuple[int, int, int, int]:
    """Parts and plates for one printed group; a failure condemns its plate."""
    loads = _ceil_div(ok + lost, size)
    return ok + lost, ok, loads, loads - min(loads, _ceil_div(lost, size))


def yield_evidence(run: "ProductionRun", model: "Model") -> Optional[YieldEvidence]:
    """This run's parts and plates for this model, or ``None`` if it printed none.

    A multi-plate run records each plate; an item run records parts, and its
    plates are the parts over the model's prints per plate. Under the per-plate
    mode a failure condemns its plate (research D3), so the plates lost are the
    failed parts over the plate size, rounded up.
    """
    per_plate = int(_positive(getattr(model, "prints_per_plate", None)) or 1)
    totals = [0, 0, 0, 0]

    if (getattr(run, "total_plates", 0) or 0) > 0:
        groups = [
            (
                int(plate.successful_prints or 0),
                int(plate.failed_prints or 0),
                int(plate.prints_per_plate or per_plate) or 1,
            )
            for plate in getattr(run, "plates", None) or []
            if plate.model_id == model.id
        ]
    else:
        groups = [
            (int(item.successful_quantity or 0), int(item.failed_quantity or 0), per_plate)
            for item in getattr(run, "items", None) or []
            if item.model_id == model.id
        ]

    for ok, lost, size in groups:
        if ok + lost <= 0:
            continue
        for index, value in enumerate(_tally(ok, lost, size)):
            totals[index] += value

    if totals[0] <= 0:
        return None
    return YieldEvidence(*totals)


def pooled_yield(
    evidence: Sequence[YieldEvidence], mode: str, prints_per_plate: int
) -> Optional[Decimal]:
    """The per-part yield the evidence supports, under one failure mode (research D3).

    ``per_part``: parts succeeded over parts attempted, pooled across runs so a
    run of one part does not weigh as much as a run of forty. ``per_plate``:
    the pooled plate success rate, and the per-part figure is its N-th root.
    ``None`` when nothing succeeded: a yield of zero is a configuration error
    (spec edge case), never something to learn.
    """
    if mode == "per_plate":
        attempted = sum(e.plates_attempted for e in evidence)
        succeeded = sum(e.plates_succeeded for e in evidence)
    else:
        attempted = sum(e.parts_attempted for e in evidence)
        succeeded = sum(e.parts_succeeded for e in evidence)
    if attempted <= 0 or succeeded <= 0:
        return None
    rate = Decimal(succeeded) / Decimal(attempted)
    size = max(prints_per_plate, 1)
    if mode != "per_plate" or size == 1:
        return rate
    return rate ** (Decimal(1) / Decimal(size))


def runs_under_current_mode(model: "Model", runs: Sequence["ProductionRun"]) -> list:
    """Only the runs completed since the item's failure mode last changed (FR-015d)."""
    since = getattr(model, "failure_mode_since", None)
    if since is None:
        return list(runs)
    kept = []
    for run in runs:
        completed = getattr(run, "completed_at", None)
        if completed is not None and completed.date() >= since:
            kept.append(run)
    return kept


def _observed_on(run: "ProductionRun") -> date:
    when = getattr(run, "completed_at", None) or getattr(run, "started_at", None)
    return when.date() if when else clock.today()


async def _learn_yield(
    db: AsyncSession,
    tenant: "Tenant",
    model: "Model",
    runs: Sequence["ProductionRun"],
    *,
    min_outcomes: int,
    divergence_threshold_pct: Decimal,
    user: Optional["User"],
) -> VarianceDecision:
    """Learn expected yield from the runs printed under the item's current mode."""
    mode = getattr(model, "failure_mode", None) or "per_part"
    per_plate = int(_positive(getattr(model, "prints_per_plate", None)) or 1)
    evidence: list[YieldEvidence] = []
    outcomes: list[Outcome] = []
    for run in runs_under_current_mode(model, runs):
        found = yield_evidence(run, model)
        if found is None:
            continue
        evidence.append(found)
        outcomes.append(
            Outcome(
                run_id=str(run.id),
                value=pooled_yield([found], mode, per_plate) or ZERO,
                observed_on=_observed_on(run),
            )
        )
    observed = pooled_yield(evidence, mode, per_plate)
    if outcomes and observed is None:
        return VarianceDecision(
            applied=False,
            reason="no part succeeded in these runs, and a yield of zero is not learned",
            run_ids=frozenset(outcome.run_id for outcome in outcomes),
        )
    return await consider_outcomes(
        db,
        tenant,
        model,
        entity_type="model",
        field_name="expected_yield",
        outcomes=outcomes,
        min_outcomes=min_outcomes,
        divergence_threshold_pct=divergence_threshold_pct,
        user=user,
        observed=observed,
    )


def part_weight_outcome(run: "ProductionRun", model: "Model", material: Any) -> Optional[Decimal]:
    """Grams of this line's filament per part, where the run attributes it unambiguously.

    Only a run that printed this model alone, with one actual for this line's
    spool, and no failed part: a failed part used an unknown share of its
    filament, so dividing by every part attempted would understate the weight.
    """
    if (getattr(run, "total_plates", 0) or 0) > 0:
        units = [
            (plate.model_id, int(plate.successful_prints or 0), int(plate.failed_prints or 0))
            for plate in getattr(run, "plates", None) or []
        ]
    else:
        units = [
            (item.model_id, int(item.successful_quantity or 0), int(item.failed_quantity or 0))
            for item in getattr(run, "items", None) or []
        ]
    if not units or any(model_id != model.id or lost > 0 for model_id, _, lost in units):
        return None
    parts = sum(ok for _, ok, _ in units)
    if parts <= 0:
        return None

    matching = [
        used for used in getattr(run, "materials", None) or [] if used.spool_id == material.spool_id
    ]
    if len(matching) != 1:
        return None
    grams = _positive(matching[0].actual_model_weight_grams)
    if grams is None:
        return None
    return grams / Decimal(parts)


async def _learn_part_weight(
    db: AsyncSession,
    tenant: "Tenant",
    model: "Model",
    runs: Sequence["ProductionRun"],
    *,
    min_outcomes: int,
    divergence_threshold_pct: Decimal,
    user: Optional["User"],
) -> dict[str, VarianceDecision]:
    """Learn each bill-of-materials line's weight where a spool names one line."""
    decisions: dict[str, VarianceDecision] = {}
    materials = list(getattr(model, "materials", None) or [])
    for material in materials:
        if sum(1 for other in materials if other.spool_id == material.spool_id) != 1:
            # Two lines on one spool cannot be told apart by the spool's actual.
            continue
        outcomes = []
        for run in runs:
            value = part_weight_outcome(run, model, material)
            if value is not None:
                outcomes.append(
                    Outcome(run_id=str(run.id), value=value, observed_on=_observed_on(run))
                )
        key = f"model_material.{material.id}.weight_grams"
        try:
            decisions[key] = await consider_outcomes(
                db,
                tenant,
                material,
                entity_type="model_material",
                field_name="weight_grams",
                outcomes=outcomes,
                min_outcomes=min_outcomes,
                divergence_threshold_pct=divergence_threshold_pct,
                user=user,
            )
        except NotLearnable as exc:
            decisions[key] = VarianceDecision(
                applied=False,
                reason=str(exc),
                run_ids=frozenset(outcome.run_id for outcome in outcomes),
            )
    return decisions


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

    try:
        decisions["expected_yield"] = await _learn_yield(
            db,
            tenant,
            model,
            runs,
            min_outcomes=min_outcomes,
            divergence_threshold_pct=divergence_threshold_pct,
            user=user,
        )
    except NotLearnable as exc:
        decisions["expected_yield"] = VarianceDecision(applied=False, reason=str(exc))

    decisions.update(
        await _learn_part_weight(
            db,
            tenant,
            model,
            runs,
            min_outcomes=min_outcomes,
            divergence_threshold_pct=divergence_threshold_pct,
            user=user,
        )
    )

    return decisions


# ---------------------------------------------------------------------------
# The entry points (task T148)
#
# The two functions above were written, tested and then never called. They had
# no `@celery_app.task`, no place in `celery_app.include` and no caller in
# `app/`, so in a running system no estimate was ever revised, no proposal ever
# reached the review list T106 built, and no cost line ever acquired an
# observed origin. FR-042 describes a loop; without these it was an open arc.
#
# The sweep learns from what a *run* recorded -- its duration and its purge
# columns -- which the operator fills in on completion today. It does not need
# a printer to answer, which is why the loop can close now rather than waiting
# on an adapter that reports consumption.
# ---------------------------------------------------------------------------

#: How far back a sweep looks for runs to learn from.
#:
#: A quarter, matching the realised-margin sweep. Long enough that a
#: slow-moving item accumulates the minimum number of outcomes the operator
#: asked for (FR-042a), short enough that what is learned describes how the
#: shop prints now.
DEFAULT_LOOKBACK_DAYS = 90


async def learn_for_tenant(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    since: Optional[date] = None,
) -> dict[str, "VarianceDecision"]:
    """Consider every model with runs completed since ``since``.

    Returns one decision per model and field, keyed ``"<model_id>.<field>"``,
    including the fields nothing moved — an operator asking why their print
    time did not change needs the reason, not silence.

    Nothing is committed here; the caller's transaction decides, so one sweep
    over a catalogue commits once or not at all.
    """
    from app.models.model import Model
    from app.models.production_run import ProductionRun, ProductionRunItem

    if since is None:
        since = clock.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    # Completed runs only. An in-progress run's duration is how long it has been
    # going, not how long it took, and a cancelled one is not evidence of
    # anything. A failed run is excluded for the same reason its waste is not a
    # purge figure: the yield line is what accounts for failure (FR-015).
    rows = (
        await db.execute(
            select(ProductionRunItem.model_id, ProductionRun.id)
            .join(ProductionRun, ProductionRunItem.production_run_id == ProductionRun.id)
            .where(
                ProductionRun.tenant_id == tenant.id,
                ProductionRun.status == "completed",
                ProductionRun.completed_at.is_not(None),
                func.date(ProductionRun.completed_at) >= since,
            )
        )
    ).all()

    if not rows:
        logger.info(
            "No runs completed since %s for tenant %s, so there is nothing to learn from",
            since,
            tenant.id,
        )
        return {}

    by_model: dict[Any, set[Any]] = {}
    for model_id, run_id in rows:
        by_model.setdefault(model_id, set()).add(run_id)

    policy = await _resolved_policy(db, tenant)
    decisions: dict[str, VarianceDecision] = {}

    for model_id, run_ids in by_model.items():
        model = (
            await db.execute(
                select(Model).where(Model.id == model_id).options(selectinload(Model.materials))
            )
        ).scalar_one_or_none()
        if model is None:  # pragma: no cover - a run cannot outlive its model
            continue

        # Items, plates and per-spool actuals are what yield and part weight
        # are learned from (T256).
        runs = (
            (
                await db.execute(
                    select(ProductionRun)
                    .where(ProductionRun.id.in_(run_ids))
                    .options(
                        selectinload(ProductionRun.items),
                        selectinload(ProductionRun.plates),
                        selectinload(ProductionRun.materials),
                    )
                )
            )
            .scalars()
            .all()
        )

        for field_name, decision in (
            await learn_from_runs(db, tenant, model, runs, policy=policy)
        ).items():
            decisions[f"{model_id}.{field_name}"] = decision
            if decision.applied:
                logger.info(
                    "Model %s: %s updated from %d run(s) -- %s",
                    model_id,
                    field_name,
                    len(decision.run_ids),
                    decision.reason,
                )
            elif decision.proposal is not None:
                # A held proposal is the interesting outcome: pricing keeps the
                # current estimate and the operator has something to accept or
                # reject (FR-042b, FR-042e).
                logger.warning(
                    "Model %s: %s diverges beyond the threshold and is held for review -- %s",
                    model_id,
                    field_name,
                    decision.reason,
                )

    return decisions


async def _resolved_policy(db: AsyncSession, tenant: "Tenant") -> "CostPolicy":
    """The tenant's thresholds, read once for the whole sweep."""
    from app.services.pricing_policy import resolve_cost_policy

    return await resolve_cost_policy(db, tenant)


async def _learn_all(tenant_id: Optional[uuid.UUID] = None) -> int:
    """Sweep one tenant, or every active one. Returns the decision count."""
    from app.database import async_session_maker
    from app.models.tenant import Tenant

    total = 0
    async with async_session_maker() as db:
        query = select(Tenant)
        if tenant_id is not None:
            query = query.where(Tenant.id == tenant_id)
        else:
            query = query.where(Tenant.is_active.is_(True))

        for tenant in (await db.execute(query)).scalars().all():
            try:
                decisions = await learn_for_tenant(db, tenant)
                # One commit per tenant: a sweep that fell over on tenant four
                # must not discard what it learned for tenants one to three.
                await db.commit()
                total += len(decisions)
            except Exception:  # pragma: no cover - one tenant must not stop the rest
                await db.rollback()
                logger.error(
                    "Telemetry learning sweep failed for tenant %s", tenant.id, exc_info=True
                )
    return total


@celery_app.task(name="telemetry.learn", bind=True, max_retries=0)
def learn_from_production_runs_task(self: Any, tenant_id: Optional[str] = None) -> int:
    """Celery entry point for the periodic learning sweep.

    ``max_retries=0``: a retry would reconsider the same runs, and
    ``variance_service`` already refuses to re-propose from outcomes that were
    rejected (FR-042d) — so a retry buys nothing and risks a second warning
    about the same figure.
    """
    return asyncio.run(_learn_all(uuid.UUID(str(tenant_id)) if tenant_id else None))


@celery_app.task(name="telemetry.ingest_run", bind=True, max_retries=0)
def ingest_run_actuals_task(self: Any, run_id: str) -> dict[str, Any]:
    """Record what one finished run used, from its machine or its slicer file.

    Dispatched per run rather than scheduled: the moment worth asking a printer
    what a job consumed is when the job ends, and a sweep would ask long after
    the machine has moved on. A caller that holds an adapter passes it to
    :func:`ingest_run_actuals` directly; this entry point is the one for a
    caller that holds only a run id.

    The returned figures are strings because a Celery result is JSON and an
    amount must not cross it as a float (Constitution IV).
    """
    return asyncio.run(_ingest_one(uuid.UUID(str(run_id))))


async def _ingest_one(run_id: uuid.UUID) -> dict[str, Any]:
    from app.database import async_session_maker
    from app.models.production_run import ProductionRun
    from app.models.tenant import Tenant

    async with async_session_maker() as db:
        run = (
            await db.execute(select(ProductionRun).where(ProductionRun.id == run_id))
        ).scalar_one_or_none()
        if run is None:
            logger.warning("No run %s to ingest actuals for", run_id)
            return {"source": "none", "written": [], "reason": "run not found"}

        tenant = (
            await db.execute(select(Tenant).where(Tenant.id == run.tenant_id))
        ).scalar_one_or_none()
        if tenant is None:  # pragma: no cover - a run cannot outlive its tenant
            return {"source": "none", "written": [], "reason": "tenant not found"}

        actuals = await ingest_run_actuals(db, tenant, run)
        await db.commit()

        logger.info(
            "Run %s: actuals from %s, wrote %s",
            run_id,
            actuals.source,
            ", ".join(actuals.written) or "nothing",
        )
        return {
            "source": actuals.source,
            "grams": str(actuals.grams) if actuals.grams is not None else None,
            "print_hours": str(actuals.print_hours) if actuals.print_hours is not None else None,
            "written": list(actuals.written),
            "reason": actuals.reason,
        }


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "LEARNABLE_FROM_RUNS",
    "RunActuals",
    "ingest_run_actuals",
    "ingest_run_actuals_task",
    "learn_for_tenant",
    "learn_from_production_runs_task",
    "learn_from_runs",
]
