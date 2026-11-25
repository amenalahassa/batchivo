"""Generative AI API: capabilities, jobs, assets, adoption, provider webhook (spec 008).

Thin routes over ``app.services.genai``. Reading is open to every member of the
tenant, viewers included; starting, canceling, uploading and adopting need the
member role or above (clarification Q3). Domain refusals come back as
``{"detail": {"code", "message"}}`` so screens and agents can branch on ``code``.
"""

import logging
import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.database import get_db
from app.models.generation_job import JOB_STATUSES, GenAIAsset, GenerationJob
from app.models.user import User
from app.schemas.genai import (
    AdoptionInfo,
    AdoptRequest,
    AdoptResponse,
    CapabilitiesResponse,
    CapabilityInfo,
    EstimateResponse,
    GenAIAssetResponse,
    GenerationJobCreate,
    GenerationJobList,
    GenerationJobResponse,
    JobTarget,
    PriceInfo,
    UserRef,
)
from app.services.genai import catalog
from app.services.genai.adoption import AdoptionService, AdoptTarget
from app.services.genai.capabilities import Capability
from app.services.genai.errors import GenAIError, InputInvalid
from app.services.genai.service import GenAIService, JobRequest
from app.services.genai.webhooks import handle_replicate_webhook

logger = logging.getLogger(__name__)

router = APIRouter()
webhook_router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _http(exc: GenAIError) -> HTTPException:
    return HTTPException(status_code=exc.http_status, detail=exc.detail())


def _price(snapshot: dict) -> PriceInfo:
    return PriceInfo(
        unit=str(snapshot.get("unit", "per_run")),
        amount_usd=str(snapshot.get("amount_usd", "0")),
        source=str(snapshot.get("source", "catalog")),
        assumed=bool(snapshot.get("assumed", False)),
    )


def asset_response(asset: GenAIAsset) -> GenAIAssetResponse:
    base = f"/api/v1/genai/assets/{asset.id}/file"
    return GenAIAssetResponse(
        id=asset.id,
        job_id=asset.job_id,
        source=asset.source,
        kind=asset.kind,
        content_type=asset.content_type,
        file_size=asset.file_size,
        width=asset.width,
        height=asset.height,
        position=asset.position,
        original_filename=asset.original_filename,
        ai_generated=asset.ai_generated,
        file_path=base,
        thumbnail_path=f"{base}?variant=thumb" if asset.thumbnail_url else None,
        adoptions=[
            AdoptionInfo(
                owner_type=a.owner_type,
                owner_id=a.owner_id,
                idea_entry_id=a.idea_entry_id,
                product_image_id=a.product_image_id,
                model_file_id=a.model_file_id,
                warning_confirmed=a.warning_confirmed,
                created_at=a.created_at,
            )
            for a in (asset.adoptions or [])
        ],
        created_at=asset.created_at,
    )


def _label(capability: str) -> str:
    try:
        return catalog.DEFAULTS[Capability(capability)].label
    except (ValueError, KeyError):
        return capability


def job_response(job: GenerationJob) -> GenerationJobResponse:
    user: Optional[User] = job.requested_by
    return GenerationJobResponse(
        id=job.id,
        capability=job.capability,
        capability_label=_label(job.capability),
        provider=job.provider,
        model_ref=job.model_ref,
        model_version=job.model_version,
        model_version_ran=job.model_version_ran,
        inputs=job.inputs or {},
        seed=job.seed,
        target=JobTarget(type=job.target_type, id=job.target_id),
        status=job.status,
        error=job.error,
        error_code=job.error_code,
        estimated_cost=job.estimated_cost,
        cost=job.cost,
        cost_provenance=job.cost_provenance,
        price=_price(job.price_snapshot or {}),
        shows_real_item=job.shows_real_item,
        requested_by=UserRef(id=user.id, name=user.full_name or user.email) if user else None,
        created_at=job.created_at,
        submitted_at=job.submitted_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        outputs=[asset_response(a) for a in (job.outputs or [])],
        can_cancel=job.status in ("queued", "running"),
    )


async def _reload(db, job_id: uuid.UUID, tenant_id) -> GenerationJob:
    return await db.scalar(
        select(GenerationJob)
        .where(GenerationJob.id == job_id, GenerationJob.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    )


# ----------------------------------------------------------------------- capabilities


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def list_capabilities(
    user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> CapabilitiesResponse:
    """Every capability with the model and price it uses for this tenant."""
    source, configs = GenAIService(db, tenant, user).capabilities()
    return CapabilitiesResponse(
        connected=source != "none",
        token_source=source,
        capabilities=[
            CapabilityInfo(
                capability=c.capability.value,
                label=c.label,
                output_kind=c.output_kind,
                model_ref=c.model_ref,
                model_version=c.model_version,
                pinnable=c.pinnable,
                overridden=c.overridden,
                price=_price(c.price.snapshot()),
                inputs=catalog.input_rules(c),
                max_count=c.max_count,
                max_inputs=catalog.selectable_inputs(c),
                time_limit_s=c.time_limit_s,
                shows_real_item=c.shows_real_item,
            )
            for c in configs
        ],
    )


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(
    data: GenerationJobCreate, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> EstimateResponse:
    """The estimated cost of a request and whether it fits the monthly budget."""
    try:
        result = await GenAIService(db, tenant, user).estimate(
            JobRequest(data.capability, data.inputs, data.target.type, data.target.id)
        )
    except GenAIError as exc:
        raise _http(exc) from exc
    return EstimateResponse(
        estimated_cost=result.estimated_cost,
        month_to_date=result.month_to_date,
        budget=result.budget,
        would_exceed_budget=result.would_exceed_budget,
    )


# ----------------------------------------------------------------------- jobs


@router.post("/jobs", response_model=GenerationJobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    data: GenerationJobCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> GenerationJobResponse:
    """Start a generation job; it runs in the background."""
    try:
        job = await GenAIService(db, tenant, user).create_job(
            JobRequest(data.capability, data.inputs, data.target.type, data.target.id)
        )
    except GenAIError as exc:
        raise _http(exc) from exc
    return job_response(await _reload(db, job.id, tenant.id) or job)


@router.get("/jobs", response_model=GenerationJobList)
async def list_jobs(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    target_type: Optional[str] = Query(None, pattern="^(idea|product|model|none)$"),
    target_id: Optional[uuid.UUID] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    capability: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
) -> GenerationJobList:
    """Jobs of this tenant, newest first, filtered by target, status or capability."""
    if status_filter is not None and status_filter not in JOB_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown status")
    if capability is not None and capability not in {c.value for c in Capability}:
        raise HTTPException(status_code=422, detail="Unknown capability")
    jobs, total = await GenAIService(db, tenant, user).list_jobs(
        target_type=target_type,
        target_id=target_id,
        status=status_filter,
        capability=capability,
        skip=skip,
        limit=limit,
    )
    return GenerationJobList(items=[job_response(j) for j in jobs], total=total)


@router.get("/jobs/{job_id}", response_model=GenerationJobResponse)
async def get_job(
    job_id: uuid.UUID, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> GenerationJobResponse:
    """One job: how it was made, its status, cost and outputs."""
    try:
        job = await GenAIService(db, tenant, user).get_job(job_id)
    except GenAIError as exc:
        raise _http(exc) from exc
    return job_response(job)


@router.post("/jobs/{job_id}/cancel", response_model=GenerationJobResponse)
async def cancel_job(
    job_id: uuid.UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> GenerationJobResponse:
    """Cancel a queued or running job."""
    try:
        job = await GenAIService(db, tenant, user).cancel_job(job_id)
    except GenAIError as exc:
        raise _http(exc) from exc
    return job_response(await _reload(db, job.id, tenant.id) or job)


# ----------------------------------------------------------------------- assets


@router.post("/uploads", response_model=GenAIAssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_input(
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
    file: UploadFile = File(...),
) -> GenAIAssetResponse:
    """Upload an image to use as a generation input."""
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        if len(content) > MAX_UPLOAD_BYTES:
            raise InputInvalid("Image larger than 10 MB")
        asset = await GenAIService(db, tenant, user).upload_input(
            content, file.content_type or "", file.filename
        )
    except GenAIError as exc:
        raise _http(exc) from exc
    return asset_response(asset)


@router.get("/assets/{asset_id}/file")
async def asset_file(
    asset_id: uuid.UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    variant: str = Query("full", pattern="^(full|thumb)$"),
) -> Response:
    """The bytes of a stored output or upload, for signed-in members only."""
    try:
        content, content_type = await GenAIService(db, tenant, user).open_asset(asset_id, variant)
    except GenAIError as exc:
        raise _http(exc) from exc
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600", "ETag": f'"{asset_id}-{variant}"'},
    )


@router.post(
    "/assets/{asset_id}/adopt", response_model=AdoptResponse, status_code=status.HTTP_201_CREATED
)
async def adopt_asset(
    asset_id: uuid.UUID,
    data: AdoptRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> AdoptResponse:
    """Adopt an output into an idea, a product or a model, explicitly."""
    if data.target.type == "none" or data.target.id is None:
        raise HTTPException(status_code=422, detail="An adoption needs a target")
    try:
        result = await AdoptionService(db, tenant, user).adopt(
            asset_id,
            AdoptTarget(data.target.type, data.target.id),
            confirm_not_real_item=data.confirm_not_real_item,
            alt_text=data.alt_text,
            version_note=data.version_note,
        )
    except GenAIError as exc:
        raise _http(exc) from exc
    a = result.adoption
    return AdoptResponse(
        adoption=AdoptionInfo(
            owner_type=a.owner_type,
            owner_id=a.owner_id,
            idea_entry_id=a.idea_entry_id,
            product_image_id=a.product_image_id,
            model_file_id=a.model_file_id,
            warning_confirmed=a.warning_confirmed,
            created_at=a.created_at,
        ),
        idea_entry_id=result.idea_entry_id,
        product_image_id=result.product_image_id,
        model_file_id=result.model_file_id,
        model_file_version_id=result.model_file_version_id,
    )


# ----------------------------------------------------------------------- webhook


@webhook_router.post(
    "/webhooks/replicate/{tenant_id}/{job_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def replicate_webhook(
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Provider callback; verified with the tenant's signing secret before anything is written.

    No user session exists here: the tenant comes from the path and the session
    is scoped to it before the first query (plan, Complexity Tracking).
    """
    body = await request.body()
    try:
        await handle_replicate_webhook(db, tenant_id, job_id, request.headers, body)
    except GenAIError as exc:
        await db.rollback()
        logger.info(f"Replicate webhook refused for job {job_id}: {exc.code}")
        raise HTTPException(status_code=exc.http_status, detail=exc.detail()) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["asset_response", "job_response", "router", "webhook_router"]
