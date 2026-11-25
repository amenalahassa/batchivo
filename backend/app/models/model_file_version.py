"""A revision of a model's design: the files uploaded together, one of them printed."""

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.model import Model
    from app.models.model_file import ModelFile
    from app.models.user import User


class ModelFileVersion(Base, UUIDMixin, TimestampMixin):
    """
    A version groups the files of one revision of a model -- typically the
    source mesh and the sliced plate made from it -- with a note on what
    changed.

    Exactly one version per model is active: the one used for the final print
    (FR-009). Within a version, one sliced file is the print file, the only file
    whose print time, plate count and filament weight are offered to the cost
    profile (FR-011a). Nothing here is applied on its own; activation goes
    through a review of the figures that would change (FR-012).
    """

    __tablename__ = "model_file_versions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="1, 2, 3... per model; orders versions newest first"
    )
    label: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="Shown to the operator; defaults to the sequence"
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="What changed")
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="The version used for the final print; one per model",
    )
    # use_alter: model_files also points here, so the two tables reference each other.
    print_file_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(
            "model_files.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_model_file_versions_print_file_id",
        ),
        nullable=True,
        comment="The sliced file whose figures feed the cost profile",
    )
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    model: Mapped["Model"] = relationship("Model", back_populates="file_versions")
    files: Mapped[list["ModelFile"]] = relationship(
        "ModelFile",
        back_populates="file_version",
        foreign_keys="ModelFile.version_id",
        order_by="ModelFile.uploaded_at.desc()",
    )
    created_by: Mapped[Optional["User"]] = relationship("User", lazy="select")

    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_model_file_versions_sequence_positive"),
        CheckConstraint(
            "length(label) BETWEEN 1 AND 50", name="ck_model_file_versions_label_length"
        ),
        Index("uq_model_file_versions_model_sequence", "model_id", "sequence", unique=True),
        Index(
            "uq_model_file_versions_one_active",
            "model_id",
            unique=True,
            postgresql_where=text("is_active"),
            sqlite_where=text("is_active"),
        ),
    )

    def __repr__(self) -> str:
        return f"<ModelFileVersion(model_id={self.model_id}, label={self.label!r}, active={self.is_active})>"
