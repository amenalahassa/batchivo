"""Tier 4a of the pricing rebuild: estimate revisions held for review.

Revision ID: pricing_tier4_v1
Revises: pricing_tier3_v1

One table, and two constraints on it that are the whole point:

* **At most one pending proposal per figure**, as a partial unique index over
  ``state = 'pending'``. Two pending proposals on one figure make "accept"
  ambiguous, and the service supersedes rather than queues (data-model.md), so
  a second pending row is a bug worth refusing at the database rather than
  trusting a convention to prevent.

* **A decided proposal names its reviewer and its moment.** A ``CHECK`` ties
  ``reviewed_at`` to the state: null while pending, set once decided. A
  decision nobody is recorded as having made is a decision nobody can question
  (Constitution VI), and an accepted revision moves a figure that reaches
  every price.

``derived_from_run_ids`` is JSONB on PostgreSQL and portable JSON on SQLite,
where the test suite runs. FR-042d is implemented against it: a rejected
proposal must not be re-raised from the **same** outcomes while still allowing
a later one from **new** outcomes, which needs the outcomes behind each
rejection on record.

Nothing is backfilled. There is no proposal to reconstruct: a proposal is a
question raised at a moment about evidence that existed then, and inventing
historical ones would ask the operator to review decisions nobody proposed.

## The downgrade

``downgrade()`` drops the table, which **discards every pending and decided
proposal**. The estimates themselves are untouched — they live on their own
records — so nothing an operator priced against is lost. What is lost is the
record of which proposals were rejected, and therefore FR-042d's memory: after
a downgrade and re-upgrade, a change an operator has already declined can be
proposed to them again from the same outcomes.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "pricing_tier4_v1"
down_revision = "pricing_tier3_v1"
branch_labels = None
depends_on = None

TABLE = "estimate_revisions"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _enable_rls(table: str) -> None:
    """Tenant isolation at the database layer, as Constitution I requires.

    Guarded so the statement is a no-op outside PostgreSQL: the test suite runs
    on SQLite, where RLS does not exist, and a hard failure there would make
    the migration untestable rather than safe.
    """
    if not _is_postgres():
        return
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        f"USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
    )


def _disable_rls(table: str) -> None:
    if not _is_postgres():
        return
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def _uuid_default() -> sa.sql.elements.TextClause | None:
    """``gen_random_uuid()`` on PostgreSQL, nothing on SQLite."""
    if _is_postgres():
        return sa.text("gen_random_uuid()")
    return None


def _json_type():
    """``JSONB`` on PostgreSQL, portable ``JSON`` on SQLite.

    A column that could only be written in production is a column nothing
    tests, and FR-042d is implemented entirely against this one.
    """
    return postgresql.JSONB() if _is_postgres() else sa.JSON()


def upgrade() -> None:
    is_postgres = _is_postgres()
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.Uuid()
    now = sa.func.now()

    op.create_table(
        TABLE,
        sa.Column("id", uuid_type, primary_key=True, server_default=_uuid_default()),
        sa.Column(
            "tenant_id",
            uuid_type,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column(
            "entity_id",
            uuid_type,
            nullable=False,
            comment="The record's id. Not a foreign key: the entity type varies",
        ),
        sa.Column(
            "field_name",
            sa.String(60),
            nullable=False,
            comment="A registered pricing input marked learnable (FR-042g)",
        ),
        sa.Column(
            "current_value",
            sa.Numeric(14, 6),
            nullable=False,
            comment=(
                "The estimate in force when this was raised. Stored, not "
                "recomputed at review time: the figure may have moved since "
                "for an unrelated reason (FR-042c)"
            ),
        ),
        sa.Column("observed_value", sa.Numeric(14, 6), nullable=False),
        sa.Column(
            "divergence_pct",
            sa.Numeric(9, 4),
            nullable=False,
            comment="The figure that was compared against the operator's threshold",
        ),
        sa.Column(
            "derived_from_run_ids",
            _json_type(),
            nullable=False,
            comment="The outcome ids behind the observed value; FR-042d reads this",
        ),
        sa.Column("state", sa.String(10), nullable=False, server_default="pending"),
        sa.Column(
            "reviewed_by_user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "observed_as_of",
            sa.Date,
            nullable=False,
            comment=(
                "The business date the observation covers, which becomes the "
                "figure's provenance date on acceptance (FR-042f)"
            ),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(
            "state IN ('pending', 'accepted', 'rejected')",
            name="ck_estimate_revision_state",
        ),
        # A decided proposal says who decided it and when.
        sa.CheckConstraint(
            "(state = 'pending' AND reviewed_at IS NULL)"
            " OR (state <> 'pending' AND reviewed_at IS NOT NULL)",
            name="ck_estimate_revision_reviewed_when_decided",
        ),
        comment=(
            "Proposed estimate changes held for review beyond the operator's "
            "divergence threshold (FR-042b)"
        ),
    )

    op.create_index(f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"])
    op.create_index(f"ix_{TABLE}_state", TABLE, ["state"])

    # The read the review screen does.
    op.create_index(
        "ix_estimate_revisions_tenant_state", TABLE, ["tenant_id", "state"]
    )
    # The read FR-042d does: has this field been rejected before, and from
    # which outcomes?
    op.create_index(
        "ix_estimate_revisions_field",
        TABLE,
        ["tenant_id", "entity_type", "entity_id", "field_name"],
    )
    # At most one pending proposal per figure. A partial unique index rather
    # than a plain one: a figure may accumulate any number of *decided*
    # proposals, and FR-042d needs every one of them.
    op.execute(
        f"CREATE UNIQUE INDEX uq_estimate_revision_pending ON {TABLE} "
        f"(tenant_id, entity_type, entity_id, field_name) WHERE state = 'pending'"
    )

    _enable_rls(TABLE)


def downgrade() -> None:
    """Drop the table, discarding every proposal and every rejection.

    The estimates themselves are untouched, so nothing an operator priced
    against is lost. FR-042d's memory is: a change already declined can be
    proposed again from the same outcomes after a re-upgrade.
    """
    _disable_rls(TABLE)
    op.drop_index("uq_estimate_revision_pending", table_name=TABLE)
    op.drop_index("ix_estimate_revisions_field", table_name=TABLE)
    op.drop_index("ix_estimate_revisions_tenant_state", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_state", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
