"""Design briefs and their immutable revisions (spec 009, Preflight foundations).

A brief is the Preflight design file of one part: the intent document as the
Preflight skill writes it (``intent.yaml``, stored as written), the risk summary
and triage result, the design plan, the design parameters and the status of each
per-part Preflight step. It starts on an idea or a model; a model converted from
an idea reaches the idea's brief through ``models.source_idea_id`` (research R1).

Every save that changes the intent, the risk part or the plan appends a
``DesignBriefRevision`` (clarification Q1). Revisions are never changed: a
database trigger refuses UPDATE on them (research R2).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    DDL,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

#: Per-part Preflight commands, in the skill's order (research R4).
PREFLIGHT_STEPS = (
    "intent",
    "adopt",
    "clarify",
    "risk",
    "plan",
    "design",
    "check",
    "slice",
    "print",
    "test",
    "learn",
    "render",
    "ship",
    "quick",
)
STEP_STATUSES = ("not_started", "in_progress", "done", "skipped", "blocked")
#: Preflight's own risk classes (``pf.py triage`` ``risk_class``).
RISK_CLASSES = ("faible", "moyen", "élevé", "arrêt")
REVISION_PARTS = ("intent", "risk", "plan")

_JSON = JSON().with_variant(JSONB(), "postgresql")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class DesignBrief(Base, UUIDMixin, TimestampMixin):
    """The Preflight design file of a part, on an idea and/or the model it became."""

    __tablename__ = "design_briefs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Both SET NULL: ideas and models are soft-deleted, and the "at least one"
    # rule is the service's (research R1), so a hard delete never fails here.
    idea_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("ideas.id", ondelete="SET NULL"), nullable=True
    )
    model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("models.id", ondelete="SET NULL"), nullable=True
    )
    intent: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True)
    intent_schema_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    risk_class: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    risk_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    triage: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True)
    plan_md: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    params: Mapped[Optional[dict]] = mapped_column(_JSON, nullable=True)
    params_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    step_status: Mapped[dict] = mapped_column(_JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            f"risk_class IS NULL OR risk_class IN ({_in(RISK_CLASSES)})",
            name="ck_design_briefs_risk_class",
        ),
        Index(
            "uq_design_briefs_idea",
            "idea_id",
            unique=True,
            postgresql_where=text("idea_id IS NOT NULL"),
            sqlite_where=text("idea_id IS NOT NULL"),
        ),
        Index(
            "uq_design_briefs_model",
            "model_id",
            unique=True,
            postgresql_where=text("model_id IS NOT NULL"),
            sqlite_where=text("model_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<DesignBrief(id={self.id}, idea={self.idea_id}, model={self.model_id})>"


class DesignBriefRevision(Base, UUIDMixin, TimestampMixin):
    """An immutable copy of a brief's intent, risk part or plan as saved at one moment."""

    __tablename__ = "design_brief_revisions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brief_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("design_briefs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    part: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[dict] = mapped_column(_JSON, nullable=False)
    schema_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    author_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(f"part IN ({_in(REVISION_PARTS)})", name="ck_design_brief_revisions_part"),
        Index("ix_design_brief_revisions_brief_created", "brief_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<DesignBriefRevision(brief={self.brief_id}, part={self.part})>"


#: Refuses any UPDATE of a revision (principle VI). Shared with the migration.
REVISION_TRIGGER_SQL = (
    # The one change allowed: ON DELETE SET NULL clearing the author of a deleted user.
    "CREATE OR REPLACE FUNCTION design_brief_revisions_immutable() RETURNS trigger AS $$ "
    "BEGIN "
    "IF NEW.author_user_id IS NULL "
    "AND (to_jsonb(NEW) - 'author_user_id') = (to_jsonb(OLD) - 'author_user_id') "
    "THEN RETURN NEW; END IF; "
    "RAISE EXCEPTION 'design brief revisions are immutable'; END; $$ LANGUAGE plpgsql",
    "CREATE TRIGGER trg_design_brief_revisions_immutable BEFORE UPDATE ON design_brief_revisions "
    "FOR EACH ROW EXECUTE FUNCTION design_brief_revisions_immutable()",
)

for _statement in REVISION_TRIGGER_SQL:
    # create_all (test databases) gets the trigger too; the migration creates it explicitly.
    event.listen(
        DesignBriefRevision.__table__,
        "after_create",
        DDL(_statement).execute_if(dialect="postgresql"),
    )
