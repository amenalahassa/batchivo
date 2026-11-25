"""Explicit adoption of a generation output (spec 008 FR-016 to FR-020, FR-017a).

Nothing is ever replaced on its own: adopting copies an output to its new owner
and records a ``GenAIAdoption`` row saying where it went.

- idea: a ``generation`` timeline entry in the idea's current iteration; an
  image is copied under ``ideas/{id}/``, a mesh is referenced through the job;
- product: a new product image with origin ``ai`` (the source is untouched); a
  result that does not show the real item (a concept image, a 3D draft, or any
  result made from one or from a sketch: ``GenerationJob.shows_real_item``)
  needs the operator to confirm the warning that listings must show the real item;
- model: the GLB is converted to STL and added as a new, inactive file version
  labelled "AI draft"; its size is recorded but never applied to the model.
"""

import logging
import struct
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_job import GenAIAdoption, GenAIAsset, GenerationJob
from app.models.idea import Idea, IdeaEntry
from app.models.model import Model
from app.models.model_file import ModelFileType
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.tenant import Tenant
from app.models.user import User
from app.services.genai import glb
from app.services.genai.capabilities import Capability
from app.services.genai.catalog import DEFAULTS
from app.services.genai.errors import (
    AlreadyAdopted,
    InputInvalid,
    NeedsConfirmation,
    NotFound,
    NotSucceeded,
    WrongKind,
)
from app.services.genai.storage import GenAIFileStore, GenAIStorageError
from app.services.image_storage import ImageStorageError, get_image_storage

logger = logging.getLogger(__name__)

AI_DRAFT_LABEL = "AI draft"
MESH_ENTRY_BODY = "AI 3D draft (image to 3D)"


@dataclass
class AdoptTarget:
    type: str  # idea | product | model
    id: uuid.UUID


@dataclass
class AdoptResult:
    adoption: GenAIAdoption
    idea_entry_id: Optional[uuid.UUID] = None
    product_image_id: Optional[uuid.UUID] = None
    model_file_id: Optional[uuid.UUID] = None
    model_file_version_id: Optional[uuid.UUID] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _label(capability: str) -> str:
    try:
        return DEFAULTS[Capability(capability)].label
    except (ValueError, KeyError):
        return capability


def _entry_body(job: GenerationJob, kind: str) -> str:
    if kind == "mesh":
        return MESH_ENTRY_BODY
    text = (
        (job.inputs or {}).get("prompt")
        or (job.inputs or {}).get("instruction")
        or (job.inputs or {}).get("scene")
    )
    label = _label(job.capability)
    return f"{label}: {text}"[:4000] if text else label


class AdoptionService:
    """Adopt outputs into ideas, products and models for one tenant."""

    def __init__(self, db: AsyncSession, tenant: Tenant, user: Optional[User] = None) -> None:
        self.db = db
        self.tenant = tenant
        self.user = user
        self.files = GenAIFileStore()
        self.images = get_image_storage()

    async def _asset_and_job(self, asset_id: uuid.UUID) -> tuple[GenAIAsset, GenerationJob]:
        asset = await self.db.scalar(
            select(GenAIAsset).where(
                GenAIAsset.id == asset_id, GenAIAsset.tenant_id == self.tenant.id
            )
        )
        if asset is None:
            raise NotFound("File not found")
        if asset.source != "output" or asset.job_id is None:
            raise InputInvalid("Only generation results can be adopted")
        job = await self.db.scalar(
            select(GenerationJob).where(
                GenerationJob.id == asset.job_id, GenerationJob.tenant_id == self.tenant.id
            )
        )
        if job is None or job.status != "succeeded":
            raise NotSucceeded("This generation has not succeeded")
        return asset, job

    async def _owner(self, target: AdoptTarget):
        model = {"idea": Idea, "product": Product, "model": Model}.get(target.type)
        if model is None:
            raise InputInvalid("target: unknown target type")
        owner = await self.db.scalar(
            select(model).where(model.id == target.id, model.tenant_id == self.tenant.id)
        )
        if owner is None:
            raise NotFound(f"{target.type.capitalize()} not found")
        return owner

    async def _check_not_adopted(self, asset: GenAIAsset, target: AdoptTarget) -> None:
        existing = await self.db.scalar(
            select(GenAIAdoption.id).where(
                GenAIAdoption.tenant_id == self.tenant.id,
                GenAIAdoption.asset_id == asset.id,
                GenAIAdoption.owner_type == target.type,
                GenAIAdoption.owner_id == target.id,
            )
        )
        if existing is not None:
            raise AlreadyAdopted(f"This result was already adopted into this {target.type}")

    def _adoption(self, asset: GenAIAsset, target: AdoptTarget, **fields) -> GenAIAdoption:
        adoption = GenAIAdoption(
            tenant_id=self.tenant.id,
            asset_id=asset.id,
            owner_type=target.type,
            owner_id=target.id,
            adopted_by_user_id=self.user.id if self.user else None,
            **fields,
        )
        self.db.add(adoption)
        return adoption

    async def adopt(
        self,
        asset_id: uuid.UUID,
        target: AdoptTarget,
        *,
        confirm_not_real_item: bool = False,
        alt_text: Optional[str] = None,
        version_note: Optional[str] = None,
    ) -> AdoptResult:
        """Adopt one output into one target, explicitly (FR-016)."""
        asset, job = await self._asset_and_job(asset_id)
        owner = await self._owner(target)
        await self._check_not_adopted(asset, target)
        copied: list[Optional[str]] = []
        self._model_files: list[str] = []
        try:
            if target.type == "idea":
                result = await self._into_idea(asset, job, owner, target, copied)
            elif target.type == "product":
                result = await self._into_product(
                    asset, job, owner, target, confirm_not_real_item, alt_text, copied
                )
            else:
                result = await self._into_model(asset, job, owner, target, version_note, copied)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            await self._cleanup(copied)
            await delete_model_files(self.db, self.tenant, self._model_files)
            if "uq_genai_adoptions_target" in str(exc.orig):
                raise AlreadyAdopted("This result was already adopted here") from exc
            raise
        except Exception:
            await self.db.rollback()
            await self._cleanup(copied)
            await delete_model_files(self.db, self.tenant, self._model_files)
            raise
        await self.db.refresh(result.adoption)
        logger.info(f"Adopted generation output {asset.id} into {target.type} {target.id}")
        return result

    async def _cleanup(self, urls: list[Optional[str]]) -> None:
        for url in urls:
            if not url:
                continue
            if url.startswith("/uploads/generations/"):
                await self.files.delete(url)
            else:
                try:
                    await self.images.delete_image(url)
                except ImageStorageError:  # pragma: no cover - best effort
                    pass

    async def _copy_image(
        self, asset: GenAIAsset, owner_type: str, owner_id: uuid.UUID, copied: list
    ) -> dict:
        try:
            # Full resolution: an upscale (or any large result) must not come back at the
            # 800 px a hand upload is shrunk to (FR-001, T108). The 10 MB rule still holds.
            stored = await self.images.copy_image(
                asset.storage_url, owner_type, str(owner_id), display_size=None
            )
        except ImageStorageError as exc:
            raise InputInvalid(f"The result could not be copied: {exc}") from exc
        copied.extend([stored["image_url"], stored.get("thumbnail_url")])
        return stored

    # ------------------------------------------------------------------ idea

    async def _into_idea(
        self, asset: GenAIAsset, job: GenerationJob, idea: Idea, target: AdoptTarget, copied
    ) -> AdoptResult:
        fields: dict = {}
        if asset.kind == "image":
            stored = await self._copy_image(asset, "ideas", idea.id, copied)
            fields = dict(
                image_url=stored["image_url"],
                thumbnail_url=stored["thumbnail_url"],
                content_type=stored["content_type"],
                file_size=stored["file_size"],
                original_filename=asset.original_filename,
            )
        entry = IdeaEntry(
            id=uuid.uuid4(),
            tenant_id=self.tenant.id,
            idea_id=idea.id,
            kind="generation",
            iteration=idea.current_iteration,
            body=_entry_body(job, asset.kind),
            generation_job_id=job.id,
            author_user_id=self.user.id if self.user else None,
            created_at=_now(),
            **fields,
        )
        self.db.add(entry)
        idea.updated_at = _now()
        await self.db.flush()
        adoption = self._adoption(asset, target, idea_entry_id=entry.id)
        return AdoptResult(adoption, idea_entry_id=entry.id)

    # ------------------------------------------------------------------ product

    async def _into_product(
        self,
        asset: GenAIAsset,
        job: GenerationJob,
        product: Product,
        target: AdoptTarget,
        confirmed: bool,
        alt_text: Optional[str],
        copied,
    ) -> AdoptResult:
        if asset.kind != "image":
            raise WrongKind("Only images can become product images")
        warn = not job.shows_real_item
        if warn and not confirmed:
            raise NeedsConfirmation(
                "Listings must show the real item. This image is not a photo or a render of the "
                "product's real geometry; confirm to add it anyway."
            )
        stored = await self._copy_image(asset, "products", product.id, copied)
        last = await self.db.scalar(
            select(func.max(ProductImage.display_order)).where(
                ProductImage.product_id == product.id, ProductImage.tenant_id == self.tenant.id
            )
        )
        image = ProductImage(
            tenant_id=self.tenant.id,
            product_id=product.id,
            image_url=stored["image_url"],
            thumbnail_url=stored["thumbnail_url"],
            alt_text=(alt_text or product.name or "")[:255],
            display_order=(last + 1) if last is not None else 0,
            is_primary=False,
            original_filename=asset.original_filename,
            file_size=stored["file_size"],
            content_type=stored["content_type"],
            origin="ai",
        )
        self.db.add(image)
        await self.db.flush()
        adoption = self._adoption(
            asset, target, product_image_id=image.id, warning_confirmed=bool(warn and confirmed)
        )
        return AdoptResult(adoption, product_image_id=image.id)

    # ------------------------------------------------------------------ model

    async def add_mesh_to_model(
        self,
        asset: GenAIAsset,
        job: GenerationJob,
        model: Model,
        note: Optional[str],
        cleanup: list,
    ) -> tuple[uuid.UUID, uuid.UUID]:
        """Convert the GLB and add it as an inactive "AI draft" version; no commit."""
        from app.services.model_file_service import ModelFileService
        from app.services.model_file_version_service import ModelFileVersionService

        if asset.kind != "mesh":
            raise WrongKind("Only 3D results can become model files")
        try:
            content = await self.files.get(asset.storage_url)
        except GenAIStorageError as exc:
            raise NotFound("The 3D result is no longer stored") from exc
        try:
            stl = glb.to_stl(content)
        except (ValueError, IndexError, KeyError, struct.error) as exc:
            raise InputInvalid(f"The 3D result could not be converted: {exc}") from exc
        versions = ModelFileVersionService(self.db, self.tenant, self.user)
        version_ref = job.model_version_ran or job.model_version
        version = await versions.create_version(
            model,
            AI_DRAFT_LABEL,
            note
            or f"Generated by job {job.id} ({job.model_ref}:{version_ref}). No real-world scale.",
            activate_if_first=False,
        )
        from app.services.model_file_service import ModelFileStorageError

        try:
            model_file = await ModelFileService(
                db=self.db, tenant=self.tenant, user=self.user
            ).upload_file(
                model_id=model.id,
                file_content=stl,
                content_type="model/stl",
                original_filename=f"ai-draft-{str(job.id)[:8]}.stl",
                file_type=ModelFileType.SOURCE_STL,
                version_id=version.id,
                notes="AI draft generated from an image; not to scale.",
                commit=False,
                offer_measurement=False,
            )
        except ModelFileStorageError as exc:
            raise InputInvalid(f"The 3D draft could not be stored: {exc}") from exc
        cleanup.append(model_file.file_url)
        return model_file.id, version.id

    async def _into_model(
        self,
        asset: GenAIAsset,
        job: GenerationJob,
        model: Model,
        target: AdoptTarget,
        note: Optional[str],
        copied,
    ) -> AdoptResult:
        file_id, version_id = await self.add_mesh_to_model(
            asset, job, model, note, self._model_files
        )
        adoption = self._adoption(asset, target, model_file_id=file_id)
        return AdoptResult(adoption, model_file_id=file_id, model_file_version_id=version_id)


async def delete_model_files(db: AsyncSession, tenant: Tenant, urls: list) -> None:
    from app.services.model_file_service import ModelFileService

    service = ModelFileService(db=db, tenant=tenant)
    for url in urls:
        if url:
            await service.delete_stored_file(url)


async def carry_idea_drafts(
    db: AsyncSession,
    tenant: Tenant,
    user: Optional[User],
    idea: Idea,
    model: Model,
    cleanup: list,
) -> list[str]:
    """Add each 3D draft adopted on the idea to its new model (FR-017a, Q4).

    Runs inside the conversion's savepoint and never commits. Stored model-file
    URLs are appended to ``cleanup`` so the caller can delete them if the
    conversion rolls back. A draft that cannot be carried becomes a warning.
    """
    rows = (
        await db.execute(
            select(GenAIAsset, GenerationJob)
            .join(GenAIAdoption, GenAIAdoption.asset_id == GenAIAsset.id)
            .join(IdeaEntry, IdeaEntry.id == GenAIAdoption.idea_entry_id)
            .join(GenerationJob, GenerationJob.id == GenAIAsset.job_id)
            .where(
                GenAIAdoption.tenant_id == tenant.id,
                GenAIAdoption.owner_type == "idea",
                GenAIAdoption.owner_id == idea.id,
                GenAIAsset.kind == "mesh",
                IdeaEntry.archived_at.is_(None),
            )
            .order_by(IdeaEntry.created_at, IdeaEntry.id)
        )
    ).all()
    service = AdoptionService(db, tenant, user)
    warnings: list[str] = []
    for asset, job in rows:
        stored: list[str] = []
        try:
            async with db.begin_nested():
                file_id, _ = await service.add_mesh_to_model(asset, job, model, None, stored)
                db.add(
                    GenAIAdoption(
                        tenant_id=tenant.id,
                        asset_id=asset.id,
                        owner_type="model",
                        owner_id=model.id,
                        model_file_id=file_id,
                        adopted_by_user_id=user.id if user else None,
                    )
                )
                await db.flush()
            cleanup.extend(stored)
        except (InputInvalid, NotFound, WrongKind) as exc:
            await delete_model_files(db, tenant, stored)
            warnings.append(
                f"3D draft from job {str(job.id)[:8]} could not be added: {exc.message}"
            )
            logger.warning(f"3D draft {asset.id} not carried to model {model.id}: {exc.message}")
    return warnings


__all__ = [
    "AI_DRAFT_LABEL",
    "AdoptResult",
    "AdoptTarget",
    "AdoptionService",
    "carry_idea_drafts",
    "delete_model_files",
]
