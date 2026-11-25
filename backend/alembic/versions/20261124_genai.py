"""Generative AI: generation jobs, stored assets, adoptions, product image origin (feature 008).

Creates ``generation_jobs``, ``genai_assets`` and ``genai_adoptions`` (tenant-scoped,
row-level security), adds ``product_images.origin`` (default ``photo``, so every
existing image reads as a photo) and the foreign key that 007 reserved on
``idea_entries.generation_job_id``. No existing row changes value, except that an
``idea_entries.generation_job_id`` pointing at no job (any value before 008, since no
job could exist) is cleared to NULL so the foreign key can be created; the entry is kept.

Revision ID: genai_v1
Revises: printer_serial_v1
Create Date: 2026-11-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "genai_v1"
down_revision = "printer_serial_v1"
branch_labels = None
depends_on = None

NEW_TABLES = ("generation_jobs", "genai_assets", "genai_adoptions")
TENANT_MATCHES = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
CAPABILITIES = (
    "'concept_image', 'image_edit', 'product_photo_enhance', 'background_remove', "
    "'upscale', 'lifestyle_scene', 'image_to_3d'"
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


def upgrade() -> None:
    is_pg = op.get_bind().dialect.name == "postgresql"
    json_type = postgresql.JSONB() if is_pg else sa.JSON()
    money = sa.Numeric(12, 4)

    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant(),
        sa.Column("capability", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model_ref", sa.String(200), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("model_version_ran", sa.String(100), nullable=True),
        sa.Column("inputs", json_type, nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("target_type", sa.String(10), nullable=False, server_default="none"),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("estimated_cost", money, nullable=False, server_default="0"),
        sa.Column("cost", money, nullable=True),
        sa.Column("cost_provenance", sa.String(12), nullable=True),
        sa.Column("price_snapshot", json_type, nullable=False),
        sa.Column("shows_real_item", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("poll_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_files", json_type, nullable=True),
        _user("requested_by_user_id"),
        *_timestamps(),
        sa.CheckConstraint(f"capability IN ({CAPABILITIES})", name="ck_generation_jobs_capability"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'canceled')",
            name="ck_generation_jobs_status",
        ),
        sa.CheckConstraint(
            "target_type IN ('idea', 'product', 'model', 'none')", name="ck_generation_jobs_target"
        ),
        sa.CheckConstraint(
            "(target_type = 'none') = (target_id IS NULL)", name="ck_generation_jobs_target_id"
        ),
        sa.CheckConstraint(
            "cost_provenance IS NULL OR cost_provenance IN ('computed', 'estimated')",
            name="ck_generation_jobs_cost_provenance",
        ),
        sa.CheckConstraint("estimated_cost >= 0", name="ck_generation_jobs_estimate_positive"),
        sa.CheckConstraint("cost IS NULL OR cost >= 0", name="ck_generation_jobs_cost_positive"),
    )
    op.create_index("ix_generation_jobs_tenant_id", "generation_jobs", ["tenant_id"])
    op.create_index("ix_generation_jobs_status", "generation_jobs", ["status"])
    op.create_index("ix_generation_jobs_external_id", "generation_jobs", ["external_id"])
    op.create_index(
        "ix_generation_jobs_target",
        "generation_jobs",
        ["tenant_id", "target_type", "target_id", "created_at"],
    )
    op.create_index("ix_generation_jobs_tenant_status", "generation_jobs", ["tenant_id", "status"])
    op.create_index(
        "ix_generation_jobs_tenant_created", "generation_jobs", ["tenant_id", "created_at"]
    )

    op.create_table(
        "genai_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant(),
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("generation_jobs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("storage_url", sa.String(500), nullable=False),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("content_type", sa.String(80), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shows_real_item", sa.Boolean(), nullable=False, server_default=sa.true()),
        _user("created_by_user_id"),
        *_timestamps(),
        sa.CheckConstraint("source IN ('output', 'upload')", name="ck_genai_assets_source"),
        sa.CheckConstraint("kind IN ('image', 'mesh')", name="ck_genai_assets_kind"),
        sa.CheckConstraint(
            "(source = 'output') = (job_id IS NOT NULL)", name="ck_genai_assets_job"
        ),
        sa.CheckConstraint(
            "source <> 'output' OR ai_generated", name="ck_genai_assets_ai_generated"
        ),
    )
    op.create_index("ix_genai_assets_tenant_id", "genai_assets", ["tenant_id"])
    op.create_index("ix_genai_assets_job_id", "genai_assets", ["job_id"])

    op.create_table(
        "genai_adoptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant(),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("genai_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_type", sa.String(10), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "idea_entry_id",
            sa.Uuid(),
            sa.ForeignKey("idea_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "product_image_id",
            sa.Uuid(),
            sa.ForeignKey("product_images.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "model_file_id",
            sa.Uuid(),
            sa.ForeignKey("model_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("warning_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        _user("adopted_by_user_id"),
        *_timestamps(),
        sa.CheckConstraint(
            "owner_type IN ('idea', 'product', 'model')", name="ck_genai_adoptions_owner"
        ),
        sa.CheckConstraint(
            "(CASE WHEN idea_entry_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN product_image_id IS NULL THEN 0 ELSE 1 END"
            " + CASE WHEN model_file_id IS NULL THEN 0 ELSE 1 END) <= 1",
            name="ck_genai_adoptions_one_result",
        ),
        sa.UniqueConstraint("asset_id", "owner_type", "owner_id", name="uq_genai_adoptions_target"),
    )
    op.create_index("ix_genai_adoptions_tenant_id", "genai_adoptions", ["tenant_id"])
    op.create_index("ix_genai_adoptions_asset_id", "genai_adoptions", ["asset_id"])
    op.create_index(
        "ix_genai_adoptions_owner", "genai_adoptions", ["tenant_id", "owner_type", "owner_id"]
    )

    with op.batch_alter_table("product_images") as batch:
        batch.add_column(sa.Column("origin", sa.String(10), nullable=False, server_default="photo"))
        batch.create_check_constraint(
            "ck_product_images_origin", "origin IN ('photo', 'render', 'ai')"
        )

    # Before 008 no job could exist, so any id already in the column points at nothing:
    # clear it, or the foreign key cannot be created (the entry itself is kept).
    op.execute(
        "UPDATE idea_entries SET generation_job_id = NULL WHERE generation_job_id IS NOT NULL "
        "AND generation_job_id NOT IN (SELECT id FROM generation_jobs)"
    )
    with op.batch_alter_table("idea_entries") as batch:
        batch.create_foreign_key(
            "fk_idea_entries_generation_job_id",
            "generation_jobs",
            ["generation_job_id"],
            ["id"],
            ondelete="SET NULL",
        )

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
    with op.batch_alter_table("idea_entries") as batch:
        batch.drop_constraint("fk_idea_entries_generation_job_id", type_="foreignkey")
    with op.batch_alter_table("product_images") as batch:
        batch.drop_constraint("ck_product_images_origin", type_="check")
        batch.drop_column("origin")
    op.drop_table("genai_adoptions")
    op.drop_table("genai_assets")
    op.drop_table("generation_jobs")
