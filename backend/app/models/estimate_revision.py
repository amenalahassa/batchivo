"""A proposed change to an estimate, held for review (task T103, FR-042b-g).

An observed outcome usually improves an estimate, and FR-042a has it update the
figure on its own once enough outcomes agree. The exception is the whole reason
this table exists: **an observation that disagrees with the estimate by a large
margin is more often a faulty measurement than a discovery**. A smart plug
reporting 9 kW, a print logged at 95 hours instead of 9.5, a spool weighed
before it was dried — each of those would move a price, and the price would be
wrong in a way nobody could trace back to a sensor.

So beyond the operator's divergence threshold the update is written here instead
of being applied (FR-042b), and a person decides.

## What this table is not

It is **not** a queue. A later proposal on the same field supersedes an earlier
pending one rather than joining it (FR-042d's companion rule in data-model.md).
Two pending proposals on one figure would make "accept" ambiguous, and the
newer one is always built from more outcomes than the older.

It is **not** a history of estimates. The figure itself lives on its own
record, and its origin lives in `pricing_input_provenance`. This row records a
proposal and its fate.

## The rules the columns exist for

* `current_value` and `observed_value` are both stored, because FR-042c
  requires the proposal to state what it would change *from* as well as *to*.
  Recomputing the "from" at review time would show the operator a comparison
  against whatever the figure says today, which may have moved for an unrelated
  reason.
* `divergence_pct` is stored rather than derived on read for the same reason:
  it is the figure that was compared against the threshold at the time, and
  re-deriving it from two values one of which may since have changed would let
  a proposal appear to have been raised for no reason.
* `derived_from_run_ids` is the evidence. FR-042d turns on it: a rejected
  proposal must not be re-raised from the **same** outcomes, but must not
  suppress a later one from **new** ones. Without the list of outcomes behind a
  rejection, the only implementable rules are "never propose this field again"
  and "propose it every time", and both are wrong.
* `reviewed_by_user_id` and `reviewed_at` are null while pending. A decision
  nobody is recorded as having made is a decision that cannot be questioned
  (Constitution VI).

## Tenant isolation

Tenant-scoped like everything else (Constitution I). The RLS policy is created
by the Tier 4 migration; the application filter is in
`app/services/variance_service.py`, which never queries without it.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.user import User

#: The three states a proposal can be in. Terminal states are terminal: an
#: accepted or rejected row is never reopened, because its fate is part of the
#: record FR-042d reads to decide whether to propose again.
REVISION_STATES: tuple[str, ...] = ("pending", "accepted", "rejected")


def _json_type():
    """``JSONB`` on PostgreSQL, portable ``JSON`` on SQLite.

    The test suite runs on SQLite, where ``JSONB`` does not exist. A column
    that could only be written in production is a column nothing tests.
    """
    return JSON().with_variant(JSONB(), "postgresql")


class EstimateRevision(Base, UUIDMixin, TimestampMixin):
    """One proposed change to one estimated figure."""

    __tablename__ = "estimate_revisions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Which figure
    # ------------------------------------------------------------------

    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Which kind of record the field belongs to; see PROVENANCE_ENTITY_TYPES",
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        comment="The record's id. Not a foreign key: the entity type varies",
    )

    field_name: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        comment=(
            "The field this proposal would change. Must be a registered "
            "pricing input marked learnable -- an operator decision is never "
            "proposed against (FR-042g)"
        ),
    )

    # ------------------------------------------------------------------
    # What it proposes, as it stood when it was raised (FR-042c)
    # ------------------------------------------------------------------

    current_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 6),
        nullable=False,
        comment=(
            "The estimate in force when this was raised. Stored, not "
            "recomputed at review time: the figure may have moved since for an "
            "unrelated reason, and the operator must see the comparison that "
            "was actually made"
        ),
    )

    observed_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 6),
        nullable=False,
        comment="The rolling average of the outcomes this proposal came from",
    )

    confidence: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 4),
        nullable=True,
        comment=(
            "How far to believe the observed value, in (0, 1], from the count and "
            "spread of the outcomes behind it (T259)"
        ),
    )

    divergence_pct: Mapped[Decimal] = mapped_column(
        Numeric(9, 4),
        nullable=False,
        comment=(
            "How far the observation sat from the estimate, as a percentage of "
            "the estimate. Stored because this is the figure that was compared "
            "against the threshold"
        ),
    )

    derived_from_run_ids: Mapped[list] = mapped_column(
        _json_type(),
        nullable=False,
        comment=(
            "The outcome ids behind the observed value, as a JSON array of "
            "strings. FR-042d turns on this: a rejected proposal is not "
            "re-raised from the same outcomes but does not suppress one from "
            "new outcomes"
        ),
    )

    # ------------------------------------------------------------------
    # Its fate
    # ------------------------------------------------------------------

    state: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | accepted | rejected; terminal states are terminal",
    )

    reviewed_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Who accepted or rejected it. Null while pending",
    )

    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When it was decided. Null while pending",
    )

    observed_as_of: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment=(
            "The business date the observation covers, which becomes the "
            "figure's provenance date on acceptance (FR-042f)"
        ),
    )

    # ------------------------------------------------------------------

    tenant: Mapped["Tenant"] = relationship("Tenant", lazy="raise")
    reviewed_by: Mapped[Optional["User"]] = relationship("User", lazy="raise")

    __table_args__ = (
        # At most one pending proposal per figure. A later proposal supersedes
        # an earlier one rather than queueing, so two pending rows on one field
        # is a bug -- and it is one that would make "accept" ambiguous, which
        # is worth a constraint rather than a convention.
        Index(
            "uq_estimate_revision_pending",
            "tenant_id",
            "entity_type",
            "entity_id",
            "field_name",
            unique=True,
            postgresql_where=state == "pending",
            sqlite_where=state == "pending",
        ),
        # The read the review screen does.
        Index(
            "ix_estimate_revisions_tenant_state",
            "tenant_id",
            "state",
        ),
        # The read FR-042d does: has this field been rejected before, and from
        # which outcomes?
        Index(
            "ix_estimate_revisions_field",
            "tenant_id",
            "entity_type",
            "entity_id",
            "field_name",
        ),
        CheckConstraint(
            "state IN ('pending', 'accepted', 'rejected')",
            name="ck_estimate_revision_state",
        ),
        # A decided proposal says who decided it and when. Enforced rather than
        # trusted: a decision with no reviewer is one nobody can question.
        CheckConstraint(
            "(state = 'pending' AND reviewed_at IS NULL)"
            " OR (state <> 'pending' AND reviewed_at IS NOT NULL)",
            name="ck_estimate_revision_reviewed_when_decided",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence > 0 AND confidence <= 1)",
            name="ck_estimate_revision_confidence",
        ),
        {
            "comment": (
                "Proposed estimate changes held for review beyond the "
                "operator's divergence threshold (FR-042b)"
            )
        },
    )

    @property
    def is_pending(self) -> bool:
        return self.state == "pending"

    @property
    def run_ids(self) -> frozenset[str]:
        """The outcomes behind this proposal, as a set of strings.

        A set, because FR-042d's question is "are these the same outcomes?",
        which is set equality and not list equality -- the order two queries
        return outcomes in is not a difference the operator should see.
        """
        return frozenset(str(value) for value in (self.derived_from_run_ids or []))

    def __repr__(self) -> str:
        return (
            f"<EstimateRevision {self.entity_type}.{self.field_name} "
            f"{self.current_value} -> {self.observed_value} ({self.state})>"
        )
