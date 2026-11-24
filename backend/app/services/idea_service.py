"""Product ideas: capture, timeline, conversion and import (spec 007).

Every business rule of the Ideas module lives here; ``api/v1/ideas.py`` stays
thin. Queries filter on ``tenant_id`` on top of row-level security, so an idea
of another shop is simply "not found".
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from fastapi import HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import func, or_, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role
from app.config import get_settings
from app.models.idea import IMAGE_KINDS, SCORE_FIELDS, Idea, IdeaEntry
from app.models.model import Model
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.idea import (
    ConvertRequest,
    ConvertResponse,
    IdeaCreate,
    IdeaDetail,
    IdeaEntryCreate,
    IdeaEntryList,
    IdeaEntryResponse,
    IdeaEntryUpdate,
    IdeaLink,
    IdeaListResponse,
    IdeaScores,
    IdeaSummary,
    IdeaUpdate,
    ImageUploadResult,
    ImportCreated,
    ImportItem,
    ImportRefused,
    ImportResult,
    ImportSkipped,
    RefusedFile,
    UserRef,
)
from app.schemas.model import ModelCreate
from app.schemas.product import ProductCreate, ProductModelCreate
from app.services.image_storage import ImageStorage, ImageStorageError, get_image_storage
from app.services.model_creation import create_model
from app.services.product_creation import create_product
from app.services.sku_generator import EntityType, SKUGeneratorService

logger = logging.getLogger(__name__)

MAX_FILES_PER_UPLOAD = 10
SCORE_NAMES = {
    "score_frequency": "frequency",
    "score_frustration": "frustration",
    "score_printability": "printability",
    "score_gap": "gap",
    "score_willingness_to_pay": "willingness_to_pay",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user_ref(user: Optional[User]) -> Optional[UserRef]:
    if user is None:
        return None
    return UserRef(id=user.id, name=user.full_name or user.email)


def _http(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


async def source_idea_fields(
    db: AsyncSession, tenant_id: uuid.UUID, idea_id: Optional[uuid.UUID]
) -> dict:
    """``source_idea_*`` response fields of a model or product (spec 007, FR-027)."""
    if idea_id is None:
        return {"source_idea_id": None, "source_idea_title": None, "source_idea_archived": None}
    row = (
        await db.execute(
            select(Idea.title, Idea.archived_at).where(
                Idea.id == idea_id, Idea.tenant_id == tenant_id
            )
        )
    ).first()
    if row is None:
        return {"source_idea_id": None, "source_idea_title": None, "source_idea_archived": None}
    return {
        "source_idea_id": idea_id,
        "source_idea_title": row.title,
        "source_idea_archived": row.archived_at is not None,
    }


async def source_idea_fields_many(
    db: AsyncSession, tenant_id: uuid.UUID, idea_ids: set[Optional[uuid.UUID]]
) -> dict[uuid.UUID, dict]:
    """``source_idea_*`` fields for a page of records, in one query (spec 007, FR-027).

    Keyed by idea id; a record whose idea is missing or of another shop gets the
    empty fields from ``source_idea_fields_for``.
    """
    wanted = {i for i in idea_ids if i is not None}
    if not wanted:
        return {}
    rows = await db.execute(
        select(Idea.id, Idea.title, Idea.archived_at).where(
            Idea.id.in_(wanted), Idea.tenant_id == tenant_id
        )
    )
    return {
        row.id: {
            "source_idea_id": row.id,
            "source_idea_title": row.title,
            "source_idea_archived": row.archived_at is not None,
        }
        for row in rows
    }


def source_idea_fields_for(found: dict[uuid.UUID, dict], idea_id: Optional[uuid.UUID]) -> dict:
    """One record's ``source_idea_*`` fields out of ``source_idea_fields_many``."""
    empty = {"source_idea_id": None, "source_idea_title": None, "source_idea_archived": None}
    return found.get(idea_id, empty) if idea_id is not None else empty


class IdeaService:
    """
    Ideas of one tenant and their timelines.

    Instantiated per request with the tenant-scoped session, the tenant and the
    acting user.
    """

    def __init__(
        self,
        db: AsyncSession,
        tenant: Tenant,
        user: Optional[User] = None,
        storage: Optional[ImageStorage] = None,
    ):
        self.db = db
        self.tenant = tenant
        self.user = user
        self.storage = storage or get_image_storage()
        self.prefix = get_settings().api_v1_prefix

    # ============================================
    # Loading and response building
    # ============================================

    async def get_idea(self, idea_id: uuid.UUID) -> Idea:
        """The tenant's idea, archived or not; 404 otherwise."""
        idea = await self.db.scalar(
            select(Idea)
            .where(Idea.id == idea_id, Idea.tenant_id == self.tenant.id)
            .execution_options(populate_existing=True)
        )
        if idea is None:
            raise _http(status.HTTP_404_NOT_FOUND, "Idea not found")
        return idea

    async def get_entry(self, idea: Idea, entry_id: uuid.UUID) -> IdeaEntry:
        """An entry of this idea; 404 otherwise."""
        entry = await self.db.scalar(
            select(IdeaEntry)
            .where(
                IdeaEntry.id == entry_id,
                IdeaEntry.idea_id == idea.id,
                IdeaEntry.tenant_id == self.tenant.id,
            )
            .execution_options(populate_existing=True)
        )
        if entry is None:
            raise _http(status.HTTP_404_NOT_FOUND, "Entry not found")
        return entry

    def image_path(self, idea_id: uuid.UUID, entry_id: uuid.UUID, variant: str) -> str:
        """The authenticated API path an idea image is served from (research R2)."""
        return f"{self.prefix}/ideas/{idea_id}/entries/{entry_id}/image?variant={variant}"

    async def _links(
        self, ideas: Sequence[Idea]
    ) -> tuple[dict[uuid.UUID, Model], dict[uuid.UUID, Product]]:
        model_ids = {i.converted_model_id for i in ideas if i.converted_model_id}
        product_ids = {i.converted_product_id for i in ideas if i.converted_product_id}
        models: dict[uuid.UUID, Model] = {}
        products: dict[uuid.UUID, Product] = {}
        if model_ids:
            rows = await self.db.scalars(
                select(Model).where(Model.id.in_(model_ids), Model.tenant_id == self.tenant.id)
            )
            models = {m.id: m for m in rows}
        if product_ids:
            rows = await self.db.scalars(
                select(Product).where(
                    Product.id.in_(product_ids), Product.tenant_id == self.tenant.id
                )
            )
            products = {p.id: p for p in rows}
        return models, products

    @staticmethod
    def _link(target_id, record, was_converted: bool) -> IdeaLink:
        if target_id and record is not None:
            return IdeaLink(id=record.id, name=record.name, sku=record.sku, state="linked")
        if was_converted:
            # The model or product was deleted after the conversion (FR-030).
            return IdeaLink(state="gone")
        return IdeaLink(state="none")

    def _summary_fields(self, idea: Idea, models: dict, products: dict) -> dict:
        return {
            "id": idea.id,
            "title": idea.title,
            "status": idea.status,
            "source": idea.source,
            "source_url": idea.source_url,
            "tags": list(idea.tags or []),
            "scores": IdeaScores(**{SCORE_NAMES[f]: getattr(idea, f) for f in SCORE_FIELDS}),
            "report_score": idea.report_score,
            "score": idea.score,
            "score_source": idea.score_source,
            "cover_thumbnail_path": (
                self.image_path(idea.id, idea.cover_entry_id, "thumb")
                if idea.cover_entry_id
                else None
            ),
            "current_iteration": idea.current_iteration,
            "archived": idea.archived_at is not None,
            "model": self._link(
                idea.converted_model_id,
                models.get(idea.converted_model_id),
                idea.was_converted_to_model,
            ),
            "product": self._link(
                idea.converted_product_id,
                products.get(idea.converted_product_id),
                idea.was_converted_to_product,
            ),
            "created_at": idea.created_at,
            "updated_at": idea.updated_at,
        }

    async def to_detail(self, idea: Idea) -> IdeaDetail:
        """Full response for one idea."""
        models, products = await self._links([idea])
        return IdeaDetail(
            **self._summary_fields(idea, models, products),
            summary=idea.summary,
            cover_entry_id=idea.cover_entry_id,
            cover_image_path=(
                self.image_path(idea.id, idea.cover_entry_id, "full")
                if idea.cover_entry_id
                else None
            ),
            created_by=_user_ref(idea.created_by),
        )

    def to_entry(self, entry: IdeaEntry) -> IdeaEntryResponse:
        """Response for one timeline entry; storage keys never leave the server."""
        has_image = entry.image_url is not None
        return IdeaEntryResponse(
            id=entry.id,
            idea_id=entry.idea_id,
            kind=entry.kind,
            iteration=entry.iteration,
            body=entry.body,
            link_url=entry.link_url,
            pinned=entry.pinned,
            archived=entry.archived_at is not None,
            image_path=self.image_path(entry.idea_id, entry.id, "full") if has_image else None,
            thumbnail_path=(
                self.image_path(entry.idea_id, entry.id, "thumb")
                if has_image and entry.thumbnail_url
                else None
            ),
            content_type=entry.content_type,
            original_filename=entry.original_filename,
            file_size=entry.file_size,
            generation_job_id=entry.generation_job_id,
            author=_user_ref(entry.author),
            created_at=entry.created_at,
            edited_at=entry.edited_at,
        )

    def _touch(self, idea: Idea) -> None:
        idea.updated_at = _now()

    async def _commit(self) -> None:
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if "uq_ideas_report_source" in str(exc.orig):
                raise _http(
                    status.HTTP_409_CONFLICT,
                    "An idea was already imported from this report link",
                ) from exc
            raise

    # ============================================
    # Ideas (US1)
    # ============================================

    async def list_ideas(
        self,
        *,
        statuses: Optional[Iterable[str]] = None,
        tags: Optional[Iterable[str]] = None,
        source: Optional[str] = None,
        search: Optional[str] = None,
        archived: str = "false",
        sort: str = "updated",
        skip: int = 0,
        limit: int = 20,
    ) -> IdeaListResponse:
        """A page of the tenant's ideas, filtered and sorted in the database."""
        query = select(Idea).where(Idea.tenant_id == self.tenant.id)
        if archived == "false":
            query = query.where(Idea.archived_at.is_(None))
        elif archived == "true":
            query = query.where(Idea.archived_at.isnot(None))
        status_list = [s for s in (statuses or []) if s]
        if status_list:
            query = query.where(Idea.status.in_(status_list))
        for tag in tags or []:
            tag = " ".join(tag.split()).lower()
            if tag:
                query = query.where(type_coerce(Idea.tags, JSONB).contains([tag]))
        if source:
            query = query.where(Idea.source == source)
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            query = query.where(or_(Idea.title.ilike(pattern), Idea.summary.ilike(pattern)))

        total = await self.db.scalar(select(func.count()).select_from(query.subquery()))
        if sort == "score":
            order = (Idea.score.desc().nullslast(), Idea.updated_at.desc())
        elif sort == "created":
            order = (Idea.created_at.desc(), Idea.id)
        else:
            order = (Idea.updated_at.desc(), Idea.id)
        rows = list(await self.db.scalars(query.order_by(*order).offset(skip).limit(limit)))
        models, products = await self._links(rows)
        return IdeaListResponse(
            items=[IdeaSummary(**self._summary_fields(i, models, products)) for i in rows],
            total=total or 0,
            skip=skip,
            limit=limit,
        )

    async def list_tags(self) -> list[str]:
        """Distinct tags of the tenant's ideas, for the filter."""
        element = func.jsonb_array_elements_text(type_coerce(Idea.tags, JSONB))
        rows = await self.db.scalars(
            select(element)
            .where(Idea.tenant_id == self.tenant.id, Idea.archived_at.is_(None))
            .distinct()
        )
        return sorted(rows)

    def _apply_scores(self, idea: Idea, scores: IdeaScores) -> None:
        for field, name in SCORE_NAMES.items():
            setattr(idea, field, getattr(scores, name))

    def _new_idea(self, data: IdeaCreate) -> Idea:
        idea = Idea(
            id=uuid.uuid4(),
            tenant_id=self.tenant.id,
            title=data.title,
            summary=data.summary,
            status=data.status,
            source=data.source,
            source_url=data.source_url,
            tags=list(data.tags),
            report_score=data.report_score,
            current_iteration=1,
            created_by_user_id=self.user.id if self.user else None,
        )
        self._apply_scores(idea, data.scores)
        return idea

    async def create(self, data: IdeaCreate) -> IdeaDetail:
        """Create an idea (Inbox and manual by default)."""
        idea = self._new_idea(data)
        self.db.add(idea)
        await self._commit()
        logger.info(f"Created idea {idea.id} for tenant {self.tenant.id}")
        return await self.to_detail(await self.get_idea(idea.id))

    async def update(self, idea_id: uuid.UUID, data: IdeaUpdate) -> IdeaDetail:
        """Partial update; ``converted`` is never set here (FR-007)."""
        idea = await self.get_idea(idea_id)
        changes = data.model_dump(exclude_unset=True)
        for field in ("title", "status", "source", "tags"):
            if changes.get(field) is not None:
                setattr(idea, field, changes[field])
        for field in ("summary", "source_url"):  # these two can be cleared
            if field in changes:
                setattr(idea, field, changes[field])
        if "scores" in changes and data.scores is not None:
            self._apply_scores(idea, data.scores)
        if "archived" in changes and data.archived is not None:
            idea.archived_at = _now() if data.archived else None
        if "cover_entry_id" in changes:
            await self._set_cover(idea, data.cover_entry_id)
        self._touch(idea)
        await self._commit()
        return await self.to_detail(await self.get_idea(idea_id))

    async def archive(self, idea_id: uuid.UUID) -> IdeaDetail:
        """Archive an idea; it stays recoverable (FR-006)."""
        idea = await self.get_idea(idea_id)
        if idea.archived_at is None:
            idea.archived_at = _now()
            self._touch(idea)
            await self._commit()
        return await self.to_detail(await self.get_idea(idea_id))

    async def _set_cover(self, idea: Idea, entry_id: Optional[uuid.UUID]) -> None:
        if entry_id is None:
            idea.cover_entry_id = None
            return
        entry = await self.db.scalar(
            select(IdeaEntry).where(
                IdeaEntry.id == entry_id,
                IdeaEntry.idea_id == idea.id,
                IdeaEntry.tenant_id == self.tenant.id,
            )
        )
        if entry is None or entry.kind not in IMAGE_KINDS or entry.archived_at is not None:
            raise _http(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "The cover must be an image or sketch of this idea that is not archived",
            )
        idea.cover_entry_id = entry.id

    # ============================================
    # Timeline (US2)
    # ============================================

    async def list_entries(
        self, idea_id: uuid.UUID, include_archived: bool = False
    ) -> IdeaEntryList:
        """The timeline: latest iteration first, pinned first, then newest first (FR-017)."""
        idea = await self.get_idea(idea_id)
        query = select(IdeaEntry).where(
            IdeaEntry.idea_id == idea.id, IdeaEntry.tenant_id == self.tenant.id
        )
        if not include_archived:
            query = query.where(IdeaEntry.archived_at.is_(None))
        rows = await self.db.scalars(
            query.order_by(
                IdeaEntry.iteration.desc(),
                IdeaEntry.pinned.desc(),
                IdeaEntry.created_at.desc(),
                IdeaEntry.id,
            )
        )
        return IdeaEntryList(
            items=[self.to_entry(e) for e in rows], current_iteration=idea.current_iteration
        )

    def _new_entry(self, idea: Idea, kind: str, **fields) -> IdeaEntry:
        return IdeaEntry(
            id=uuid.uuid4(),
            tenant_id=self.tenant.id,
            idea_id=idea.id,
            kind=kind,
            iteration=idea.current_iteration,
            author_user_id=self.user.id if self.user else None,
            created_at=_now(),
            **fields,
        )

    async def _entry_response(self, entry_id: uuid.UUID, idea: Idea) -> IdeaEntryResponse:
        return self.to_entry(await self.get_entry(idea, entry_id))

    async def add_entry(self, idea_id: uuid.UUID, data: IdeaEntryCreate) -> IdeaEntryResponse:
        """Add a note, link, measurement or decision to the current iteration."""
        idea = await self.get_idea(idea_id)
        body = data.body.strip() if data.body else None
        if data.kind == "link":
            if not data.link_url:
                raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, "A link entry needs a link")
        elif not body:
            raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, "This entry needs some text")
        entry = self._new_entry(idea, data.kind, body=body, link_url=data.link_url)
        self.db.add(entry)
        self._touch(idea)
        await self._commit()
        return await self._entry_response(entry.id, idea)

    async def add_images(
        self, idea_id: uuid.UUID, files: Sequence[UploadFile], kind: str = "image"
    ) -> ImageUploadResult:
        """
        Save each file as an image (or sketch) entry; refuse bad files one by one.

        Raises 422 when no file was given, too many were given, or every one was refused.
        """
        if kind not in IMAGE_KINDS:
            raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kind must be image or sketch")
        if not files:
            raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, "No file was sent")
        if len(files) > MAX_FILES_PER_UPLOAD:
            raise _http(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Upload at most {MAX_FILES_PER_UPLOAD} images at once",
            )
        idea = await self.get_idea(idea_id)
        created: list[IdeaEntry] = []
        refused: list[RefusedFile] = []
        for upload in files:
            content = await upload.read()
            try:
                stored = await self.storage.save_image(
                    content,
                    upload.content_type or "application/octet-stream",
                    str(idea.id),
                    original_filename=upload.filename,
                    owner_type="ideas",
                )
            except ImageStorageError as exc:
                refused.append(RefusedFile(filename=upload.filename, reason=str(exc)))
                continue
            entry = self._new_entry(
                idea,
                kind,
                image_url=stored["image_url"],
                thumbnail_url=stored["thumbnail_url"],
                content_type=stored["content_type"],
                original_filename=(upload.filename or "")[:255] or None,
                file_size=stored["file_size"],
            )
            self.db.add(entry)
            created.append(entry)
        if not created:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "No image was saved",
                    "refused": [r.model_dump() for r in refused],
                },
            )
        self._touch(idea)
        await self._commit()
        return ImageUploadResult(
            created=[await self._entry_response(e.id, idea) for e in created], refused=refused
        )

    async def update_entry(
        self, idea_id: uuid.UUID, entry_id: uuid.UUID, data: IdeaEntryUpdate
    ) -> IdeaEntryResponse:
        """Edit text or link, pin, archive or restore, or switch image ↔ sketch."""
        idea = await self.get_idea(idea_id)
        entry = await self.get_entry(idea, entry_id)
        changes = data.model_dump(exclude_unset=True)
        edited = False
        if "body" in changes:
            body = data.body.strip() if data.body else None
            if entry.kind in ("note", "measurement", "decision") and not body:
                raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, "This entry needs some text")
            edited = edited or body != entry.body
            entry.body = body
        if "link_url" in changes:
            if entry.kind == "link" and not data.link_url:
                raise _http(status.HTTP_422_UNPROCESSABLE_ENTITY, "A link entry needs a link")
            edited = edited or data.link_url != entry.link_url
            entry.link_url = data.link_url
        if data.kind is not None:
            if entry.kind not in IMAGE_KINDS:
                raise _http(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Only an image can become a sketch, and back",
                )
            entry.kind = data.kind
        if data.pinned is not None:
            entry.pinned = data.pinned
        if data.archived is not None:
            entry.archived_at = _now() if data.archived else None
            if data.archived and idea.cover_entry_id == entry.id:
                idea.cover_entry_id = None
        if edited:
            entry.edited_at = _now()
        self._touch(idea)
        await self._commit()
        return await self._entry_response(entry.id, idea)

    async def archive_entry(self, idea_id: uuid.UUID, entry_id: uuid.UUID) -> IdeaEntryResponse:
        """Archive an entry; clears the cover if it was the cover (FR-018)."""
        return await self.update_entry(idea_id, entry_id, IdeaEntryUpdate(archived=True))

    async def start_iteration(self, idea_id: uuid.UUID, note: Optional[str]) -> IdeaEntryList:
        """Move to the next iteration; the note, if any, is its first entry (FR-015)."""
        idea = await self.get_idea(idea_id)
        idea.current_iteration += 1
        if note and note.strip():
            self.db.add(self._new_entry(idea, "note", body=note.strip()))
        self._touch(idea)
        await self._commit()
        return await self.list_entries(idea_id)

    async def open_image(
        self, idea_id: uuid.UUID, entry_id: uuid.UUID, variant: str
    ) -> tuple[bytes, str, IdeaEntry]:
        """The bytes of an entry's image or thumbnail; 404 if there is none."""
        idea = await self.get_idea(idea_id)
        entry = await self.get_entry(idea, entry_id)
        url = entry.thumbnail_url if variant == "thumb" else entry.image_url
        if not url:
            raise _http(status.HTTP_404_NOT_FOUND, "This entry has no image")
        try:
            content, content_type = await self.storage.get_image(url)
        except ImageStorageError as exc:
            raise _http(status.HTTP_404_NOT_FOUND, "Image not found") from exc
        return content, entry.content_type or content_type, entry

    # ============================================
    # Conversion (US3)
    # ============================================

    async def _images_to_copy(self, idea: Idea) -> list[IdeaEntry]:
        """The cover first, then every pinned image or sketch in the order it was added."""
        rows = list(
            await self.db.scalars(
                select(IdeaEntry)
                .where(
                    IdeaEntry.idea_id == idea.id,
                    IdeaEntry.tenant_id == self.tenant.id,
                    IdeaEntry.kind.in_(IMAGE_KINDS),
                    IdeaEntry.archived_at.is_(None),
                    or_(IdeaEntry.pinned.is_(True), IdeaEntry.id == idea.cover_entry_id),
                )
                .order_by(IdeaEntry.iteration, IdeaEntry.created_at, IdeaEntry.id)
            )
        )
        rows.sort(key=lambda e: e.id != idea.cover_entry_id)
        return rows

    async def _cover_entry(self, idea: Idea) -> Optional[IdeaEntry]:
        if not idea.cover_entry_id:
            return None
        return await self.db.scalar(
            select(IdeaEntry).where(
                IdeaEntry.id == idea.cover_entry_id, IdeaEntry.tenant_id == self.tenant.id
            )
        )

    async def convert(self, idea_id: uuid.UUID, request: ConvertRequest) -> ConvertResponse:
        """
        Turn an idea into a model, or a product with its model, in one transaction.

        Uses the model and product creation services (no BOM row is written
        here); copies images through ImageStorage; on any failure rolls back
        and deletes the files it copied (FR-026, research R6).
        """
        idea = await self.get_idea(idea_id)
        if idea.archived_at is not None:
            raise _http(status.HTTP_409_CONFLICT, "Restore the idea before converting it")
        if idea.converted_product_id is not None:
            raise _http(status.HTTP_409_CONFLICT, "This idea was already converted to a product")
        if request.target == "product":
            # Conversion grants no more than the products screen (clarification, FR-002).
            await require_role(self.user, self.tenant, self.db, "admin")

        name = (request.name or idea.title).strip()
        copied: list[dict] = []
        warnings: list[str] = []
        # A savepoint, not the whole transaction: a failure undoes the conversion
        # alone and leaves the session (tenant, user, RLS setting) usable.
        savepoint = await self.db.begin_nested()
        try:
            model = None
            if idea.converted_model_id is not None:
                model = await self.db.scalar(
                    select(Model).where(
                        Model.id == idea.converted_model_id, Model.tenant_id == self.tenant.id
                    )
                )
            new_model = model is None
            if new_model:
                sku = request.model_sku or await SKUGeneratorService.generate_next_sku(
                    self.db, self.tenant.id, EntityType.MOD
                )
                model = await create_model(
                    self.db,
                    self.tenant,
                    self.user,
                    ModelCreate(sku=sku, name=name, description=idea.summary),
                    source_idea_id=idea.id,
                )
                cover = await self._cover_entry(idea)
                if request.include_images and cover is not None and cover.image_url:
                    result = await self._copy(cover, "products", model.id, warnings)
                    if result:
                        copied.append(result)
                        model.image_url = result["image_url"]

            product = None
            if request.target == "product":
                sku = request.product_sku or await SKUGeneratorService.generate_next_sku(
                    self.db, self.tenant.id, EntityType.PROD
                )
                product = await create_product(
                    self.db,
                    self.tenant,
                    self.user,
                    ProductCreate(
                        sku=sku,
                        name=name,
                        description=idea.summary,
                        models=[ProductModelCreate(model_id=model.id, quantity=1)],
                    ),
                    source_idea_id=idea.id,
                )
                if request.include_images:
                    saved = 0
                    for entry in await self._images_to_copy(idea):
                        result = await self._copy(entry, "products", product.id, warnings)
                        if result is None:
                            continue
                        copied.append(result)
                        self.db.add(
                            ProductImage(
                                tenant_id=self.tenant.id,
                                product_id=product.id,
                                image_url=result["image_url"],
                                thumbnail_url=result["thumbnail_url"],
                                alt_text=name[:255],
                                display_order=saved,
                                # The cover (first copied) is the primary image.
                                is_primary=saved == 0,
                                original_filename=entry.original_filename,
                                file_size=result["file_size"],
                                content_type=result["content_type"],
                            )
                        )
                        saved += 1
                idea.converted_product_id = product.id
                idea.was_converted_to_product = True

            idea.converted_model_id = model.id
            idea.was_converted_to_model = True
            idea.status = "converted"
            self._touch(idea)
            await savepoint.commit()
            await self.db.commit()
        except Exception:
            if savepoint.is_active:
                await savepoint.rollback()
            for result in copied:
                await self.storage.delete_image(result["image_url"], result["thumbnail_url"])
            logger.error(f"Conversion of idea {idea_id} failed and was rolled back")
            raise

        logger.info(f"Converted idea {idea_id} to {request.target}")
        return ConvertResponse(
            idea=await self.to_detail(await self.get_idea(idea_id)),
            model_id=model.id,
            product_id=product.id if product is not None else None,
            copied_images=len(copied),
            warnings=warnings,
        )

    async def _copy(
        self, entry: IdeaEntry, owner_type: str, owner_id: uuid.UUID, warnings: list[str]
    ) -> Optional[dict]:
        """Copy one entry's image; a missing file becomes a warning, not a failure."""
        try:
            return await self.storage.copy_image(entry.image_url, owner_type, str(owner_id))
        except ImageStorageError as exc:
            label = entry.original_filename or str(entry.id)
            warnings.append(f"Image {label} could not be copied: {exc}")
            logger.warning(f"Idea image {entry.id} not copied: {exc}")
            return None

    # ============================================
    # Import (US4)
    # ============================================

    async def import_items(self, items: list[dict], dry_run: bool = False) -> ImportResult:
        """
        Create Inbox ideas from report problems; skip links already imported.

        Each item is validated alone, so one bad item never blocks the others.
        """
        created: list[ImportCreated] = []
        skipped: list[ImportSkipped] = []
        refused: list[ImportRefused] = []
        parsed: list[tuple[int, ImportItem]] = []
        for index, raw in enumerate(items):
            try:
                parsed.append((index, ImportItem.model_validate(raw)))
            except ValidationError as exc:
                title = raw.get("title") if isinstance(raw, dict) else None
                first = exc.errors()[0]
                where = ".".join(str(p) for p in first.get("loc", ()))
                refused.append(
                    ImportRefused(
                        index=index,
                        title=title if isinstance(title, str) else None,
                        reason=f"{where}: {first.get('msg')}" if where else first.get("msg", ""),
                    )
                )

        links = [i.source_url for _, i in parsed if i.source_url]
        existing: dict[str, uuid.UUID] = {}
        if links:
            rows = await self.db.execute(
                select(Idea.source_url, Idea.id).where(
                    Idea.tenant_id == self.tenant.id,
                    Idea.source == "pain_point_report",
                    Idea.source_url.in_(links),
                )
            )
            existing = {url: idea_id for url, idea_id in rows}

        seen: set[str] = set()
        for index, item in parsed:
            try:
                data = IdeaCreate(
                    title=item.title,
                    summary=item.summary,
                    source="pain_point_report",
                    source_url=item.source_url,
                    tags=item.tags,
                    scores=item.scores or IdeaScores(),
                    report_score=item.report_score,
                )
            except ValidationError as exc:
                refused.append(
                    ImportRefused(index=index, title=item.title, reason=exc.errors()[0]["msg"])
                )
                continue
            link = data.source_url
            if link and (link in existing or link in seen):
                skipped.append(
                    ImportSkipped(
                        title=data.title, source_url=link, existing_idea_id=existing.get(link)
                    )
                )
                continue
            if link:
                seen.add(link)
            if dry_run:
                created.append(ImportCreated(id=None, title=data.title))
                continue
            idea = self._new_idea(data)
            self.db.add(idea)
            created.append(ImportCreated(id=idea.id, title=data.title))

        if not dry_run and created:
            await self._commit()
            logger.info(f"Imported {len(created)} ideas for tenant {self.tenant.id}")
        return ImportResult(created=created, skipped=skipped, refused=refused)
