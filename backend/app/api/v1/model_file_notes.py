"""Model file notes API: pins on a part, resolved or carried from one version to the next."""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.model_file_versions import _model_or_404, rule_error
from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.models.model_file_note import ModelFileNote
from app.models.user import User
from app.schemas.model_file_note import (
    CarryForwardRequest,
    NoteCreate,
    NoteResponse,
    NoteUpdate,
)
from app.schemas.model_file_version import PersonRef
from app.services.model_file_note_service import ModelFileNoteService, NoteNotFound
from app.services.model_file_version_service import VersionRuleError

router = APIRouter()


async def _response(db: AsyncSession, note: ModelFileNote, ghost: bool = False) -> NoteResponse:
    author = None
    if note.author_user_id is not None:
        user = await db.get(User, note.author_user_id)
        if user is not None:
            author = PersonRef(id=user.id, name=user.full_name or user.email)
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
    )


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
    note_status: Optional[Literal["open", "resolved", "carried_forward"]] = Query(
        None, alias="status"
    ),
    include_archived: bool = False,
    ghosts_for_file_id: Optional[UUID] = None,
) -> list[NoteResponse]:
    """A model's notes; with ``ghosts_for_file_id``, plus earlier versions' open notes (FR-029)."""
    await _model_or_404(db, tenant, model_id)
    service = ModelFileNoteService(db, tenant, user)
    try:
        notes = await service.list_notes(
            model_id,
            file_id=file_id,
            version_id=version_id,
            status=note_status,
            include_archived=include_archived,
            ghosts_for_file_id=ghosts_for_file_id,
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
    """Edit, move, resolve or reopen a note."""
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
