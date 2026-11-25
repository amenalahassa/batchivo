"""A note pinned on a point of a model file, carried from one version to the next."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User

NOTE_STATUSES = ("open", "resolved", "carried_forward")


class ModelFileNote(Base, UUIDMixin, TimestampMixin):
    """
    A remark placed on a file at a point of the part (and a layer, on a sliced
    file).

    Positions are in the file's own coordinates, in mm. Geometry is not money,
    so floating point is the right type here (research D7).

    Carrying a note forward never moves it: a new note is created on the newer
    version, linked by ``carried_from_note_id``, and this one becomes
    ``carried_forward`` with its own position and text untouched, so each
    version's history stays as it was (clarification Q2). Deleting the file
    archives the note rather than dropping it (FR-030).
    """

    __tablename__ = "model_file_notes"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_file_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_file_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("model_files.id", ondelete="SET NULL"), nullable=True, index=True
    )
    number: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Display number of the pin within its file"
    )
    pos_x: Mapped[float] = mapped_column(Float, nullable=False)
    pos_y: Mapped[float] = mapped_column(Float, nullable=False)
    pos_z: Mapped[float] = mapped_column(Float, nullable=False)
    normal_x: Mapped[float] = mapped_column(Float, nullable=False)
    normal_y: Mapped[float] = mapped_column(Float, nullable=False)
    normal_z: Mapped[float] = mapped_column(Float, nullable=False)
    layer: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="Layer the note was placed on, for a sliced file"
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    resolved_in_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("model_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    carried_to_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("model_file_versions.id", ondelete="SET NULL"), nullable=True
    )
    carried_from_note_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("model_file_notes.id", ondelete="SET NULL"), nullable=True
    )
    author_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Set when its file was deleted"
    )

    author: Mapped[Optional["User"]] = relationship("User", lazy="select")

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved', 'carried_forward')",
            name="ck_model_file_notes_status",
        ),
        CheckConstraint("layer IS NULL OR layer >= 0", name="ck_model_file_notes_layer"),
        CheckConstraint("length(text) BETWEEN 1 AND 2000", name="ck_model_file_notes_text_length"),
        CheckConstraint(
            "status <> 'resolved' OR resolved_in_version_id IS NOT NULL",
            name="ck_model_file_notes_resolved_version",
        ),
        CheckConstraint(
            "status <> 'carried_forward' OR carried_to_version_id IS NOT NULL",
            name="ck_model_file_notes_carried_version",
        ),
    )

    def __repr__(self) -> str:
        return f"<ModelFileNote(file={self.model_file_id}, number={self.number}, status={self.status})>"
