"""Model file versions API: list, create and edit versions, review and apply activation."""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.models.model import Model
from app.models.model_file_version import ModelFileVersion
from app.models.user import User
from app.schemas.model_file import ModelFileResponse
from app.schemas.model_file_version import (
    ActivateRequest,
    ActivationPreview,
    FileVersionCreate,
    FileVersionResponse,
    FileVersionUpdate,
    PersonRef,
)
from app.services.model_file_version_service import (
    ModelFileVersionService,
    VersionNotFound,
    VersionRuleError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _model_or_404(db: AsyncSession, tenant, model_id: UUID) -> Model:
    model = (
        await db.execute(select(Model).where(Model.id == model_id, Model.tenant_id == tenant.id))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    return model


def rule_error(exc: VersionRuleError) -> HTTPException:
    """A broken version rule, with its code so the screen can word it."""
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


async def _version_or_404(
    service: ModelFileVersionService, model_id: UUID, version_id: UUID
) -> ModelFileVersion:
    try:
        return await service.get(model_id, version_id)
    except VersionNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")


async def _response(
    service: ModelFileVersionService, version: ModelFileVersion, open_notes: int = 0
) -> FileVersionResponse:
    files = await service.files_of(version.id)
    creator = None
    if version.created_by_user_id is not None:
        user = await service.db.get(User, version.created_by_user_id)
        if user is not None:
            creator = PersonRef(id=user.id, name=user.full_name or user.email)
    return FileVersionResponse(
        id=version.id,
        model_id=version.model_id,
        sequence=version.sequence,
        label=version.label,
        note=version.note,
        is_active=version.is_active,
        print_file_id=version.print_file_id,
        created_by=creator,
        created_at=version.created_at,
        files=[ModelFileResponse.model_validate(f) for f in files],
        has_measurable_file=any(f.measurement_status == "done" for f in files),
        open_note_count=open_notes,
    )


@router.get("/{model_id}/file-versions", response_model=list[FileVersionResponse])
async def list_file_versions(
    model_id: UUID, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> list[FileVersionResponse]:
    """Every version of a model, newest first (FR-010). Any tenant user may read."""
    await _model_or_404(db, tenant, model_id)
    service = ModelFileVersionService(db, tenant, user)
    counts = await service.open_note_counts(model_id)
    return [
        await _response(service, version, counts.get(version.id, 0))
        for version in await service.list_versions(model_id)
    ]


@router.post(
    "/{model_id}/file-versions",
    response_model=FileVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_file_version(
    model_id: UUID,
    data: FileVersionCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> FileVersionResponse:
    """Add a version; it stays inactive unless it is the model's first (FR-009)."""
    model = await _model_or_404(db, tenant, model_id)
    service = ModelFileVersionService(db, tenant, user)
    version = await service.create_version(model, data.label, data.note)
    await db.commit()
    await db.refresh(version)
    return await _response(service, version)


@router.patch("/{model_id}/file-versions/{version_id}", response_model=FileVersionResponse)
async def update_file_version(
    model_id: UUID,
    version_id: UUID,
    data: FileVersionUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> FileVersionResponse:
    """Rename a version, edit its note, or choose an inactive version's print file."""
    await _model_or_404(db, tenant, model_id)
    service = ModelFileVersionService(db, tenant, user)
    version = await _version_or_404(service, model_id, version_id)
    try:
        if data.print_file_id is not None:
            await service.set_print_file(version, data.print_file_id)
        await service.update_version(
            version,
            label=data.label,
            note=data.note,
            note_given="note" in data.model_fields_set,
        )
    except VersionRuleError as exc:
        raise rule_error(exc) from exc
    await db.commit()
    await db.refresh(version)
    return await _response(service, version)


@router.get(
    "/{model_id}/file-versions/{version_id}/activation-preview",
    response_model=ActivationPreview,
)
async def preview_activation(
    model_id: UUID,
    version_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    print_file_id: UUID | None = None,
) -> ActivationPreview:
    """The figures that would change if this version (or this print file) were used (FR-012)."""
    model = await _model_or_404(db, tenant, model_id)
    service = ModelFileVersionService(db, tenant, user)
    version = await _version_or_404(service, model_id, version_id)
    try:
        return await service.activation_preview(model, version, print_file_id)
    except VersionRuleError as exc:
        raise rule_error(exc) from exc


@router.post("/{model_id}/file-versions/{version_id}/activate", response_model=FileVersionResponse)
async def activate_file_version(
    model_id: UUID,
    version_id: UUID,
    data: ActivateRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> FileVersionResponse:
    """Make a version active and write only the chosen figures (FR-012, FR-012a)."""
    model = await _model_or_404(db, tenant, model_id)
    service = ModelFileVersionService(db, tenant, user)
    version = await _version_or_404(service, model_id, version_id)
    try:
        version = await service.activate(model, version, data.apply, data.print_file_id)
    except VersionRuleError as exc:
        raise rule_error(exc) from exc
    return await _response(service, version)
