"""Generation jobs, their stored files and what they became (feature 008).

A job is one request for a capability. Its capability, provider, model, version,
inputs, seed, target and price are written once at creation (constitution VI):
any output can be traced to exactly how it was made. Files the layer uses or
produces live in ``genai_assets``; ``genai_adoptions`` records each place an
output was explicitly adopted into (an idea entry, a product image, a model file).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.expression import true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User

CAPABILITIES = (
    "concept_image",
    "image_edit",
    "product_photo_enhance",
    "background_remove",
    "upscale",
    "lifestyle_scene",
    "image_to_3d",
)
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "canceled")
ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("succeeded", "failed", "canceled")
TARGET_TYPES = ("idea", "product", "model", "none")
ASSET_SOURCES = ("output", "upload")
ASSET_KINDS = ("image", "mesh")
ADOPTION_OWNERS = ("idea", "product", "model")
COST_PROVENANCES = ("computed", "estimated")

_JSON = JSON().with_variant(JSONB(), "postgresql")
_MONEY = Numeric(12, 4)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class GenerationJob(Base, UUIDMixin, TimestampMixin):
    """One request for a generative capability, run by a provider in the background."""

    __tablename__ = "generation_jobs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    model_version: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Pinned version id, or 'official' (not pinnable)"
    )
    model_version_ran: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, comment="Version the provider reports it ran; set once"
    )
    inputs: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_type: Mapped[str] = mapped_column(String(10), nullable=False, default="none")
    target_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued", index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    estimated_cost: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=Decimal("0"))
    cost: Mapped[Optional[Decimal]] = mapped_column(_MONEY, nullable=True)
    cost_provenance: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    price_snapshot: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    #: False when the result cannot show the real item: a concept or 3D-draft capability, or
    #: an input that is itself not the real item (an output or idea entry of such a job, a
    #: sketch). Decided once at creation; a product adoption then needs a confirmation (FR-030).
    shows_real_item: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    #: input files uploaded to the provider for this job, deleted there once it ends (R7)
    provider_files: Mapped[Optional[list]] = mapped_column(_JSON, nullable=True)
    requested_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    requested_by: Mapped[Optional["User"]] = relationship("User", lazy="joined")
    outputs: Mapped[list["GenAIAsset"]] = relationship(
        "GenAIAsset",
        back_populates="job",
        order_by="GenAIAsset.position",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        CheckConstraint(
            f"capability IN ({_in(CAPABILITIES)})", name="ck_generation_jobs_capability"
        ),
        CheckConstraint(f"status IN ({_in(JOB_STATUSES)})", name="ck_generation_jobs_status"),
        CheckConstraint(f"target_type IN ({_in(TARGET_TYPES)})", name="ck_generation_jobs_target"),
        CheckConstraint(
            "(target_type = 'none') = (target_id IS NULL)", name="ck_generation_jobs_target_id"
        ),
        CheckConstraint(
            f"cost_provenance IS NULL OR cost_provenance IN ({_in(COST_PROVENANCES)})",
            name="ck_generation_jobs_cost_provenance",
        ),
        CheckConstraint("estimated_cost >= 0", name="ck_generation_jobs_estimate_positive"),
        CheckConstraint("cost IS NULL OR cost >= 0", name="ck_generation_jobs_cost_positive"),
        Index("ix_generation_jobs_target", "tenant_id", "target_type", "target_id", "created_at"),
        Index("ix_generation_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_generation_jobs_tenant_created", "tenant_id", "created_at"),
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def __repr__(self) -> str:
        return f"<GenerationJob({self.capability}, {self.status})>"


class GenAIAsset(Base, UUIDMixin, TimestampMixin):
    """A stored file used or produced by the genai layer: an input upload or an output."""

    __tablename__ = "genai_assets"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("generation_jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_url: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: For an upload: whether the picture shows the real item. False for an import of a
    #: sketch, of a generation entry or an ``ai`` product image that does not; decided once,
    #: when the image is imported, so reusing the asset by id keeps the answer (FR-030).
    #: An output follows its job's ``shows_real_item`` instead.
    shows_real_item: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    job: Mapped[Optional[GenerationJob]] = relationship("GenerationJob", back_populates="outputs")
    adoptions: Mapped[list["GenAIAdoption"]] = relationship(
        "GenAIAdoption",
        back_populates="asset",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="GenAIAdoption.created_at",
    )

    __table_args__ = (
        CheckConstraint(f"source IN ({_in(ASSET_SOURCES)})", name="ck_genai_assets_source"),
        CheckConstraint(f"kind IN ({_in(ASSET_KINDS)})", name="ck_genai_assets_kind"),
        CheckConstraint("(source = 'output') = (job_id IS NOT NULL)", name="ck_genai_assets_job"),
        CheckConstraint("source <> 'output' OR ai_generated", name="ck_genai_assets_ai_generated"),
    )

    def __repr__(self) -> str:
        return f"<GenAIAsset({self.source}, {self.kind})>"


#: An adoption names at most one result (FK set to NULL when that result is deleted).
ONE_RESULT = (
    "(CASE WHEN idea_entry_id IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN product_image_id IS NULL THEN 0 ELSE 1 END"
    " + CASE WHEN model_file_id IS NULL THEN 0 ELSE 1 END) <= 1"
)


class GenAIAdoption(Base, UUIDMixin, TimestampMixin):
    """One explicit adoption of an output into an idea, a product or a model."""

    __tablename__ = "genai_adoptions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("genai_assets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_type: Mapped[str] = mapped_column(String(10), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    idea_entry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("idea_entries.id", ondelete="SET NULL"), nullable=True
    )
    product_image_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("product_images.id", ondelete="SET NULL"), nullable=True
    )
    model_file_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("model_files.id", ondelete="SET NULL"), nullable=True
    )
    warning_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    adopted_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    asset: Mapped[GenAIAsset] = relationship("GenAIAsset", back_populates="adoptions")

    __table_args__ = (
        CheckConstraint(f"owner_type IN ({_in(ADOPTION_OWNERS)})", name="ck_genai_adoptions_owner"),
        CheckConstraint(ONE_RESULT, name="ck_genai_adoptions_one_result"),
        UniqueConstraint("asset_id", "owner_type", "owner_id", name="uq_genai_adoptions_target"),
        Index("ix_genai_adoptions_owner", "tenant_id", "owner_type", "owner_id"),
    )

    def __repr__(self) -> str:
        return f"<GenAIAdoption({self.owner_type})>"


__all__ = [
    "ACTIVE_STATUSES",
    "ADOPTION_OWNERS",
    "ASSET_KINDS",
    "ASSET_SOURCES",
    "CAPABILITIES",
    "JOB_STATUSES",
    "TARGET_TYPES",
    "TERMINAL_STATUSES",
    "GenAIAdoption",
    "GenAIAsset",
    "GenerationJob",
]
