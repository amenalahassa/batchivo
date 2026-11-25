"""Model file notes API: pins on a part, resolved or carried from one version to the next."""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.model_file_versions import _model_or_404, rule_error
from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.models.model_file_note import NOTE_SEVERITIES, ModelFileNote
from app.models.user import User
from app.schemas.model_file_note import (
    CarryForwardRequest,
    NoteCreate,
    NoteResponse,
    NoteSource,
    NoteTypeFields,
    NoteUpdate,
    normalise_severity,
)
from app.schemas.model_file_version import PersonRef
from app.services.model_file_note_service import ModelFileNoteService, NoteNotFound
from app.services.model_file_version_service import VersionRuleError

router = APIRouter()


async def _person(db: AsyncSession, user_id: Optional[UUID]) -> Optional[PersonRef]:
    if user_id is None:
        return None
    user = await db.get(User, user_id)
    if user is None:
        return None
    return PersonRef(id=user.id, name=user.full_name or user.email)


async def _response(db: AsyncSession, note: ModelFileNote, ghost: bool = False) -> NoteResponse:
    author = await _person(db, note.author_user_id)
    return NoteResponse(
        id=note.id,
        number=note.number,
        model_file_id=note.model_file_id,
        version_id=note.version_id,
        position=(note.pos_x, note.pos_y, note.pos_z),
        normal=(note.normal_x, note.normal_y, note.normal_z),
        layer=note.layer,
        text=note.text,
        status=note.status,
        resolved_in_version_id=note.resolved_in_version_id,
        carried_to_version_id=note.carried_to_version_id,
        carried_from_note_id=note.carried_from_note_id,
        author=author,
        created_at=note.created_at,
        archived_at=note.archived_at,
        ghost=ghost,
        source=note.source,
        rule_id=note.rule_id,
        severity=note.severity,
        measured_value=note.measured_value,
        expected_value=note.expected_value,
        value_unit=note.value_unit,
        dismissal_reason=note.dismissal_reason,
        dismissed_at=note.dismissed_at,
        dismissed_by=await _person(db, note.dismissed_by_user_id),
    )


def _type_fields(data: NoteTypeFields) -> dict:
    """The type fields the caller actually sent (spec 009)."""
    return {
        field: getattr(data, field)
        for field in NoteTypeFields.model_fields
        if field in data.model_fields_set
    }


def _not_found(exc: NoteNotFound) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/{model_id}/file-notes", response_model=list[NoteResponse])
async def list_file_notes(
    model_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    file_id: Optional[UUID] = None,
    version_id: Optional[UUID] = None,
    note_status: Optional[Literal["open", "resolved", "carried_forward", "dismissed"]] = Query(
        None, alias="status"
    ),
    include_archived: bool = False,
    ghosts_for_file_id: Optional[UUID] = None,
    source: Optional[NoteSource] = None,
    severity: Optional[str] = Query(
        None, description="info, warning or failure (Preflight's attention / échec accepted)"
    ),
) -> list[NoteResponse]:
    """A model's notes; with ``ghosts_for_file_id``, plus earlier versions' open notes (FR-029)."""
    await _model_or_404(db, tenant, model_id)
    severity_value = normalise_severity(severity)
    if severity_value is not None and severity_value not in NOTE_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="severity must be info, warning or failure",
        )
    service = ModelFileNoteService(db, tenant, user)
    try:
        notes = await service.list_notes(
            model_id,
            file_id=file_id,
            version_id=version_id,
            status=note_status,
            include_archived=include_archived,
            ghosts_for_file_id=ghosts_for_file_id,
            source=source,
            severity=severity_value,
        )
    except NoteNotFound as exc:
        raise _not_found(exc) from exc
    return [await _response(db, note, ghost) for note, ghost in notes]


@router.post(
    "/{model_id}/files/{file_id}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_file_note(
    model_id: UUID,
    file_id: UUID,
    data: NoteCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> NoteResponse:
    """Pin a note on a point of the part (FR-025, FR-026)."""
    await _model_or_404(db, tenant, model_id)
    service = ModelFileNoteService(db, tenant, user)
    try:
        note = await service.create(
            model_id,
            file_id,
            position=data.position,
            normal=data.normal,
            text=data.text,
            layer=data.layer,
            note_type=_type_fields(data),
        )
    except NoteNotFound as exc:
        raise _not_found(exc) from exc
    except VersionRuleError as exc:
        raise rule_error(exc) from exc
    await db.commit()
    await db.refresh(note)
    return await _response(db, note)


@router.patch("/{model_id}/file-notes/{note_id}", response_model=NoteResponse)
async def update_file_note(
    model_id: UUID,
    note_id: UUID,
    data: NoteUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> NoteResponse:
    """Edit, move, resolve, dismiss (with a reason) or reopen a note."""
    await _model_or_404(db, tenant, model_id)
    service = ModelFileNoteService(db, tenant, user)
    try:
        note = await service.get(model_id, note_id)
        await service.update(
            note,
            text=data.text,
            position=data.position,
            normal=data.normal,
            status=data.status,
            resolved_in_version_id=data.resolved_in_version_id,
            dismissal_reason=data.dismissal_reason,
            note_type=_type_fields(data),
        )
    except NoteNotFound as exc:
        raise _not_found(exc) from exc
    except VersionRuleError as exc:
        raise rule_error(exc) from exc
    await db.commit()
    await db.refresh(note)
    return await _response(db, note)


@router.post(
    "/{model_id}/file-notes/{note_id}/carry-forward",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def carry_file_note_forward(
    model_id: UUID,
    note_id: UUID,
    data: CarryForwardRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> NoteResponse:
    """Continue an open note on a newer version's file (FR-029a)."""
    await _model_or_404(db, tenant, model_id)
    service = ModelFileNoteService(db, tenant, user)
    try:
        note = await service.get(model_id, note_id)
        carried = await service.carry_forward(note, data.target_file_id)
    except NoteNotFound as exc:
        raise _not_found(exc) from exc
    except VersionRuleError as exc:
        raise rule_error(exc) from exc
    await db.commit()
    await db.refresh(carried)
    return await _response(db, carried)
