"""Ideas: product ideas, their brainstorming timeline, and source_idea_id (feature 007).

Creates ``ideas`` and ``idea_entries`` (tenant-scoped, row-level security), and a
nullable ``source_idea_id`` on ``models`` and ``products`` so a record shows the
idea it was converted from. No existing row changes: every new column is
nullable or defaulted.

Revision ID: ideas_v1
Revises: catalogue_columns_v1
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ideas_v1"
down_revision = "catalogue_columns_v1"
branch_labels = None
depends_on = None

NEW_TABLES = ("ideas", "idea_entries")
TENANT_MATCHES = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
IDEA_STATUSES = "'inbox', 'exploring', 'validating', 'ready', 'converted', 'parked', 'dropped'"
IDEA_SOURCES = "'manual', 'pain_point_report', 'customer', 'other'"
ENTRY_KINDS = "'note', 'image', 'link', 'sketch', 'measurement', 'decision', 'generation'"
SCORE_FIELDS = (
    "score_frequency",
    "score_frustration",
    "score_printability",
    "score_gap",
    "score_willingness_to_pay",
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


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    json_type = postgresql.JSONB() if is_pg else sa.JSON()

    op.create_table(
        "ideas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="inbox"),
        sa.Column("source", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("tags", json_type, nullable=False, server_default=sa.text("'[]'")),
        *(sa.Column(f, sa.SmallInteger(), nullable=True) for f in SCORE_FIELDS),
        sa.Column("report_score", sa.SmallInteger(), nullable=True),
        sa.Column("current_iteration", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cover_entry_id", sa.Uuid(), nullable=True),
        sa.Column(
            "converted_model_id",
            sa.Uuid(),
            sa.ForeignKey("models.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "converted_product_id",
            sa.Uuid(),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "was_converted_to_model", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "was_converted_to_product", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("length(trim(title)) BETWEEN 1 AND 200", name="ck_ideas_title"),
        sa.CheckConstraint(f"status IN ({IDEA_STATUSES})", name="ck_ideas_status"),
        sa.CheckConstraint(f"source IN ({IDEA_SOURCES})", name="ck_ideas_source"),
        *(
            sa.CheckConstraint(f"{f} IS NULL OR {f} BETWEEN 1 AND 5", name=f"ck_ideas_{f}")
            for f in SCORE_FIELDS
        ),
        sa.CheckConstraint(
            "report_score IS NULL OR report_score BETWEEN 0 AND 25", name="ck_ideas_report_score"
        ),
        sa.CheckConstraint("current_iteration >= 1", name="ck_ideas_current_iteration"),
    )
    op.create_index("ix_ideas_tenant_id", "ideas", ["tenant_id"])
    op.create_index(
        "ix_ideas_tenant_status_updated", "ideas", ["tenant_id", "status", "updated_at"]
    )
    op.create_index("ix_ideas_converted_model_id", "ideas", ["converted_model_id"])
    op.create_index("ix_ideas_converted_product_id", "ideas", ["converted_product_id"])
    op.create_index(
        "uq_ideas_report_source",
        "ideas",
        ["tenant_id", "source_url"],
        unique=True,
        postgresql_where=sa.text("source = 'pain_point_report' AND source_url IS NOT NULL"),
        sqlite_where=sa.text("source = 'pain_point_report' AND source_url IS NOT NULL"),
    )
    if is_pg:
        op.create_index("ix_ideas_tags", "ideas", ["tags"], postgresql_using="gin")

    op.create_table(
        "idea_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "idea_id",
            sa.Uuid(),
            sa.ForeignKey("ideas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(500), nullable=True),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("content_type", sa.String(50), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("link_url", sa.String(2048), nullable=True),
        # The foreign key to generation_jobs is added by feature 008, which creates that table.
        sa.Column("generation_job_id", sa.Uuid(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "author_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(f"kind IN ({ENTRY_KINDS})", name="ck_idea_entries_kind"),
        sa.CheckConstraint(
            "kind NOT IN ('image', 'sketch') OR image_url IS NOT NULL",
            name="ck_idea_entries_image",
        ),
        sa.CheckConstraint("kind <> 'link' OR link_url IS NOT NULL", name="ck_idea_entries_link"),
        sa.CheckConstraint(
            "kind NOT IN ('note', 'measurement', 'decision') OR "
            "(body IS NOT NULL AND length(trim(body)) > 0)",
            name="ck_idea_entries_text",
        ),
        sa.CheckConstraint("iteration >= 1", name="ck_idea_entries_iteration"),
    )
    op.create_index("ix_idea_entries_tenant_id", "idea_entries", ["tenant_id"])
    op.create_index("ix_idea_entries_idea_id", "idea_entries", ["idea_id"])
    op.create_index(
        "ix_idea_entries_idea_iteration", "idea_entries", ["idea_id", "iteration", "created_at"]
    )

    with op.batch_alter_table("ideas") as batch:
        batch.create_foreign_key(
            "fk_ideas_cover_entry_id",
            "idea_entries",
            ["cover_entry_id"],
            ["id"],
            ondelete="SET NULL",
        )

    for table in ("models", "products"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("source_idea_id", sa.Uuid(), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_source_idea_id",
                "ideas",
                ["source_idea_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index(f"ix_{table}_source_idea_id", ["source_idea_id"])

    if is_pg:
        for table in NEW_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                f"USING ({TENANT_MATCHES}) WITH CHECK ({TENANT_MATCHES})"
            )


def downgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    if is_pg:
        for table in NEW_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    for table in ("products", "models"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_source_idea_id")
            batch.drop_constraint(f"fk_{table}_source_idea_id", type_="foreignkey")
            batch.drop_column("source_idea_id")
    with op.batch_alter_table("ideas") as batch:
        batch.drop_constraint("fk_ideas_cover_entry_id", type_="foreignkey")
    op.drop_table("idea_entries")
    op.drop_table("ideas")
