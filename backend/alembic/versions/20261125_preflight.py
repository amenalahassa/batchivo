"""Preflight foundations: design briefs, typed notes, calibrations, test results, secrets (009).

Creates ``design_briefs``, ``design_brief_revisions``, ``print_test_results`` and
``calibrations`` (tenant-scoped, row-level security; revisions and calibrations
guarded by immutability triggers). Adds typed-note columns to ``model_file_notes``
(``source`` defaults to ``person`` and ``severity`` to ``info``, so every existing
note reads as before) and the ``dismissed`` status. Widens
``printer_connections.access_code`` to text and encrypts every stored access code
and cloud token in place (idempotent: values already encrypted are left alone);
the downgrade decrypts them. No computed value changes.

The data step uses ``app.core.encryption``, keyed by the application's
``SECRET_KEY``: run it with the same key as the application.

Revision ID: preflight_v1
Revises: genai_v1
Create Date: 2026-11-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "preflight_v1"
down_revision = "genai_v1"
branch_labels = None
depends_on = None

NEW_TABLES = ("design_briefs", "design_brief_revisions", "print_test_results", "calibrations")
TENANT_MATCHES = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
NIL_UUID = "00000000-0000-0000-0000-000000000000"

REVISION_TRIGGER = (
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
CALIBRATION_TRIGGER = (
    # Allowed: superseding a current value once, and ON DELETE SET NULL clearing a
    # reference (recorder, source print job, source test result) of a deleted row.
    "CREATE OR REPLACE FUNCTION calibrations_immutable() RETURNS trigger AS $$ "
    "DECLARE refs text[] := ARRAY['recorded_by_user_id', 'source_print_job_id', "
    "'source_test_result_id']; "
    "BEGIN "
    "IF (to_jsonb(NEW) - refs) = (to_jsonb(OLD) - refs) "
    "AND (NEW.recorded_by_user_id IS NULL OR NEW.recorded_by_user_id = OLD.recorded_by_user_id) "
    "AND (NEW.source_print_job_id IS NULL OR NEW.source_print_job_id = OLD.source_print_job_id) "
    "AND (NEW.source_test_result_id IS NULL "
    "OR NEW.source_test_result_id = OLD.source_test_result_id) "
    "THEN RETURN NEW; END IF; "
    "IF OLD.superseded_by_id IS NOT NULL "
    "OR (to_jsonb(NEW) - 'superseded_by_id' - 'superseded_at' - 'updated_at') "
    "<> (to_jsonb(OLD) - 'superseded_by_id' - 'superseded_at' - 'updated_at') "
    "THEN RAISE EXCEPTION 'calibrations are immutable: record a new value instead'; "
    "END IF; RETURN NEW; END; $$ LANGUAGE plpgsql",
    "CREATE TRIGGER trg_calibrations_immutable BEFORE UPDATE ON calibrations "
    "FOR EACH ROW EXECUTE FUNCTION calibrations_immutable()",
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def _tenant() -> sa.Column:
    return sa.Column(
        "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


def _fk(name: str, table: str, ondelete: str | None = "SET NULL", nullable: bool = True):
    return sa.Column(
        name, sa.Uuid(), sa.ForeignKey(f"{table}.id", ondelete=ondelete), nullable=nullable
    )


def _create_tables(json_type) -> None:
    op.create_table(
        "design_briefs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant(),
        _fk("idea_id", "ideas"),
        _fk("model_id", "models"),
        sa.Column("intent", json_type, nullable=True),
        sa.Column("intent_schema_version", sa.Integer(), nullable=True),
        sa.Column("risk_class", sa.String(10), nullable=True),
        sa.Column("risk_md", sa.Text(), nullable=True),
        sa.Column("triage", json_type, nullable=True),
        sa.Column("plan_md", sa.Text(), nullable=True),
        sa.Column("params", json_type, nullable=True),
        sa.Column("params_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("step_status", json_type, nullable=False, server_default="{}"),
        _user("created_by_user_id"),
        _user("updated_by_user_id"),
        *_timestamps(),
        sa.CheckConstraint(
            "risk_class IS NULL OR risk_class IN ('faible', 'moyen', 'élevé', 'arrêt')",
            name="ck_design_briefs_risk_class",
        ),
    )
    op.create_index("ix_design_briefs_tenant_id", "design_briefs", ["tenant_id"])
    op.create_index(
        "uq_design_briefs_idea",
        "design_briefs",
        ["idea_id"],
        unique=True,
        postgresql_where=sa.text("idea_id IS NOT NULL"),
        sqlite_where=sa.text("idea_id IS NOT NULL"),
    )
    op.create_index(
        "uq_design_briefs_model",
        "design_briefs",
        ["model_id"],
        unique=True,
        postgresql_where=sa.text("model_id IS NOT NULL"),
        sqlite_where=sa.text("model_id IS NOT NULL"),
    )

    op.create_table(
        "design_brief_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant(),
        _fk("brief_id", "design_briefs", ondelete="CASCADE", nullable=False),
        sa.Column("part", sa.String(10), nullable=False),
        sa.Column("content", json_type, nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=True),
        _user("author_user_id"),
        *_timestamps(),
        sa.CheckConstraint(
            "part IN ('intent', 'risk', 'plan')", name="ck_design_brief_revisions_part"
        ),
    )
    op.create_index("ix_design_brief_revisions_tenant_id", "design_brief_revisions", ["tenant_id"])
    op.create_index("ix_design_brief_revisions_brief_id", "design_brief_revisions", ["brief_id"])
    op.create_index(
        "ix_design_brief_revisions_brief_created",
        "design_brief_revisions",
        ["brief_id", "created_at"],
    )

    op.create_table(
        "print_test_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant(),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(8), nullable=False),
        _fk("model_id", "models"),
        _fk("model_file_version_id", "model_file_versions"),
        _fk("print_job_id", "print_jobs"),
        _fk("printer_id", "printers"),
        _fk("material_type_id", "material_types"),
        _fk("filament_type_id", "filament_types"),
        sa.Column("orientation", sa.String(12), nullable=True),
        sa.Column("measurements", json_type, nullable=False, server_default="[]"),
        sa.Column("failure_mode", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("photo_url", sa.String(500), nullable=True),
        sa.Column("photo_thumbnail_url", sa.String(500), nullable=True),
        sa.Column("photo_content_type", sa.String(50), nullable=True),
        sa.Column("photo_original_filename", sa.String(255), nullable=True),
        _user("recorded_by_user_id"),
        _user("updated_by_user_id"),
        *_timestamps(),
        sa.CheckConstraint(
            "kind IN ('clearance_grid', 'critical_zone', 'full_part')",
            name="ck_print_test_results_kind",
        ),
        sa.CheckConstraint(
            "outcome IN ('pass', 'fail', 'partial')", name="ck_print_test_results_outcome"
        ),
        sa.CheckConstraint(
            "orientation IS NULL OR orientation IN ('vertical', 'horizontal')",
            name="ck_print_test_results_orientation",
        ),
    )
    op.create_index("ix_print_test_results_tenant_id", "print_test_results", ["tenant_id"])
    op.create_index("ix_print_test_results_print_job_id", "print_test_results", ["print_job_id"])
    op.create_index(
        "ix_print_test_results_model_created",
        "print_test_results",
        ["tenant_id", "model_id", "created_at"],
    )

    op.create_table(
        "calibrations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant(),
        _fk("printer_id", "printers", ondelete="CASCADE", nullable=False),
        _fk("material_type_id", "material_types", ondelete="RESTRICT", nullable=False),
        _fk("filament_type_id", "filament_types", ondelete="CASCADE"),
        sa.Column("orientation", sa.String(12), nullable=False),
        sa.Column("fit_type", sa.String(16), nullable=False),
        sa.Column("value_mm", sa.Numeric(5, 3), nullable=False),
        sa.Column("provenance", sa.String(10), nullable=False),
        _fk("source_print_job_id", "print_jobs"),
        _fk("source_test_result_id", "print_test_results"),
        sa.Column(
            "measured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        _user("recorded_by_user_id"),
        _fk("superseded_by_id", "calibrations", ondelete=None),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "orientation IN ('vertical', 'horizontal')", name="ck_calibrations_orientation"
        ),
        sa.CheckConstraint(
            "fit_type IN ('slide', 'press', 'snap', 'print-in-place')",
            name="ck_calibrations_fit_type",
        ),
        sa.CheckConstraint(
            "provenance IN ('measured', 'assumed')", name="ck_calibrations_provenance"
        ),
        sa.CheckConstraint("value_mm >= 0 AND value_mm <= 2", name="ck_calibrations_value_range"),
    )
    op.create_index("ix_calibrations_tenant_id", "calibrations", ["tenant_id"])
    op.create_index("ix_calibrations_printer_id", "calibrations", ["printer_id"])
    op.create_index("ix_calibrations_printer_created", "calibrations", ["printer_id", "created_at"])
    op.create_index(
        "uq_calibrations_current",
        "calibrations",
        [
            "tenant_id",
            "printer_id",
            "material_type_id",
            sa.text(f"coalesce(filament_type_id, '{NIL_UUID}')"),
            "orientation",
            "fit_type",
        ],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def _extend_notes() -> None:
    with op.batch_alter_table("model_file_notes") as batch:
        batch.add_column(
            sa.Column("source", sa.String(10), nullable=False, server_default="person")
        )
        batch.add_column(sa.Column("rule_id", sa.String(100), nullable=True))
        batch.add_column(
            sa.Column("severity", sa.String(10), nullable=False, server_default="info")
        )
        batch.add_column(sa.Column("measured_value", sa.Numeric(), nullable=True))
        batch.add_column(sa.Column("expected_value", sa.Numeric(), nullable=True))
        batch.add_column(sa.Column("value_unit", sa.String(20), nullable=True))
        batch.add_column(sa.Column("dismissal_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column(
                "dismissed_by_user_id",
                sa.Uuid(),
                sa.ForeignKey(
                    "users.id", ondelete="SET NULL", name="fk_model_file_notes_dismissed_by"
                ),
                nullable=True,
            )
        )
        batch.drop_constraint("ck_model_file_notes_status", type_="check")
        batch.create_check_constraint(
            "ck_model_file_notes_status",
            "status IN ('open', 'resolved', 'carried_forward', 'dismissed')",
        )
        batch.create_check_constraint(
            "ck_model_file_notes_dismissed_reason",
            "status <> 'dismissed' OR dismissal_reason IS NOT NULL",
        )
        batch.create_check_constraint(
            "ck_model_file_notes_source", "source IN ('person', 'preflight', 'print')"
        )
        batch.create_check_constraint(
            "ck_model_file_notes_severity", "severity IN ('info', 'warning', 'failure')"
        )
    op.create_index(
        "ix_model_file_notes_model_source_severity",
        "model_file_notes",
        ["model_id", "source", "severity"],
    )


def _transform_secrets(encrypting: bool) -> None:
    """Encrypt (or decrypt) every stored access code and cloud token, row by row."""
    from app.core.encryption import encrypt_value, safe_decrypt

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, access_code, cloud_token FROM printer_connections")
    ).fetchall()
    for row_id, access_code, cloud_token in rows:
        changes = {}
        for column, value in (("access_code", access_code), ("cloud_token", cloud_token)):
            if not value:
                continue
            clear = safe_decrypt(value)
            if encrypting and clear is None:
                # Not a token this key can read: a clear value, encrypt it.
                changes[column] = encrypt_value(value)
            elif not encrypting and clear is not None:
                changes[column] = clear
        if changes:
            assignments = ", ".join(f"{column} = :{column}" for column in changes)
            bind.execute(
                sa.text(f"UPDATE printer_connections SET {assignments} WHERE id = :id"),
                {**changes, "id": row_id},
            )


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    json_type = postgresql.JSONB() if is_pg else sa.JSON()

    _create_tables(json_type)
    _extend_notes()

    with op.batch_alter_table("printer_connections") as batch:
        batch.alter_column(
            "access_code", type_=sa.Text(), existing_type=sa.String(100), existing_nullable=True
        )
    _transform_secrets(encrypting=True)

    if is_pg:
        for statement in REVISION_TRIGGER + CALIBRATION_TRIGGER:
            op.execute(statement)
        for table in NEW_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                f"USING ({TENANT_MATCHES}) WITH CHECK ({TENANT_MATCHES})"
            )


def downgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"

    _transform_secrets(encrypting=False)
    with op.batch_alter_table("printer_connections") as batch:
        batch.alter_column(
            "access_code", type_=sa.String(100), existing_type=sa.Text(), existing_nullable=True
        )

    # A dismissed note goes back to open: the previous release knows no "dismissed".
    op.execute("UPDATE model_file_notes SET status = 'open' WHERE status = 'dismissed'")
    op.drop_index("ix_model_file_notes_model_source_severity", table_name="model_file_notes")
    with op.batch_alter_table("model_file_notes") as batch:
        batch.drop_constraint("ck_model_file_notes_severity", type_="check")
        batch.drop_constraint("ck_model_file_notes_source", type_="check")
        batch.drop_constraint("ck_model_file_notes_dismissed_reason", type_="check")
        batch.drop_constraint("ck_model_file_notes_status", type_="check")
        batch.create_check_constraint(
            "ck_model_file_notes_status", "status IN ('open', 'resolved', 'carried_forward')"
        )
        batch.drop_constraint("fk_model_file_notes_dismissed_by", type_="foreignkey")
        for column in (
            "dismissed_by_user_id",
            "dismissed_at",
            "dismissal_reason",
            "value_unit",
            "expected_value",
            "measured_value",
            "severity",
            "rule_id",
            "source",
        ):
            batch.drop_column(column)

    if is_pg:
        for table in NEW_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.drop_table("calibrations")
    op.drop_table("print_test_results")
    op.drop_table("design_brief_revisions")
    op.drop_table("design_briefs")
    if is_pg:
        op.execute("DROP FUNCTION IF EXISTS calibrations_immutable()")
        op.execute("DROP FUNCTION IF EXISTS design_brief_revisions_immutable()")
