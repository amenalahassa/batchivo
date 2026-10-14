"""Tier 4b of the pricing rebuild: scenario runs.

Revision ID: pricing_tier4b_v1
Revises: pricing_tier4_v1

One table holding a requested catalogue-wide shock, its state and what it
found. Separate from ``pricing_tier4_v1`` rather than folded into it, because
that revision has already been applied to developer databases: editing an
applied migration leaves two databases claiming the same revision with
different schemas, which is the failure mode a migration chain exists to
prevent.

## Why the state lives here and not in the broker

FR-044b requires a running job to report its state. A Celery task's state is
in Redis, which does not survive a broker restart and is not queryable by
tenant -- so an operator refreshing a job after a restart would be told it does
not exist. The row is the answer; the task is only the thing that fills it in
(research.md D4).

## The constraints, and what each refuses

* **A failure always has a reason.** ``state = 'failed'`` with a null
  ``error_text`` is a job that stopped without saying why, which is precisely
  the "appears to hang" outcome FR-044b forbids.
* **The floor is a percentage.** A margin floor outside [-100, 100] would
  report either every product or none, and either way an operator would read
  the result as a finding.

## Nothing here is authoritative

``result_json`` holds costs and margins, and not one of them is a figure the
system uses for anything (FR-044d). The run is a hypothetical, and it records
the shock and the inputs it ran against so that a result read a fortnight
later cannot be mistaken for a current report (FR-044c).

## The downgrade

``downgrade()`` drops the table, discarding every scenario an operator has
run. No priced figure is affected: a scenario never wrote one. What is lost is
the history of questions asked -- including the shock and inputs behind a
result somebody may have acted on, which is why this is reversible but not
lossless.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "pricing_tier4b_v1"
down_revision = "pricing_tier4_v1"
branch_labels = None
depends_on = None

TABLE = "scenario_runs"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _enable_rls(table: str) -> None:
    """Tenant isolation at the database layer, as Constitution I requires.

    A no-op outside PostgreSQL: the test suite runs on SQLite, where RLS does
    not exist, and failing hard there would make the migration untestable
    rather than safe.
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
    if _is_postgres():
        return sa.text("gen_random_uuid()")
    return None


def _json_type():
    """``JSONB`` on PostgreSQL, portable ``JSON`` on SQLite."""
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
        sa.Column(
            "requested_by_user_id",
            uuid_type,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            comment=(
                "Who asked. Nullable because a run may come from a schedule, "
                "and a scheduled run with a fabricated author is worse than one "
                "with none"
            ),
        ),
        sa.Column(
            "shock_json",
            _json_type(),
            nullable=False,
            comment="The overrides applied, as decimal strings (FR-044c)",
        ),
        sa.Column(
            "inputs_json",
            _json_type(),
            nullable=True,
            comment=(
                "The figures the run was applied to -- labor rate, margin "
                "basis, reference date. A shock is only interpretable against "
                "these (FR-044c)"
            ),
        ),
        sa.Column(
            "margin_floor_pct",
            sa.Numeric(6, 2),
            nullable=False,
            comment="The operator's judgement of what is worth selling (FR-044)",
        ),
        sa.Column("state", sa.String(20), nullable=False, server_default="queued"),
        sa.Column(
            "result_json",
            _json_type(),
            nullable=True,
            comment=("What the sweep found. Holds no authoritative cost or price (FR-044d)"),
        ),
        sa.Column(
            "error_text",
            sa.Text,
            nullable=True,
            comment="Why a run stopped, in words an operator can act on (FR-044b)",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_scenario_run_state",
        ),
        sa.CheckConstraint(
            "state <> 'failed' OR error_text IS NOT NULL",
            name="ck_scenario_run_failure_has_a_reason",
        ),
        sa.CheckConstraint(
            "margin_floor_pct >= -100 AND margin_floor_pct <= 100",
            name="ck_scenario_run_floor_is_a_percentage",
        ),
        comment=(
            "Requested catalogue-wide shocks: the question, its state and what "
            "it found. Authoritative of nothing (FR-044d)"
        ),
    )

    op.create_index(f"ix_{TABLE}_tenant_id", TABLE, ["tenant_id"])
    op.create_index(f"ix_{TABLE}_state", TABLE, ["state"])
    # The read the history screen does: this tenant's runs, newest first.
    op.create_index("idx_scenario_runs_tenant_created", TABLE, ["tenant_id", "created_at"])

    _enable_rls(TABLE)


def downgrade() -> None:
    """Drop the table, discarding every scenario an operator has run.

    No priced figure moves: a scenario never wrote one. What goes is the record
    of which questions were asked and what the answers rested on.
    """
    _disable_rls(TABLE)
    op.drop_index("idx_scenario_runs_tenant_created", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_state", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_tenant_id", table_name=TABLE)
    op.drop_table(TABLE)
