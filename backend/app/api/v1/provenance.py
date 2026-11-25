"""Provenance and estimate-proposal endpoints (tasks T105, T106).

## The permission split, and why reading is open to everyone

Reading provenance is open to every role including a viewer (FR-007c). This is
deliberate and worth stating because it reads as a privilege: a viewer cannot
judge a margin without seeing which figures behind it are measured and which
are guesses. Hiding that from them would leave them trusting a number whose
basis they cannot check. Visibility is never restricted by role here; only
editing is.

Writing splits by what the figure is (FR-007a):

* A **measured** figure is a measurement, and taking one is a member's job.
* A **policy** figure is a monetary decision, and those need admin or owner.

Which one a field is comes from the provenance registry, not from the request,
so a member cannot reclassify a policy lever as a measurement to get at it.

## What this endpoint refuses

A write to a field whose current origin is ``observed`` is refused with a
``409`` (FR-004). An observed figure is read-only and refreshed only from its
source; letting an operator overwrite the label by hand would make "observed"
mean "somebody typed this", which is the one thing it must not mean.

A write naming ``observed`` as its new source is refused too, for the same
reason: the label belongs to the process that observed the figure.

## Deciding a proposal

Accept and reject are member-level (contracts/pricing-api.md), and a proposal
is taken **whole** (FR-042c). There is no partial acceptance, because a
proposal is a single claim — "these outcomes say the figure is this" — and
accepting half of it would produce a figure no evidence supports.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    CurrentTenant,
    CurrentUser,
    RequireMember,
    TenantDB,
    require_role,
    role_in_tenant,
)
from app.models.pricing_input_provenance import PROVENANCE_SOURCES
from app.models.tenant import Tenant
from app.models.user import User

from app.schemas.provenance import (
    EntityProvenanceResponse,
    EstimateRevisionListResponse,
    EstimateRevisionResponse,
    FieldOriginResponse,
    ProvenanceWriteRequest,
)
from app.services import variance_service
from app.services.pricing_policy import resolve_cost_policy
from app.services.provenance import (
    ProvenanceNotEditable,
    UnknownProvenanceField,
    known_entity_types,
    origins_for_entity,
    record_origin,
    registry_entry,
)
from app.services.variance_service import NotLearnable

logger = logging.getLogger(__name__)

router = APIRouter()

#: Sources an operator may claim for a figure. ``observed`` is absent on
#: purpose: it belongs to the process that observed the figure, and a
#: hand-declared "observed" would make the label mean nothing (FR-004).
OPERATOR_SOURCES: frozenset[str] = frozenset({"measured", "policy", "assumed"})

#: Writing a policy figure is a monetary decision (FR-007a). Which fields those
#: are comes from the registry, not from the request.
POLICY_SOURCES: frozenset[str] = frozenset({"policy"})


def _entity_type_or_422(entity_type: str) -> str:
    """Refuse an entity type the registry does not know.

    A typo would otherwise write a row nothing reads, leaving the figure
    looking unrecorded while the table says otherwise.
    """
    if entity_type not in known_entity_types():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"{entity_type!r} is not a provenance entity type. Known types: "
                f"{', '.join(sorted(known_entity_types()))}"
            ),
        )
    return entity_type


async def _require_write_role(
    db: AsyncSession,
    user: User,
    tenant: Tenant,
    *,
    entity_type: str,
    field_name: str,
    requested_source: str,
) -> Optional[str]:
    """Admin or owner for a policy figure, member for a measurement (FR-007a).

    The classification comes from two places and the stricter wins: a field the
    registry marks un-learnable is an operator decision by construction, and a
    request that *claims* ``policy`` is stating a decision whatever the field
    is. Reading only one of those would let a member either reclassify a lever
    or declare a policy on a measurable field.

    Returns the role the caller actually holds, so the write can record it
    (task T195). `authorised_by_role` existed on the table and this route was
    its only caller, passing `None` explicitly -- so the column was never
    non-null and the provenance screen showed an empty authority for every
    figure, while the tier that permitted the write was resolved right here and
    thrown away (FR-001, FR-007a).
    """
    entry = registry_entry(entity_type, field_name)
    is_policy = requested_source in POLICY_SOURCES or not entry.learnable
    await require_role(user, tenant, db, "admin" if is_policy else "member")
    return await role_in_tenant(db, user.id, tenant.id)


@router.get("/provenance", response_model=EntityProvenanceResponse)
async def get_provenance(
    tenant: CurrentTenant,
    db: TenantDB,
    entity_type: str = Query(..., description="The kind of record, e.g. 'model'"),
    entity_id: UUID = Query(..., description="The record's id"),
) -> EntityProvenanceResponse:
    """Every recorded origin for one entity's numeric fields.

    Open to every role including a viewer (FR-007c): a margin cannot be judged
    without seeing which of the figures behind it are measured and which are
    guesses.

    Returns the registry's view of what the entity *has*, not only what
    somebody got round to recording — a field with no recorded origin is
    reported with its default rather than omitted, because "nobody has said"
    is itself the answer FR-001 wants shown.
    """
    _entity_type_or_422(entity_type)

    origins = await origins_for_entity(db, tenant, entity_type, entity_id)
    policy = await resolve_cost_policy(db, tenant)
    threshold = policy.staleness_threshold_days

    pending = await variance_service.pending_revision_fields(db, tenant, entity_type, entity_id)

    fields: list[FieldOriginResponse] = []
    for field_name, origin in origins.items():
        entry = registry_entry(entity_type, field_name)
        fields.append(
            FieldOriginResponse(
                field_name=field_name,
                source=origin.source,
                as_of=origin.as_of,
                confidence=origin.confidence,
                is_default=origin.is_default,
                is_stale=origin.is_stale(threshold_days=threshold),
                # An observed figure is read-only (FR-004). Reported rather
                # than discovered on a rejected write, so the screen can show
                # the field as not editable instead of offering an edit that
                # will fail.
                editable=origin.source != "observed",
                has_pending_revision=field_name in pending,
                description=entry.description,
            )
        )

    return EntityProvenanceResponse(
        entity_type=entity_type,
        entity_id=entity_id,
        fields=fields,
        observed_count=sum(1 for field in origins.values() if field.is_evidenced),
        total_count=len(fields),
        stale_count=sum(
            1 for field in origins.values() if field.is_stale(threshold_days=threshold)
        ),
        staleness_threshold_days=threshold,
    )


@router.put(
    "/provenance/{entity_type}/{entity_id}/{field_name}",
    response_model=FieldOriginResponse,
)
async def put_provenance(
    entity_type: str,
    entity_id: UUID,
    field_name: str,
    payload: ProvenanceWriteRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> FieldOriginResponse:
    """Record where one figure came from.

    Member for a measurement, admin or owner for a decision (FR-007a).
    Refused with ``409`` for a field whose current origin is ``observed``,
    which is read-only and refreshed only from its source (FR-004).
    """
    _entity_type_or_422(entity_type)

    if payload.source not in PROVENANCE_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{payload.source!r} is not a provenance source",
        )
    if payload.source not in OPERATOR_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"{payload.source!r} cannot be claimed by hand. An observed "
                f"figure is written by the process that observed it; recording "
                f"one here would make the label mean 'somebody typed this' "
                f"(FR-004)"
            ),
        )

    try:
        entry = registry_entry(entity_type, field_name)
    except UnknownProvenanceField as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    authorised_by_role = await _require_write_role(
        db,
        user,
        tenant,
        entity_type=entity_type,
        field_name=field_name,
        requested_source=payload.source,
    )

    try:
        await record_origin(
            db,
            tenant,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            source=payload.source,
            as_of=payload.as_of,
            confidence=payload.confidence,
            measured_by_user_id=user.id,
            # The tier that permitted this write, recorded rather than
            # discarded. `_require_write_role` has just established it, and a
            # reader inspecting a figure's provenance needs to know whether a
            # member measured it or an admin declared it (task T195, FR-001).
            authorised_by_role=authorised_by_role,
        )
    except ProvenanceNotEditable as exc:
        # 409 rather than 403: the operator has the role, and the figure is the
        # obstacle. A 403 would read as "ask an admin", which would not help.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()

    origins = await origins_for_entity(db, tenant, entity_type, entity_id)
    origin = origins[field_name]
    policy = await resolve_cost_policy(db, tenant)
    pending = await variance_service.pending_revision_fields(db, tenant, entity_type, entity_id)

    logger.info(
        f"Recorded provenance for {entity_type}.{field_name} on {entity_id}: "
        f"{payload.source} as of {origin.as_of}"
    )
    return FieldOriginResponse(
        field_name=field_name,
        source=origin.source,
        as_of=origin.as_of,
        confidence=origin.confidence,
        is_default=origin.is_default,
        is_stale=origin.is_stale(threshold_days=policy.staleness_threshold_days),
        editable=origin.source != "observed",
        has_pending_revision=field_name in pending,
        description=entry.description,
    )


# ---------------------------------------------------------------------------
# Estimate proposals (task T106)
# ---------------------------------------------------------------------------


@router.get("/estimate-revisions", response_model=EstimateRevisionListResponse)
async def list_estimate_revisions(
    tenant: CurrentTenant,
    db: TenantDB,
    state: Optional[str] = Query(
        "pending", description="pending | accepted | rejected; omit for all"
    ),
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[UUID] = Query(None),
    limit: int = Query(200, ge=1, le=500),
) -> EstimateRevisionListResponse:
    """Proposals for this tenant, newest first.

    Open to every role, like the rest of the provenance reads (FR-007c): a
    viewer looking at a margin should be able to see that one of the figures
    behind it is disputed by observation.
    """
    if state is not None and state not in ("pending", "accepted", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{state!r} is not a revision state",
        )
    if entity_type is not None:
        _entity_type_or_422(entity_type)

    revisions = await variance_service.list_revisions(
        db,
        tenant,
        state=state,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )
    pending = (
        revisions
        if state == "pending"
        else await variance_service.list_revisions(db, tenant, state="pending")
    )

    return EstimateRevisionListResponse(
        revisions=[EstimateRevisionResponse.model_validate(revision) for revision in revisions],
        total=len(revisions),
        pending_count=len(pending),
    )


async def _decide(
    db: AsyncSession,
    tenant: Tenant,
    user: User,
    revision_id: UUID,
    *,
    accept: bool,
) -> EstimateRevisionResponse:
    """Accept or reject, with the three failures mapped to their own status.

    A proposal that is not this tenant's is a 404 rather than a 403: saying
    "forbidden" would confirm the id exists somewhere, which is a tenant leak
    however small (Constitution I).
    """
    await require_role(user, tenant, db, "member")

    action = variance_service.accept_revision if accept else variance_service.reject_revision
    try:
        revision = await action(db, tenant, revision_id, user=user)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        # Already decided. 409, because the request was well-formed and the
        # state of the world is what refuses it.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except NotLearnable as exc:
        # The figure became an operator decision while the proposal was
        # pending. The decision wins (FR-002).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await db.commit()
    return EstimateRevisionResponse.model_validate(revision)


@router.post(
    "/estimate-revisions/{revision_id}/accept",
    response_model=EstimateRevisionResponse,
)
async def accept_estimate_revision(
    revision_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> EstimateRevisionResponse:
    """Apply a held proposal, whole (FR-042c).

    The figure moves to the observed value and its origin becomes ``observed``,
    dated with the day the observation covers rather than today — the evidence
    is as old as it is, and FR-005's staleness threshold reads that date.
    """
    return await _decide(db, tenant, user, revision_id, accept=True)


@router.post(
    "/estimate-revisions/{revision_id}/reject",
    response_model=EstimateRevisionResponse,
)
async def reject_estimate_revision(
    revision_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> EstimateRevisionResponse:
    """Decline a held proposal, leaving the estimate untouched.

    The outcomes behind it stay on the row. That is what stops the same
    question being asked again while still letting a new outcome raise it
    (FR-042d) — so a rejection is not a permanent veto on the field.
    """
    return await _decide(db, tenant, user, revision_id, accept=False)
