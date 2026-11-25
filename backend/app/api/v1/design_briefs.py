"""Design brief API (spec 009, contracts/api.md "Design briefs").

A brief is read and started from its idea or its model, then read, updated and
listed by id. Viewers read; members and above write. Deleting a brief is for
signed-in people only (no API token row in `api_token_policy`).
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.schemas.design_brief import (
    DesignBriefResponse,
    DesignBriefRevisionResponse,
    DesignBriefStart,
    DesignBriefUpdate,
    DesignBriefUpdateResult,
    RevisionPart,
)
from app.services.design_brief_service import BriefNotFound, DesignBriefService
from app.services.preflight_intent import IntentInvalid

router = APIRouter()


def _not_found(exc: BriefNotFound) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _invalid(exc: IntentInvalid) -> HTTPException:
    """The same 422 shape as a Pydantic error, so screens and agents read one format."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=[{"loc": list(loc), "msg": msg, "type": "value_error"} for loc, msg in exc.errors],
    )


def _missing() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No design brief yet")


@router.get("/ideas/{idea_id}/design-brief", response_model=DesignBriefResponse)
async def get_idea_brief(
    idea_id: UUID, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> DesignBriefResponse:
    """The idea's design brief."""
    service = DesignBriefService(db, tenant, user)
    try:
        brief = await service.find_for_idea(idea_id)
    except BriefNotFound as exc:
        raise _not_found(exc) from exc
    if brief is None:
        raise _missing()
    return await service.to_response(brief)


@router.post("/ideas/{idea_id}/design-brief", response_model=DesignBriefResponse)
async def start_idea_brief(
    idea_id: UUID,
    data: DesignBriefStart,
    response: Response,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> DesignBriefResponse:
    """Start the idea's brief (201), or return the one it has (200)."""
    service = DesignBriefService(db, tenant, user)
    try:
        brief, created = await service.start_on_idea(idea_id, data)
    except BriefNotFound as exc:
        raise _not_found(exc) from exc
    except IntentInvalid as exc:
        raise _invalid(exc) from exc
    await db.commit()
    await db.refresh(brief)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return await service.to_response(brief)


@router.get("/models/{model_id}/design-brief", response_model=DesignBriefResponse)
async def get_model_brief(
    model_id: UUID, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> DesignBriefResponse:
    """The model's brief, or the brief of the idea it was converted from."""
    service = DesignBriefService(db, tenant, user)
    try:
        brief = await service.find_for_model(model_id)
    except BriefNotFound as exc:
        raise _not_found(exc) from exc
    if brief is None:
        raise _missing()
    return await service.to_response(brief)


@router.post("/models/{model_id}/design-brief", response_model=DesignBriefResponse)
async def start_model_brief(
    model_id: UUID,
    data: DesignBriefStart,
    response: Response,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> DesignBriefResponse:
    """Start the model's brief (201), or return the one it reaches (200)."""
    service = DesignBriefService(db, tenant, user)
    try:
        brief, created = await service.start_on_model(model_id, data)
    except BriefNotFound as exc:
        raise _not_found(exc) from exc
    except IntentInvalid as exc:
        raise _invalid(exc) from exc
    await db.commit()
    await db.refresh(brief)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return await service.to_response(brief)


@router.get("/design-briefs/{brief_id}", response_model=DesignBriefResponse)
async def get_brief(
    brief_id: UUID, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> DesignBriefResponse:
    """One brief by id."""
    service = DesignBriefService(db, tenant, user)
    try:
        brief = await service.get(brief_id)
    except BriefNotFound as exc:
        raise _not_found(exc) from exc
    return await service.to_response(brief)


@router.patch("/design-briefs/{brief_id}", response_model=DesignBriefUpdateResult)
async def update_brief(
    brief_id: UUID,
    data: DesignBriefUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> DesignBriefUpdateResult:
    """Save any subset of intent, risk, plan, parameters and step statuses."""
    service = DesignBriefService(db, tenant, user)
    try:
        brief = await service.get(brief_id)
        created = await service.update(brief, data)
    except BriefNotFound as exc:
        raise _not_found(exc) from exc
    except IntentInvalid as exc:
        raise _invalid(exc) from exc
    await db.commit()
    await db.refresh(brief)
    result = await service.to_response(brief)
    return DesignBriefUpdateResult(**result.model_dump(), created_revisions=created)


@router.get("/design-briefs/{brief_id}/revisions", response_model=list[DesignBriefRevisionResponse])
async def list_brief_revisions(
    brief_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    part: Optional[RevisionPart] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> list[DesignBriefRevisionResponse]:
    """Earlier intents, risk parts and plans of a brief, newest first."""
    service = DesignBriefService(db, tenant, user)
    try:
        brief = await service.get(brief_id)
    except BriefNotFound as exc:
        raise _not_found(exc) from exc
    return await service.list_revisions(brief, part, skip, limit)


@router.delete("/design-briefs/{brief_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brief(
    brief_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> None:
    """Delete a brief and its revisions (signed-in people only)."""
    service = DesignBriefService(db, tenant, user)
    try:
        brief = await service.get(brief_id)
    except BriefNotFound as exc:
        raise _not_found(exc) from exc
    await service.delete(brief)
    await db.commit()
