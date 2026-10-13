"""A requested catalogue-wide calculation, and what it found.

A scenario asks "if filament rose 25%, which products stop paying?". The
answer takes as long as the catalogue takes, so the request is acknowledged
and the work happens on a worker (FR-044a). This table is what makes that
honest: the state lives in the database rather than in the broker, so a run
reports its state across a worker restart (FR-044b, research.md D4).

**Nothing here is authoritative.** Not one figure in ``result_json`` is a cost
or a price the system will use for anything (FR-044d). It is a hypothetical,
and a result read a fortnight later says which hypothetical it was: the shock
applied and the inputs it ran against (FR-044c). Without that, an operator
reading an old result cannot tell it from a current report -- and would act on
a material price that has since changed twice.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

#: Every state a run can be in. ``partial`` is the one that matters: a sweep
#: that costed nine hundred products and could not cost four has an answer
#: worth reading, and reporting it as ``failed`` would throw that away while
#: reporting it as ``succeeded`` would hide the gap (FR-044b).
SCENARIO_STATES: tuple[str, ...] = ("queued", "running", "succeeded", "partial", "failed")

#: Terminal states: a run in one of these is never executed again, so a worker
#: retry cannot restate a result an operator has already read.
TERMINAL_STATES: frozenset[str] = frozenset({"succeeded", "partial", "failed"})

#: JSONB on PostgreSQL, plain JSON on the SQLite test database. The variant
#: keeps one model definition working on both (research.md D8).
_JSON = JSON().with_variant(JSONB(), "postgresql")


class ScenarioRun(Base, UUIDMixin, TimestampMixin):
    """One requested shock, its state, and the products it put below the floor."""

    __tablename__ = "scenario_runs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Who asked. Nullable because a run may be started by a schedule rather
    #: than a person, and a scheduled run with a fabricated author is worse
    #: than one with none.
    requested_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    #: The overrides applied, as decimal strings. Stored rather than derived:
    #: FR-044c needs the question answerable from the row alone.
    shock_json: Mapped[dict[str, Any]] = mapped_column(_JSON, nullable=False, default=dict)

    #: What the run actually used -- the labor rate, the margin basis, the
    #: reference date, the channels swept. A shock is only interpretable
    #: against the figures it was applied to.
    inputs_json: Mapped[Optional[dict[str, Any]]] = mapped_column(_JSON, nullable=True)

    #: The margin below which a product is reported. The operator's judgement
    #: of what is worth selling, not a system default.
    margin_floor_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)

    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued", index=True
    )

    result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(_JSON, nullable=True)

    #: Why a run stopped, in words an operator can act on. Set for ``failed``
    #: and left null otherwise.
    error_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_scenario_run_state",
        ),
        # A failure with no reason is a job that appears to have hung, which is
        # the one outcome FR-044b forbids.
        CheckConstraint(
            "state <> 'failed' OR error_text IS NOT NULL",
            name="ck_scenario_run_failure_has_a_reason",
        ),
        CheckConstraint(
            "margin_floor_pct >= -100 AND margin_floor_pct <= 100",
            name="ck_scenario_run_floor_is_a_percentage",
        ),
        Index("idx_scenario_runs_tenant_created", "tenant_id", "created_at"),
    )

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def below_floor(self) -> list[dict[str, Any]]:
        """The products the shock put below the floor, or an empty list.

        Empty for a run that has not finished, which reads correctly: nothing
        has been found yet, as against nothing being wrong.
        """
        if not self.result_json:
            return []
        found = self.result_json.get("below_floor")
        return list(found) if isinstance(found, list) else []

    def __repr__(self) -> str:
        return f"<ScenarioRun(id={self.id}, state={self.state})>"
