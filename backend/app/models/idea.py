"""Product ideas and their brainstorming timeline (feature 007)."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    and_,
    case,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User

IDEA_STATUSES = (
    "inbox",
    "exploring",
    "validating",
    "ready",
    "converted",
    "parked",
    "dropped",
)
IDEA_SOURCES = ("manual", "pain_point_report", "customer", "other")
ENTRY_KINDS = ("note", "image", "link", "sketch", "measurement", "decision", "generation")
IMAGE_KINDS = ("image", "sketch")
TEXT_KINDS = ("note", "measurement", "decision")
SCORE_FIELDS = (
    "score_frequency",
    "score_frustration",
    "score_printability",
    "score_gap",
    "score_willingness_to_pay",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class Idea(Base, UUIDMixin, TimestampMixin):
    """
    A product idea of one shop: what the problem is, where it came from, how it
    scores and what it became.

    The total score is never stored (principle V): ``score`` is the sum of the
    five scores when all are set, otherwise the ``report_score`` an imported
    pain-point report gave, otherwise nothing. ``report_score`` is an input with
    its own origin, written on creation or import and never recomputed.
    """

    __tablename__ = "ideas"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="inbox")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    source_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    tags: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list
    )
    score_frequency: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    score_frustration: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    score_printability: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    score_gap: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    score_willingness_to_pay: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    report_score: Mapped[Optional[int]] = mapped_column(
        SmallInteger, nullable=True, comment="Total out of 25 given by an imported report"
    )
    current_iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cover_entry_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey(
            "idea_entries.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_ideas_cover_entry_id",
        ),
        nullable=True,
    )
    converted_model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL"), nullable=True, index=True
    )
    converted_product_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    was_converted_to_model: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    was_converted_to_product: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[Optional["User"]] = relationship("User", lazy="joined")

    __table_args__ = (
        CheckConstraint("length(trim(title)) BETWEEN 1 AND 200", name="ck_ideas_title"),
        CheckConstraint(f"status IN ({_in(IDEA_STATUSES)})", name="ck_ideas_status"),
        CheckConstraint(f"source IN ({_in(IDEA_SOURCES)})", name="ck_ideas_source"),
        *(
            CheckConstraint(f"{f} IS NULL OR {f} BETWEEN 1 AND 5", name=f"ck_ideas_{f}")
            for f in SCORE_FIELDS
        ),
        CheckConstraint(
            "report_score IS NULL OR report_score BETWEEN 0 AND 25", name="ck_ideas_report_score"
        ),
        CheckConstraint("current_iteration >= 1", name="ck_ideas_current_iteration"),
        # One idea per report link in a shop, archived and converted ones included (FR-032).
        Index(
            "uq_ideas_report_source",
            "tenant_id",
            "source_url",
            unique=True,
            postgresql_where=text("source = 'pain_point_report' AND source_url IS NOT NULL"),
            sqlite_where=text("source = 'pain_point_report' AND source_url IS NOT NULL"),
        ),
    )

    @hybrid_property
    def score(self) -> Optional[int]:
        """The idea's score: computed total of the five scores, else the report score."""
        values = [getattr(self, f) for f in SCORE_FIELDS]
        if all(v is not None for v in values):
            return sum(values)
        return self.report_score

    @score.inplace.expression
    @classmethod
    def _score_expression(cls):
        columns = [getattr(cls, f) for f in SCORE_FIELDS]
        all_set = and_(*(c.isnot(None) for c in columns))
        total = columns[0] + columns[1] + columns[2] + columns[3] + columns[4]
        return case((all_set, total), else_=cls.report_score)

    @property
    def score_source(self) -> Optional[str]:
        """Where ``score`` comes from: ``scores``, ``report`` or None."""
        if all(getattr(self, f) is not None for f in SCORE_FIELDS):
            return "scores"
        if self.report_score is not None:
            return "report"
        return None

    def __repr__(self) -> str:
        return f"<Idea(title={self.title!r}, status={self.status})>"


class IdeaEntry(Base, UUIDMixin, TimestampMixin):
    """
    One item of an idea's timeline: a note, an image, a link, a sketch, a
    measurement, a decision, or (from feature 008) a generated result.

    One polymorphic table keeps the timeline a single ordered query and lets
    new kinds appear without new tables. ``generation_job_id`` is reserved for
    the generative AI feature, which adds its foreign key.
    """

    __tablename__ = "idea_entries"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idea_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ideas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="Storage key, never served publicly"
    )
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    original_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    link_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    generation_job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        nullable=True, comment="Generation job that produced the entry (FK added by feature 008)"
    )
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    author_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    author: Mapped[Optional["User"]] = relationship("User", lazy="joined")

    __table_args__ = (
        CheckConstraint(f"kind IN ({_in(ENTRY_KINDS)})", name="ck_idea_entries_kind"),
        CheckConstraint(
            f"kind NOT IN ({_in(IMAGE_KINDS)}) OR image_url IS NOT NULL",
            name="ck_idea_entries_image",
        ),
        CheckConstraint("kind <> 'link' OR link_url IS NOT NULL", name="ck_idea_entries_link"),
        CheckConstraint(
            f"kind NOT IN ({_in(TEXT_KINDS)}) OR (body IS NOT NULL AND length(trim(body)) > 0)",
            name="ck_idea_entries_text",
        ),
        CheckConstraint("iteration >= 1", name="ck_idea_entries_iteration"),
    )

    def __repr__(self) -> str:
        return f"<IdeaEntry(kind={self.kind}, iteration={self.iteration})>"
