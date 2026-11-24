"""Product ideas API endpoints (spec 007).

Thin handlers: every rule lives in ``IdeaService``. Reads are open to every
role of the tenant (a viewer reads); writes require member or above; converting
to a product also requires admin, checked by the service (FR-002).
"""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.schemas.idea import (
    ConvertRequest,
    ConvertResponse,
    IdeaCreate,
    IdeaDetail,
    IdeaEntryCreate,
    IdeaEntryList,
    IdeaEntryResponse,
    IdeaEntryUpdate,
    IdeaListResponse,
    IdeaSource,
    IdeaStatus,
    IdeaUpdate,
    ImageUploadResult,
    ImportItem,
    ImportRequest,
    ImportResult,
    IterationCreate,
    ParseReportRequest,
    ParseReportResponse,
)
from app.services.idea_service import IdeaService
from app.services.pain_point_report_parser import parse_report

router = APIRouter()


# ============================================
# Ideas
# ============================================


@router.get("", response_model=IdeaListResponse)
async def list_ideas(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    status_filter: Optional[list[IdeaStatus]] = Query(None, alias="status"),
    tag: Optional[list[str]] = Query(None, description="Ideas carrying every tag given"),
    source: Optional[IdeaSource] = None,
    search: Optional[str] = Query(None, max_length=200),
    archived: Literal["false", "true", "all"] = "false",
    sort: Literal["updated", "score", "created"] = "updated",
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> IdeaListResponse:
    """List the tenant's ideas, filtered, sorted and paginated."""
    return await IdeaService(db, tenant, user).list_ideas(
        statuses=status_filter,
        tags=tag,
        source=source,
        search=search,
        archived=archived,
        sort=sort,
        skip=skip,
        limit=limit,
    )


@router.get("/tags", response_model=list[str])
async def list_idea_tags(user: CurrentUser, tenant: CurrentTenant, db: TenantDB) -> list[str]:
    """Distinct tags of the tenant's ideas."""
    return await IdeaService(db, tenant, user).list_tags()


@router.post("", response_model=IdeaDetail, status_code=status.HTTP_201_CREATED)
async def create_idea(
    data: IdeaCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> IdeaDetail:
    """Create an idea."""
    return await IdeaService(db, tenant, user).create(data)


@router.post("/import", response_model=ImportResult)
async def import_ideas(
    data: ImportRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ImportResult:
    """Create ideas in bulk from report problems; ``dry_run`` only classifies them."""
    return await IdeaService(db, tenant, user).import_items(data.items, data.dry_run)


@router.post("/import/parse-report", response_model=ParseReportResponse)
async def parse_pain_point_report(
    data: ParseReportRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
) -> ParseReportResponse:
    """Read a pain-point report (markdown) into import items, without writing anything."""
    items, warnings = parse_report(data.text)
    valid: list[ImportItem] = []
    for item in items:
        try:
            valid.append(ImportItem.model_validate(item))
        except ValueError as exc:
            warnings.append(f"“{item.get('title')}” cannot be imported: {exc}")
    return ParseReportResponse(items=valid, warnings=warnings)


@router.get("/{idea_id}", response_model=IdeaDetail)
async def get_idea(
    idea_id: UUID, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> IdeaDetail:
    """One idea."""
    service = IdeaService(db, tenant, user)
    return await service.to_detail(await service.get_idea(idea_id))


@router.patch("/{idea_id}", response_model=IdeaDetail)
async def update_idea(
    idea_id: UUID,
    data: IdeaUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> IdeaDetail:
    """Update an idea: fields, status, scores, tags, cover, archived."""
    return await IdeaService(db, tenant, user).update(idea_id, data)


@router.delete("/{idea_id}", response_model=IdeaDetail)
async def archive_idea(
    idea_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> IdeaDetail:
    """Archive an idea (it can be restored)."""
    return await IdeaService(db, tenant, user).archive(idea_id)


# ============================================
# Timeline
# ============================================


@router.get("/{idea_id}/entries", response_model=IdeaEntryList)
async def list_entries(
    idea_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    archived: bool = Query(False, description="Include archived entries"),
) -> IdeaEntryList:
    """An idea's timeline."""
    return await IdeaService(db, tenant, user).list_entries(idea_id, include_archived=archived)


@router.post(
    "/{idea_id}/entries", response_model=IdeaEntryResponse, status_code=status.HTTP_201_CREATED
)
async def create_entry(
    idea_id: UUID,
    data: IdeaEntryCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> IdeaEntryResponse:
    """Add a note, link, measurement or decision."""
    return await IdeaService(db, tenant, user).add_entry(idea_id, data)


@router.post(
    "/{idea_id}/entries/images",
    response_model=ImageUploadResult,
    status_code=status.HTTP_201_CREATED,
)
async def upload_entry_images(
    idea_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
    files: list[UploadFile] = File(..., description="JPEG, PNG or WebP, up to 10 MB each"),
    kind: Literal["image", "sketch"] = Form("image"),
) -> ImageUploadResult:
    """Upload one or several images as entries; bad files are refused one by one."""
    return await IdeaService(db, tenant, user).add_images(idea_id, files, kind)


@router.patch("/{idea_id}/entries/{entry_id}", response_model=IdeaEntryResponse)
async def update_entry(
    idea_id: UUID,
    entry_id: UUID,
    data: IdeaEntryUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> IdeaEntryResponse:
    """Edit, pin, archive or restore an entry."""
    return await IdeaService(db, tenant, user).update_entry(idea_id, entry_id, data)


@router.delete("/{idea_id}/entries/{entry_id}", response_model=IdeaEntryResponse)
async def archive_entry(
    idea_id: UUID,
    entry_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> IdeaEntryResponse:
    """Archive an entry (clears the cover if it was the cover)."""
    return await IdeaService(db, tenant, user).archive_entry(idea_id, entry_id)


@router.get("/{idea_id}/entries/{entry_id}/image")
async def get_entry_image(
    idea_id: UUID,
    entry_id: UUID,
    request: Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    variant: Literal["full", "thumb"] = "full",
) -> Response:
    """
    An idea image, only for a signed-in user of the owning shop (clarification Q1).

    Never cached by shared caches (``Cache-Control: private``).
    """
    content, content_type, entry = await IdeaService(db, tenant, user).open_image(
        idea_id, entry_id, variant
    )
    etag = f'"{entry.id}-{variant}"'
    headers = {"Cache-Control": "private, max-age=3600", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=content, media_type=content_type, headers=headers)


@router.post(
    "/{idea_id}/iterations", response_model=IdeaEntryList, status_code=status.HTTP_201_CREATED
)
async def start_iteration(
    idea_id: UUID,
    data: IterationCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> IdeaEntryList:
    """Start the idea's next iteration, optionally with a note."""
    return await IdeaService(db, tenant, user).start_iteration(idea_id, data.note)


# ============================================
# Conversion
# ============================================


@router.post(
    "/{idea_id}/convert", response_model=ConvertResponse, status_code=status.HTTP_201_CREATED
)
async def convert_idea(
    idea_id: UUID,
    data: ConvertRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ConvertResponse:
    """Turn an idea into a model, or a product with its model."""
    return await IdeaService(db, tenant, user).convert(idea_id, data)
