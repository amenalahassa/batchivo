"""Letting observed outcomes move an estimate, safely (task T104, FR-042).

One mechanism with one exception. The mechanism: once enough recorded outcomes
agree, the estimate they measure updates itself to their rolling average and
its origin becomes ``observed`` (FR-042a, FR-042f). The exception, and the
reason this module is not three lines: **an observation that disagrees with the
estimate by a large margin is more often a faulty measurement than a
discovery** (FR-042b).

A smart plug reporting kilowatts where the schema expects watts. A print logged
at 95 hours instead of 9.5. A spool weighed before it was dried. Each of those
is a plausible reading that would move a price, and the price would be wrong in
a way nobody could trace back to a sensor. So beyond the operator's divergence
threshold the update is written to ``estimate_revisions`` and held, **pricing
keeps using the current estimate** (FR-042e), and a person decides.

## The four rules that are easy to get wrong

**Held means held.** While a proposal is pending the figure does not move and
its origin does not become ``observed``. The tempting shortcut — apply it and
flag it — prices every sale against a reading nobody has checked.

**At the threshold, apply.** An operator who sets 25% means "up to a quarter
out is plausible". FR-042b says *beyond*, so exactly 25% applies.

**A rejection is about a divergence, not about a field.** FR-042d has two
halves and both are load-bearing: the same outcomes must not raise the question
again, and *new* outcomes must still be able to. Suppressing for ever would
silence a field that really has changed — a new nozzle, a new filament, a
re-sliced model. Nagging for ever makes the review screen useless. So a
proposal is suppressed exactly when it contains nothing that was not already
rejected.

**An operator decision is never touched.** FR-042g and FR-002. Not held as a
proposal either: a proposal invites acceptance, and there is nothing here for
an operator to accept about a figure they themselves stated. It is refused.

## Supersede, never queue

A later proposal on the same figure replaces a pending one (data-model.md). Two
pending proposals on one figure make "accept" ambiguous, and the newer one is
always built from at least as many outcomes. The superseded row is **deleted**
rather than marked rejected: a rejection is a person's decision, it is what
FR-042d reads to decide whether to propose again, and manufacturing one here
would suppress future proposals on the strength of something nobody decided.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Iterable, Optional, Sequence

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.estimate_revision import EstimateRevision
from app.services.provenance import (
    ProvenanceNotEditable,
    origins_for,
    record_origin,
    registry_entry,
)

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.user import User

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
HUNDRED = Decimal("100")

#: Precision the stored observed value and divergence are quantised to. Six
#: and four places respectively match the columns; carrying more would be
#: rounded by the driver rather than by a decision made here.
VALUE_PRECISION = Decimal("0.000001")
DIVERGENCE_PRECISION = Decimal("0.0001")


class NotLearnable(PermissionError):
    """Raised where this mechanism must not touch a figure at all.

    Distinct from "held as a proposal". A proposal invites an operator to
    accept it, and there is nothing to accept about a figure the operator
    themselves decided (FR-002, FR-042g) -- so those are refused outright
    rather than queued for a review that should not happen.
    """


@dataclass(frozen=True)
class Outcome:
    """One recorded outcome bearing on one estimated figure.

    ``run_id`` is the evidence identifier and is what FR-042d compares: two
    proposals built from the same outcomes are the same question asked twice.
    It is a string rather than a UUID because an outcome may come from a
    production run, a print log or a meter reading, and forcing one id type
    would make the second and third unrepresentable.
    """

    run_id: str
    value: Decimal
    observed_on: date


@dataclass
class VarianceDecision:
    """What the mechanism did, and why.

    ``reason`` is in words because every one of these outcomes is something an
    operator may ask about: why did my figure move, why did it not, why am I
    being asked again.
    """

    applied: bool
    reason: str
    observed_value: Optional[Decimal] = None
    divergence: Optional[Decimal] = None
    proposal: Optional[EstimateRevision] = None
    #: Set when this proposal replaced a pending one, so the caller can say so
    #: rather than leaving a proposal to disappear silently.
    superseded_id: Optional[uuid.UUID] = None
    run_ids: frozenset[str] = field(default_factory=frozenset)


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


def rolling_average(outcomes: Sequence[Outcome]) -> Optional[Decimal]:
    """The mean of the outcomes' values, exact and unrounded.

    ``None`` for an empty sequence rather than zero: no outcomes is not an
    observation of zero, and returning zero here would propose a figure of
    zero for every field nobody has measured.

    Unrounded on purpose (Constitution IV). Rounding here would seed the
    divergence comparison with an error, which near a threshold boundary
    decides whether an operator is asked a question.
    """
    if not outcomes:
        return None
    total = sum((Decimal(str(outcome.value)) for outcome in outcomes), ZERO)
    return total / Decimal(len(outcomes))


def divergence_pct(current: Decimal, observed: Decimal) -> Optional[Decimal]:
    """How far ``observed`` sits from ``current``, as an unsigned percentage.

    Unsigned because a reading 30% low is exactly as suspect as one 30% high,
    and the threshold is a statement about implausibility rather than about
    direction.

    ``None`` where the current estimate is zero. A figure nobody set is not 0%
    different from every observation; dividing would either raise or, caught,
    read as "no divergence" and apply any reading at all. The caller decides
    what to do with an unmeasurable divergence, and this module's answer is to
    hold it for review.
    """
    current = Decimal(str(current))
    observed = Decimal(str(observed))
    if current == ZERO:
        return None
    return (abs(observed - current) / abs(current) * HUNDRED).quantize(DIVERGENCE_PRECISION)


def _coerce_to_field(entity: object, field_name: str, value: Decimal):
    """``value`` in the type the column holds.

    An integer column handed a ``Decimal`` with a fraction is either rejected
    by the driver or silently truncated by it, and a truncation nobody chose is
    a figure nobody can explain. Rounding half-up here makes it a decision.
    """
    current = getattr(entity, field_name, None)
    if isinstance(current, bool):  # pragma: no cover - no boolean estimates today
        raise NotLearnable(f"{field_name} is not a numeric estimate")
    if isinstance(current, int):
        return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if isinstance(current, float):
        # A float column is a pre-existing wart, not something to introduce.
        # Going through `str` keeps the value exactly as decided here.
        return float(str(value))
    return value


def _as_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


# ---------------------------------------------------------------------------
# Reading proposals
# ---------------------------------------------------------------------------


async def pending_revision(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
) -> Optional[EstimateRevision]:
    """The pending proposal on one figure, if there is one.

    At most one by construction -- the partial unique index on the table says
    so -- which is what lets the review screen show "this figure has a pending
    revision" without having to explain which of several.
    """
    return (
        (
            await db.execute(
                select(EstimateRevision).where(
                    EstimateRevision.tenant_id == tenant.id,
                    EstimateRevision.entity_type == entity_type,
                    EstimateRevision.entity_id == entity_id,
                    EstimateRevision.field_name == field_name,
                    EstimateRevision.state == "pending",
                )
            )
        )
        .scalars()
        .first()
    )


async def list_revisions(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    state: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[uuid.UUID] = None,
    limit: int = 200,
) -> list[EstimateRevision]:
    """Proposals for this tenant, newest first.

    Always filtered by tenant (Constitution I); the parameter is not optional
    and there is no code path here that omits it.
    """
    conditions = [EstimateRevision.tenant_id == tenant.id]
    if state is not None:
        conditions.append(EstimateRevision.state == state)
    if entity_type is not None:
        conditions.append(EstimateRevision.entity_type == entity_type)
    if entity_id is not None:
        conditions.append(EstimateRevision.entity_id == entity_id)

    return list(
        (
            await db.execute(
                select(EstimateRevision)
                .where(*conditions)
                .order_by(EstimateRevision.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def pending_revision_fields(
    db: AsyncSession,
    tenant: "Tenant",
    entity_type: str,
    entity_id: uuid.UUID,
) -> frozenset[str]:
    """Field names on one entity that currently have a pending proposal.

    This is what FR-042e's flag is read from: a breakdown line whose field is
    in this set is diverging from observation and says so, rather than quietly
    continuing to use a figure the evidence disputes.
    """
    rows = await list_revisions(
        db, tenant, state="pending", entity_type=entity_type, entity_id=entity_id
    )
    return frozenset(row.field_name for row in rows)


async def pending_revisions_for(
    db: AsyncSession,
    tenant: "Tenant",
    entities: Iterable[tuple[str, uuid.UUID]],
) -> frozenset[tuple[str, uuid.UUID, str]]:
    """Which fields across several entities currently have a pending proposal.

    The batch form of :func:`pending_revision_fields`, keyed the same way as
    :func:`app.services.provenance.origins_for` so that a cost breakdown can
    resolve both in two queries rather than one per line. A breakdown walks a
    bundle: a product, its models, their printer configs and whatever is below
    them, and asking per field would be a query per figure on the screen.

    One query, always tenant-filtered (Constitution I).
    """
    pairs = sorted({(entity_type, entity_id) for entity_type, entity_id in entities})
    if not pairs:
        return frozenset()

    rows = (
        (
            await db.execute(
                select(
                    EstimateRevision.entity_type,
                    EstimateRevision.entity_id,
                    EstimateRevision.field_name,
                ).where(
                    EstimateRevision.tenant_id == tenant.id,
                    EstimateRevision.state == "pending",
                    tuple_(
                        EstimateRevision.entity_type,
                        EstimateRevision.entity_id,
                    ).in_(pairs),
                )
            )
        )
        .tuples()
        .all()
    )
    return frozenset(
        (entity_type, entity_id, field_name) for entity_type, entity_id, field_name in rows
    )


async def _rejected_run_ids(
    db: AsyncSession,
    tenant: "Tenant",
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    field_name: str,
) -> frozenset[str]:
    """Every outcome id behind a rejected proposal on this figure.

    The union across rejections, not the most recent one. FR-042d's question is
    whether a candidate proposal rests on anything that has not already been
    considered and declined, and an outcome rejected two reviews ago has still
    been declined.
    """
    rows = (
        (
            await db.execute(
                select(EstimateRevision).where(
                    EstimateRevision.tenant_id == tenant.id,
                    EstimateRevision.entity_type == entity_type,
                    EstimateRevision.entity_id == entity_id,
                    EstimateRevision.field_name == field_name,
                    EstimateRevision.state == "rejected",
                )
            )
        )
        .scalars()
        .all()
    )
    rejected: set[str] = set()
    for row in rows:
        rejected |= row.run_ids
    return frozenset(rejected)


# ---------------------------------------------------------------------------
# The mechanism
# ---------------------------------------------------------------------------


async def consider_outcomes(
    db: AsyncSession,
    tenant: "Tenant",
    entity: object,
    *,
    entity_type: str,
    field_name: str,
    outcomes: Sequence[Outcome],
    min_outcomes: int,
    divergence_threshold_pct: Decimal,
    user: Optional["User"] = None,
    observed: Optional[Decimal] = None,
) -> VarianceDecision:
    """Apply, hold or refuse an update to one estimated figure.

    ``observed`` is the estimate the outcomes support, for a figure whose
    estimator is not their plain mean: a yield is parts succeeded over parts
    attempted across every run, and under the per-plate mode the root of a
    pooled plate success rate (research D3, T256). Without it the outcomes'
    rolling average is the estimate. The outcomes still decide the minimum
    count and the evidence a rejection is remembered against (FR-042d).

    ``min_outcomes`` and ``divergence_threshold_pct`` are the operator's
    settings (FR-042a, FR-042b) and are required rather than defaulted: a
    default here would be a policy decision made in code, and the one thing
    this mechanism must not do is decide on the operator's behalf how much
    evidence is enough.

    Nothing is committed. The caller's transaction decides, which is what lets
    a batch of outcomes be considered together and rolled back as a unit.
    """
    # Refuses an unregistered field before anything else: a typo would
    # otherwise move a figure nothing reads.
    entry = registry_entry(entity_type, field_name)

    if not entry.learnable:
        raise NotLearnable(
            f"{entity_type}.{field_name} is an operator decision and is never "
            f"updated from observations, whatever the divergence (FR-002, FR-042g)"
        )

    entity_id = getattr(entity, "id")

    recorded = await origins_for(db, tenant, [(entity_type, entity_id)])
    origin = recorded.get((entity_type, entity_id, field_name))
    if origin is not None and origin.source == "policy":
        raise NotLearnable(
            f"{entity_type}.{field_name} is currently an operator decision; an "
            f"observation does not override it (FR-002)"
        )

    run_ids = frozenset(outcome.run_id for outcome in outcomes)

    if len(outcomes) < min_outcomes:
        return VarianceDecision(
            applied=False,
            reason=(
                f"{len(outcomes)} recorded outcome(s); this figure updates once "
                f"{min_outcomes} agree"
            ),
            run_ids=run_ids,
        )

    if observed is None:
        observed = rolling_average(outcomes)
    current = _as_decimal(getattr(entity, field_name, None))

    if observed is None:  # pragma: no cover - guarded by the minimum above
        return VarianceDecision(applied=False, reason="no outcomes to average", run_ids=run_ids)

    divergence = None if current is None else divergence_pct(current, observed)
    observed_on = max(outcome.observed_on for outcome in outcomes)

    # An unmeasurable divergence -- no current estimate, or one of zero -- is
    # held rather than applied. There is nothing to compare against a
    # threshold, and applying an unchecked reading to a figure nobody has set
    # is how a sensor fault becomes a price.
    beyond_threshold = divergence is None or divergence > Decimal(str(divergence_threshold_pct))

    if not beyond_threshold:
        return await _apply(
            db,
            tenant,
            entity,
            entity_type=entity_type,
            field_name=field_name,
            observed=observed,
            observed_on=observed_on,
            divergence=divergence,
            run_ids=run_ids,
            reason=(
                f"{len(outcomes)} outcomes averaging {observed} sit "
                f"{divergence}% from the estimate, within the "
                f"{divergence_threshold_pct}% threshold"
            ),
        )

    # Beyond the threshold. FR-042d: has this question already been asked and
    # declined on exactly this evidence?
    rejected = await _rejected_run_ids(
        db,
        tenant,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
    )
    if run_ids and run_ids <= rejected:
        return VarianceDecision(
            applied=False,
            observed_value=observed,
            divergence=divergence,
            run_ids=run_ids,
            reason=(
                "this change was already rejected from these outcomes; it will be "
                "proposed again when a new outcome is recorded (FR-042d)"
            ),
        )

    superseded = await pending_revision(
        db,
        tenant,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
    )
    superseded_id = superseded.id if superseded is not None else None
    if superseded is not None:
        # Deleted, not marked rejected. A rejection is a person's decision and
        # is what FR-042d reads; manufacturing one here would suppress future
        # proposals on the strength of something nobody decided.
        await db.delete(superseded)
        await db.flush()

    proposal = EstimateRevision(
        tenant_id=tenant.id,
        entity_type=entity_type,
        entity_id=entity_id,
        field_name=field_name,
        # Stored as they stood, not recomputed at review time: the figure may
        # move for an unrelated reason, and the operator must see the
        # comparison that was actually made (FR-042c).
        current_value=(current if current is not None else ZERO).quantize(VALUE_PRECISION),
        observed_value=observed.quantize(VALUE_PRECISION),
        divergence_pct=(divergence if divergence is not None else Decimal("999.9999")),
        derived_from_run_ids=sorted(run_ids),
        state="pending",
        observed_as_of=observed_on,
    )
    db.add(proposal)
    await db.flush()

    logger.info(
        f"Held an estimate revision for {entity_type}.{field_name} on {entity_id}: "
        f"{current} -> {observed} ({divergence}% divergence, threshold "
        f"{divergence_threshold_pct}%)"
    )
    return VarianceDecision(
        applied=False,
        observed_value=observed,
        divergence=divergence,
        proposal=proposal,
        superseded_id=superseded_id,
        run_ids=run_ids,
        reason=(
            f"{len(outcomes)} outcomes averaging {observed} sit "
            f"{divergence}% from the estimate, beyond the "
            f"{divergence_threshold_pct}% threshold, so the change is held for "
            f"review and pricing keeps using the current estimate (FR-042b, FR-042e)"
        ),
    )


async def _apply(
    db: AsyncSession,
    tenant: "Tenant",
    entity: object,
    *,
    entity_type: str,
    field_name: str,
    observed: Decimal,
    observed_on: date,
    divergence: Optional[Decimal],
    run_ids: frozenset[str],
    reason: str,
) -> VarianceDecision:
    """Move the figure and record that observation moved it (FR-042f)."""
    setattr(entity, field_name, _coerce_to_field(entity, field_name, observed))
    db.add(entity)

    await record_origin(
        db,
        tenant,
        entity_type=entity_type,
        entity_id=getattr(entity, "id"),
        field_name=field_name,
        source="observed",
        as_of=observed_on,
        automated=True,
    )
    await db.flush()

    logger.info(
        f"Updated {entity_type}.{field_name} on {getattr(entity, 'id')} to {observed} "
        f"from {len(run_ids)} observed outcome(s)"
    )
    return VarianceDecision(
        applied=True,
        reason=reason,
        observed_value=observed,
        divergence=divergence,
        run_ids=run_ids,
    )


# ---------------------------------------------------------------------------
# Deciding a held proposal
# ---------------------------------------------------------------------------


async def _load_pending(
    db: AsyncSession, tenant: "Tenant", revision_id: uuid.UUID
) -> EstimateRevision:
    """One of this tenant's proposals, still pending.

    Tenant-scoped because the id arrives from a request (Constitution I), and a
    ``LookupError`` rather than ``None`` so a caller cannot accidentally treat
    "not yours" as "nothing to do".
    """
    revision = (
        (
            await db.execute(
                select(EstimateRevision).where(
                    EstimateRevision.id == revision_id,
                    EstimateRevision.tenant_id == tenant.id,
                )
            )
        )
        .scalars()
        .first()
    )
    if revision is None:
        raise LookupError(f"no estimate revision {revision_id} for this tenant")
    if revision.state != "pending":
        raise ValueError(
            f"estimate revision {revision_id} was already {revision.state}; a "
            f"decided proposal is not reopened, because its fate is part of the "
            f"record that decides whether to propose again (FR-042d)"
        )
    return revision


async def accept_revision(
    db: AsyncSession,
    tenant: "Tenant",
    revision_id: uuid.UUID,
    *,
    user: Optional["User"] = None,
    entity: Optional[object] = None,
) -> EstimateRevision:
    """Apply a held proposal, whole (FR-042c).

    ``entity`` may be passed where the caller already has it loaded; otherwise
    it is fetched from the proposal's ``entity_type`` and ``entity_id``. The
    figure moves and its origin becomes ``observed``, dated with the day the
    observation covers rather than today -- the evidence is as old as it is.
    """
    revision = await _load_pending(db, tenant, revision_id)
    subject = entity if entity is not None else await _load_entity(db, tenant, revision)

    if subject is not None:
        setattr(
            subject,
            revision.field_name,
            _coerce_to_field(subject, revision.field_name, Decimal(str(revision.observed_value))),
        )
        db.add(subject)

        try:
            await record_origin(
                db,
                tenant,
                entity_type=revision.entity_type,
                entity_id=revision.entity_id,
                field_name=revision.field_name,
                source="observed",
                as_of=revision.observed_as_of,
                automated=True,
            )
        except ProvenanceNotEditable:
            # The figure became an operator decision while the proposal sat
            # there. The decision wins (FR-002), so the acceptance is refused
            # rather than silently overriding it.
            raise NotLearnable(
                f"{revision.entity_type}.{revision.field_name} became an operator "
                f"decision while this proposal was pending; the decision stands "
                f"(FR-002)"
            ) from None

    revision.state = "accepted"
    revision.reviewed_by_user_id = user.id if user is not None else None
    revision.reviewed_at = clock.now()
    db.add(revision)
    await db.flush()

    logger.info(
        f"Accepted estimate revision {revision_id}: "
        f"{revision.entity_type}.{revision.field_name} -> {revision.observed_value}"
    )
    return revision


async def reject_revision(
    db: AsyncSession,
    tenant: "Tenant",
    revision_id: uuid.UUID,
    *,
    user: Optional["User"] = None,
) -> EstimateRevision:
    """Decline a held proposal, leaving the estimate untouched.

    The outcomes behind it stay on the row, which is what stops the same
    question being asked again while still letting a new outcome raise it
    (FR-042d).
    """
    revision = await _load_pending(db, tenant, revision_id)
    revision.state = "rejected"
    revision.reviewed_by_user_id = user.id if user is not None else None
    revision.reviewed_at = clock.now()
    db.add(revision)
    await db.flush()

    logger.info(
        f"Rejected estimate revision {revision_id} for "
        f"{revision.entity_type}.{revision.field_name}; the estimate is unchanged"
    )
    return revision


#: The ORM class behind each provenance entity type, for loading the subject of
#: a proposal. Kept as a lazy import map rather than module-level imports to
#: avoid a circular import at startup: several of these modules import services
#: that import this one.
_ENTITY_LOADERS: dict[str, tuple[str, str]] = {
    "model": ("app.models.model", "Model"),
    "model_material": ("app.models.model_material", "ModelMaterial"),
    "model_component": ("app.models.model_component", "ModelComponent"),
    "model_printer_config": ("app.models.model_printer_config", "ModelPrinterConfig"),
    "product": ("app.models.product", "Product"),
    "printer": ("app.models.printer", "Printer"),
    "spool": ("app.models.spool", "Spool"),
    "filament_purchase": ("app.models.filament_purchase", "FilamentPurchase"),
    "sales_channel": ("app.models.sales_channel", "SalesChannel"),
    "fee_rule": ("app.models.fee_rule", "FeeRule"),
    "shipping_profile": ("app.models.shipping_profile", "ShippingProfile"),
}


async def _load_entity(
    db: AsyncSession, tenant: "Tenant", revision: EstimateRevision
) -> Optional[object]:
    """The record a proposal is about, scoped to the tenant where it can be.

    Returns ``None`` for an entity type with no loader rather than raising: a
    proposal whose subject cannot be loaded should report that it could not be
    applied, not fail the request.
    """
    import importlib

    target = _ENTITY_LOADERS.get(revision.entity_type)
    if target is None:  # pragma: no cover - every registered type has a loader
        logger.warning(
            f"No loader for provenance entity type {revision.entity_type!r}; "
            f"revision {revision.id} cannot be applied automatically"
        )
        return None

    module_name, class_name = target
    model_class = getattr(importlib.import_module(module_name), class_name)

    conditions = [model_class.id == revision.entity_id]
    # Not every one of these carries `tenant_id` directly -- a model material
    # belongs to a model, which belongs to a tenant -- so the filter is applied
    # where the column exists and the parent's scope covers the rest.
    if hasattr(model_class, "tenant_id"):
        conditions.append(model_class.tenant_id == tenant.id)

    return (await db.execute(select(model_class).where(*conditions))).scalars().first()
