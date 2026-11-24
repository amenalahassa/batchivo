"""Print sends to Bambu printers and the Developer Mode flag.

Revision ID: print_sends_v1
Revises: catalogue_columns_v1
Create Date: 2026-11-23

Spec 011 (data-model.md).

- `printer_connections.developer_mode` (default false): no existing printer
  becomes able to receive prints until the operator says it is in Developer
  Mode.
- `print_sends`: a prepared send, its confirmation, outcome and spool
  deduction proposal. Tenant-scoped with row-level security (four policies,
  FORCE), like every tenant table.

No existing row changes value. Downgrade drops the table and the column.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "print_sends_v1"
down_revision = "catalogue_columns_v1"
branch_labels = None
depends_on = None

_TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column(
        "printer_connections",
        sa.Column(
            "developer_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="Operator-declared Bambu Developer Mode (enables print send, disables cloud)",
        ),
    )

    op.create_table(
        "print_sends",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            comment="Tenant ID for multi-tenant isolation",
        ),
        sa.Column(
            "printer_id",
            sa.UUID(),
            sa.ForeignKey("printers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prepared_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "model_id", sa.UUID(), sa.ForeignKey("models.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "model_file_id",
            sa.UUID(),
            sa.ForeignKey("model_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("upload_url", sa.String(500), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("file_md5", sa.String(32), nullable=False),
        sa.Column("remote_file_name", sa.String(255), nullable=False),
        sa.Column("plate_index", sa.Integer(), nullable=False),
        sa.Column("ams_mapping", postgresql.JSONB(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "warnings_acknowledged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "print_job_id",
            sa.UUID(),
            sa.ForeignKey("print_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("printer_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumption_status", sa.String(20), nullable=False, server_default="none"),
        sa.Column("consumption_lines", postgresql.JSONB(), nullable=True),
        sa.Column("consumption_decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "consumption_decided_by_user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("token_hash", name="uq_print_sends_token_hash"),
        sa.UniqueConstraint("print_job_id", name="uq_print_sends_print_job_id"),
        sa.CheckConstraint("plate_index >= 1", name="ck_print_sends_plate_index"),
        sa.CheckConstraint(
            "status IN ('prepared','confirming','started','transfer_failed','start_failed')",
            name="ck_print_sends_status",
        ),
        sa.CheckConstraint(
            "consumption_status IN ('none','pending','accepted','dismissed')",
            name="ck_print_sends_consumption_status",
        ),
        comment="Print sends to Bambu printers: prepare, confirmation, outcome (spec 011)",
    )
    op.create_index("ix_print_sends_tenant_id", "print_sends", ["tenant_id"])
    op.create_index("ix_print_sends_printer_id", "print_sends", ["printer_id"])
    op.create_index("ix_print_sends_status", "print_sends", ["status"])
    op.create_index(
        "ix_print_sends_tenant_printer_created",
        "print_sends",
        ["tenant_id", "printer_id", "created_at"],
    )
    op.create_index("ix_print_sends_printer_status", "print_sends", ["printer_id", "status"])

    op.execute(sa.text("ALTER TABLE print_sends ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE print_sends FORCE ROW LEVEL SECURITY"))
    for action, clause in (
        ("select", f"FOR SELECT USING ({_TENANT})"),
        ("insert", f"FOR INSERT WITH CHECK ({_TENANT})"),
        ("update", f"FOR UPDATE USING ({_TENANT})"),
        ("delete", f"FOR DELETE USING ({_TENANT})"),
    ):
        op.execute(sa.text(f"CREATE POLICY tenant_isolation_{action} ON print_sends {clause}"))


def downgrade() -> None:
    for action in ("select", "insert", "update", "delete"):
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{action} ON print_sends"))
    op.drop_index("ix_print_sends_printer_status", table_name="print_sends")
    op.drop_index("ix_print_sends_tenant_printer_created", table_name="print_sends")
    op.drop_index("ix_print_sends_status", table_name="print_sends")
    op.drop_index("ix_print_sends_printer_id", table_name="print_sends")
    op.drop_index("ix_print_sends_tenant_id", table_name="print_sends")
    op.drop_table("print_sends")
    op.drop_column("printer_connections", "developer_mode")
