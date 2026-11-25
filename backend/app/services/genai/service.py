"""GenAIService: validate, budget, record and dispatch generation jobs (spec 008).

Callable without HTTP (FR-015): it takes a session, a tenant and a user, and
raises ``GenAIError`` subclasses, never ``HTTPException``. The routers, scripts,
Preflight (009) and anything else in-process use the same rules.
"""

import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.generation_job import (
    ACTIVE_STATUSES,
    GenAIAdoption,
    GenAIAsset,
    GenerationJob,
)
from app.models.idea import IMAGE_KINDS, Idea, IdeaEntry
from app.models.model import Model
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.tenant import Tenant
from app.models.user import User
from app.services.genai import catalog, credentials
from app.services.genai.capabilities import (
    NOT_REAL_ITEM,
    AssetRef,
    Capability,
    output_count,
    parse_capability,
    validate_inputs,
)
from app.services.genai.costs import GenAICostService
from app.services.genai.errors import (
    BudgetExceeded,
    ConcurrencyLimit,
    InputInvalid,
    NotCancellable,
    NotConnected,
    NotFound,
    QueueUnavailable,
)
from app.services.genai.storage import GenAIFileStore, GenAIStorageError
from app.services.image_storage import ImageStorageError, get_image_storage

logger = logging.getLogger(__name__)

TARGET_MODELS = {"idea": Idea, "product": Product, "model": Model}


@dataclass
class JobRequest:
    """A caller's request: capability, raw inputs and an optional target."""

    capability: str
    inputs: dict
    target_type: str = "none"
    target_id: Optional[uuid.UUID] = None


@dataclass
class Estimate:
    estimated_cost: Decimal
    month_to_date: Decimal
    budget: Optional[Decimal]
    would_exceed_budget: bool
    config: catalog.CapabilityConfig


def _now() -> datetime:
    return datetime.now(timezone.utc)


def uploads_owner(tenant_id) -> str:
    """Storage owner for a tenant's input uploads (not tied to one job)."""
    return f"uploads-{tenant_id}"


def budget_of(tenant: Tenant) -> Optional[Decimal]:
    """The tenant's monthly budget in USD, or None for no cap."""
    raw = credentials.replicate_config(tenant).get("monthly_budget_usd")
    if raw in (None, ""):
        return None
    return Decimal(str(raw))


#: A Batchivo-stored image: ``/uploads/{owner}/{owner id}/{file}``, one level each, nothing
#: that walks out of the uploads root (FR-032).
_STORED_IMAGE = re.compile(r"/uploads/(products|ideas|generations)/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+")


def _is_stored_image(url: Optional[str]) -> bool:
    return bool(url) and ".." not in url and bool(_STORED_IMAGE.fullmatch(url))


class GenAIService:
    """Business rules of generation jobs for one tenant and user."""

    def __init__(self, db: AsyncSession, tenant: Tenant, user: Optional[User] = None) -> None:
        self.db = db
        self.tenant = tenant
        self.user = user
        self.costs = GenAICostService()
        self.files = GenAIFileStore()

    # ------------------------------------------------------------------ capabilities

    def capabilities(self) -> tuple[str, list[catalog.CapabilityConfig]]:
        """The token source and every capability as it resolves for this tenant."""
        return credentials.resolve(self.tenant).source, catalog.capability_list(
            self.tenant.settings
        )

    # ------------------------------------------------------------------ reading

    async def get_job(self, job_id: uuid.UUID) -> GenerationJob:
        job = await self.db.scalar(
            select(GenerationJob).where(
                GenerationJob.id == job_id, GenerationJob.tenant_id == self.tenant.id
            )
        )
        if job is None:
            raise NotFound("Generation job not found")
        return job

    async def list_jobs(
        self,
        *,
        target_type: Optional[str] = None,
        target_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        capability: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[GenerationJob], int]:
        filters = [GenerationJob.tenant_id == self.tenant.id]
        if target_type:
            filters.append(GenerationJob.target_type == target_type)
        if target_id:
            filters.append(GenerationJob.target_id == target_id)
        if status:
            filters.append(GenerationJob.status == status)
        if capability:
            filters.append(GenerationJob.capability == capability)
        total = await self.db.scalar(select(func.count(GenerationJob.id)).where(*filters))
        rows = await self.db.scalars(
            select(GenerationJob)
            .where(*filters)
            .order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(rows), int(total or 0)

    async def get_asset(self, asset_id: uuid.UUID) -> GenAIAsset:
        asset = await self.db.scalar(
            select(GenAIAsset).where(
                GenAIAsset.id == asset_id, GenAIAsset.tenant_id == self.tenant.id
            )
        )
        if asset is None:
            raise NotFound("File not found")
        return asset

    async def open_asset(self, asset_id: uuid.UUID, variant: str = "full") -> tuple[bytes, str]:
        asset = await self.get_asset(asset_id)
        url = (
            asset.thumbnail_url if variant == "thumb" and asset.thumbnail_url else asset.storage_url
        )
        try:
            content = await self.files.get(url)
        except GenAIStorageError as exc:
            raise NotFound("File not found") from exc
        content_type = asset.content_type
        if variant == "thumb" and asset.thumbnail_url:
            content_type = asset.content_type
        return content, content_type

    # ------------------------------------------------------------------ inputs

    async def upload_input(
        self, content: bytes, content_type: str, filename: Optional[str]
    ) -> GenAIAsset:
        """Store an operator's image to use as an input."""
        try:
            stored = await self.files.save_image(
                content, content_type, uploads_owner(self.tenant.id)
            )
        except GenAIStorageError as exc:
            raise InputInvalid(exc.message) from exc
        asset = GenAIAsset(
            tenant_id=self.tenant.id,
            source="upload",
            kind="image",
            storage_url=stored["url"],
            thumbnail_url=stored["thumbnail_url"],
            content_type=stored["content_type"],
            file_size=stored["file_size"],
            width=stored["width"],
            height=stored["height"],
            original_filename=(filename or "")[:255] or None,
            ai_generated=False,
            created_by_user_id=self.user.id if self.user else None,
        )
        self.db.add(asset)
        await self.db.commit()
        await self.db.refresh(asset)
        return asset

    async def _import_image(
        self, url: Optional[str], filename: Optional[str], shows_real_item: bool = True
    ) -> GenAIAsset:
        """Copy a stored Batchivo image into an input asset of this tenant.

        ``shows_real_item`` is what the source says of the picture, kept on the asset so
        that reusing it by id later keeps the answer (FR-030).
        """
        if not _is_stored_image(url):
            raise InputInvalid("This image is not stored in Batchivo")
        try:
            content, content_type = await get_image_storage().get_image(url)
        except ImageStorageError as exc:
            raise NotFound("Input image not found") from exc
        try:
            stored = await self.files.save_image(
                content, content_type, uploads_owner(self.tenant.id)
            )
        except GenAIStorageError as exc:
            raise InputInvalid(exc.message) from exc
        asset = GenAIAsset(
            tenant_id=self.tenant.id,
            source="upload",
            kind="image",
            storage_url=stored["url"],
            thumbnail_url=stored["thumbnail_url"],
            content_type=stored["content_type"],
            file_size=stored["file_size"],
            width=stored["width"],
            height=stored["height"],
            original_filename=(filename or url.rsplit("/", 1)[-1])[:255],
            ai_generated=False,
            shows_real_item=shows_real_item,
            created_by_user_id=self.user.id if self.user else None,
        )
        self.db.add(asset)
        await self.db.flush()
        return asset

    async def resolve_asset(self, ref: AssetRef) -> GenAIAsset:
        """The input asset a reference names, within this tenant only (FR-032)."""
        asset, _ = await self.resolve_input(ref)
        return asset

    async def resolve_input(self, ref: AssetRef) -> tuple[GenAIAsset, bool]:
        """The input asset a reference names, and whether it shows the real item (FR-030).

        Importing an idea entry or a product image makes a plain upload, so whether the
        picture shows the real item is decided here, from where it came from. When its
        origin cannot be traced, the answer is the safe one: it does not.
        """
        tid = self.tenant.id
        if ref.type == "asset":
            asset = await self.get_asset(ref.id)
            if asset.kind != "image":
                raise InputInvalid("Only images can be used as inputs")
            return asset, await self._asset_shows_real_item(asset)
        if ref.type == "idea_entry":
            entry = await self.db.scalar(
                select(IdeaEntry).where(IdeaEntry.id == ref.id, IdeaEntry.tenant_id == tid)
            )
            if entry is None or not entry.image_url:
                raise NotFound("Input image not found")
            if entry.kind not in IMAGE_KINDS and entry.kind != "generation":
                raise InputInvalid("This idea entry is not an image")
            real = await self._entry_shows_real_item(entry)
            asset = await self._import_image(entry.image_url, entry.original_filename, real)
            return asset, real
        if ref.type == "product_image":
            image = await self.db.scalar(
                select(ProductImage).where(ProductImage.id == ref.id, ProductImage.tenant_id == tid)
            )
            if image is None:
                raise NotFound("Input image not found")
            real = await self._product_image_shows_real_item(image)
            asset = await self._import_image(image.image_url, image.original_filename, real)
            return asset, real
        model = await self.db.scalar(
            select(Model).where(Model.id == ref.id, Model.tenant_id == tid)
        )
        if model is None or not model.image_url:
            raise NotFound("Input image not found")
        # A model's image is free text a member can set: only the model's own stored file
        # (where Batchivo saves it) may be read, never another owner's (FR-032, tenancy).
        if not model.image_url.startswith(f"/uploads/products/{model.id}/"):
            raise InputInvalid("This model's image is not stored in Batchivo; upload it instead")
        return await self._import_image(model.image_url, None), True

    async def _job_shows_real_item(self, job_id: Optional[uuid.UUID]) -> bool:
        """Whether a job's results show the real item; an unknown job does not."""
        if job_id is None:
            return False
        real = await self.db.scalar(
            select(GenerationJob.shows_real_item).where(
                GenerationJob.id == job_id, GenerationJob.tenant_id == self.tenant.id
            )
        )
        return bool(real)

    async def _asset_shows_real_item(self, asset: GenAIAsset) -> bool:
        if asset.source == "output":
            return await self._job_shows_real_item(asset.job_id)
        # An upload carries what its source said when it was imported (a sketch, a
        # generation entry or an AI product image that does not show the real item).
        return asset.shows_real_item

    async def _entry_shows_real_item(self, entry: IdeaEntry) -> bool:
        if entry.kind == "sketch":
            return False
        if entry.kind == "generation":
            return await self._job_shows_real_item(entry.generation_job_id)
        return True

    async def _product_image_shows_real_item(self, image: ProductImage) -> bool:
        if image.origin in ("photo", "render"):
            return True
        job_id = await self.db.scalar(
            select(GenAIAsset.job_id)
            .join(GenAIAdoption, GenAIAdoption.asset_id == GenAIAsset.id)
            .where(
                GenAIAdoption.tenant_id == self.tenant.id,
                GenAIAdoption.product_image_id == image.id,
            )
            .limit(1)
        )
        return await self._job_shows_real_item(job_id)

    async def check_target(self, target_type: str, target_id: Optional[uuid.UUID]) -> None:
        if target_type == "none":
            if target_id is not None:
                raise InputInvalid("target: a target id needs a target type")
            return
        if target_type not in TARGET_MODELS or target_id is None:
            raise InputInvalid("target: unknown target")
        model = TARGET_MODELS[target_type]
        found = await self.db.scalar(
            select(model.id).where(model.id == target_id, model.tenant_id == self.tenant.id)
        )
        if found is None:
            raise NotFound(f"{target_type.capitalize()} not found")

    # ------------------------------------------------------------------ estimate & create

    async def estimate(self, request: JobRequest) -> Estimate:
        capability = parse_capability(request.capability)
        refs = (request.inputs or {}).get("input_assets") or []
        config = catalog.resolve(capability, self.tenant.settings, has_references=bool(refs))
        inputs = validate_inputs(capability, request.inputs, config.max_count)
        estimated = self.costs.estimate(config, output_count(inputs))
        mtd, _ = await self.costs.month_to_date(self.db, self.tenant.id)
        budget = budget_of(self.tenant)
        exceed = budget is not None and mtd + estimated > budget
        return Estimate(estimated, mtd, budget, exceed, config)

    async def _lock_tenant(self) -> None:
        """Serialise job creation per tenant so budget and concurrency checks hold (R5)."""
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            await self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 8))"),
                {"k": f"genai:{self.tenant.id}"},
            )

    async def create_job(self, request: JobRequest) -> GenerationJob:
        """Validate, check budget and concurrency, record the job, hand it to a worker."""
        resolved = credentials.resolve(self.tenant)
        if not resolved.token:
            raise NotConnected("Replicate is not connected. Add a token in Settings → AI.")
        capability = parse_capability(request.capability)
        raw_refs = (request.inputs or {}).get("input_assets") or []
        config = catalog.resolve(capability, self.tenant.settings, has_references=bool(raw_refs))
        inputs = validate_inputs(capability, request.inputs, config.max_count)
        if capability is Capability.CONCEPT_IMAGE and len(inputs.input_assets) > config.max_inputs:
            raise InputInvalid(f"input_assets: at most {config.max_inputs} reference images")
        await self.check_target(request.target_type, request.target_id)
        seed = inputs.seed if inputs.seed is not None else secrets.randbelow(2**31)
        count = output_count(inputs)
        estimated = self.costs.estimate(config, count)

        await self._lock_tenant()
        active = await self.db.scalar(
            select(func.count(GenerationJob.id)).where(
                GenerationJob.tenant_id == self.tenant.id,
                GenerationJob.status.in_(ACTIVE_STATUSES),
            )
        )
        limit = get_settings().genai_max_concurrent_jobs
        if int(active or 0) >= limit:
            raise ConcurrencyLimit(
                f"{limit} generation{'s are' if limit > 1 else ' is'} already running. "
                "Try again when one finishes."
            )
        budget = budget_of(self.tenant)
        if budget is not None:
            mtd, _ = await self.costs.month_to_date(self.db, self.tenant.id)
            if mtd + estimated > budget:
                raise BudgetExceeded(
                    f"This generation (about ${estimated}) would take this month's AI spend "
                    f"(${mtd}) over the monthly budget of ${budget}."
                )

        assets: list[GenAIAsset] = []
        shows_real_item = capability not in NOT_REAL_ITEM
        try:
            for ref in inputs.input_assets:
                asset, real = await self.resolve_input(ref)
                assets.append(asset)
                shows_real_item = shows_real_item and real
        except Exception:
            for asset in assets:
                if asset.source == "upload" and asset.id not in {r.id for r in inputs.input_assets}:
                    await self.files.delete(asset.storage_url)
                    await self.files.delete(asset.thumbnail_url)
            raise

        stored_inputs = inputs.model_dump(mode="json", exclude={"input_assets", "seed"})
        stored_inputs["input_assets"] = [str(a.id) for a in assets]
        stored_inputs["params"] = dict(config.default_params)
        job = GenerationJob(
            tenant_id=self.tenant.id,
            capability=capability.value,
            provider=config.provider,
            model_ref=config.model_ref,
            model_version=config.model_version,
            inputs=stored_inputs,
            seed=seed,
            target_type=request.target_type,
            target_id=request.target_id,
            status="queued",
            estimated_cost=estimated,
            price_snapshot=config.price.snapshot(),
            shows_real_item=shows_real_item,
            requested_by_user_id=self.user.id if self.user else None,
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)
        logger.info(
            f"Queued generation job {job.id} ({capability.value}) for tenant {self.tenant.id}"
        )

        from app.tasks.genai import dispatch_submit

        try:
            dispatch_submit(job.id, self.tenant.id)
        except Exception as exc:  # noqa: BLE001 - any broker failure is the same answer
            logger.error(f"Could not queue generation job {job.id}: {type(exc).__name__}")
            job.status = "failed"
            job.error = "The job could not be queued; try again later."
            job.error_code = "queue_unavailable"
            job.cost, job.cost_provenance = self.costs.final(job, None, 0)
            job.completed_at = _now()
            await self.db.commit()
            raise QueueUnavailable(job.error) from exc
        return job

    # ------------------------------------------------------------------ cancel

    async def cancel_job(self, job_id: uuid.UUID) -> GenerationJob:
        """Cancel a queued or running job (FR-012)."""
        from app.services.genai.runner import cancel_job

        job = await self.get_job(job_id)
        if not job.is_active:
            raise NotCancellable("This generation has already finished")
        return await cancel_job(self.db, self.tenant, job, reason="Canceled by the operator")


__all__ = ["Estimate", "GenAIService", "JobRequest", "budget_of", "uploads_owner"]
