"""Model file versions and pinned notes.

Revision ID: model_file_versions_v1
Revises: packaging_advisor_v2
Create Date: 2026-11-03

Groups every model file into a version (spec 004, research D1). Each model that
already has files gets version "1", active, holding all of them; its print file
is the primary sliced file, else the newest sliced file. Nothing the cost engine
reads is written -- no model, printer-config, material, dimension or provenance
row -- so every model costs exactly what it did (FR-016, SC-004).

`is_sliced` is backfilled from the file name and type only: a migration does not
read file contents from storage. A sliced plate uploaded under another name stays
`false` until it is uploaded again, which only affects the wording of its
"cannot be measured" message.

Both new tables get the same isolation as every tenant table: RLS enabled and
forced, one policy on `app.current_tenant_id`.
"""

import sqlalchemy as sa
from alembic import op

revision = "model_file_versions_v1"
down_revision = "packaging_advisor_v2"
branch_labels = None
depends_on = None

NEW_TABLES = ("model_file_versions", "model_file_notes")
TENANT_MATCHES = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "model_file_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "model_id", sa.Uuid(), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("print_file_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_model_file_versions_sequence_positive"),
        sa.CheckConstraint(
            "length(label) BETWEEN 1 AND 50", name="ck_model_file_versions_label_length"
        ),
    )
    op.create_index("ix_model_file_versions_tenant_id", "model_file_versions", ["tenant_id"])
    op.create_index("ix_model_file_versions_model_id", "model_file_versions", ["model_id"])
    op.create_index(
        "uq_model_file_versions_model_sequence",
        "model_file_versions",
        ["model_id", "sequence"],
        unique=True,
    )
    op.create_index(
        "uq_model_file_versions_one_active",
        "model_file_versions",
        ["model_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.add_column("model_files", sa.Column("version_id", sa.Uuid(), nullable=True))
    op.add_column(
        "model_files",
        sa.Column("is_sliced", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("model_files", sa.Column("measurement_reason", sa.String(40), nullable=True))
    op.create_foreign_key(
        "fk_model_files_version_id",
        "model_files",
        "model_file_versions",
        ["version_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_model_files_version_id", "model_files", ["version_id"])
    op.create_foreign_key(
        "fk_model_file_versions_print_file_id",
        "model_file_versions",
        "model_files",
        ["print_file_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # -- backfill -------------------------------------------------------------
    op.execute(
        """
        UPDATE model_files
        SET is_sliced = true
        WHERE lower(original_filename) LIKE '%.gcode'
           OR lower(original_filename) LIKE '%.gcode.3mf'
           OR file_type = 'gcode'
        """
    )
    op.execute(
        """
        INSERT INTO model_file_versions (id, tenant_id, model_id, sequence, label, is_active,
                                         created_at, updated_at)
        SELECT gen_random_uuid(), m.tenant_id, m.id, 1, '1', true,
               min(f.uploaded_at), now()
        FROM models m
        JOIN model_files f ON f.model_id = m.id
        GROUP BY m.tenant_id, m.id
        """
    )
    op.execute(
        """
        UPDATE model_files f
        SET version_id = v.id, version = '1'
        FROM model_file_versions v
        WHERE v.model_id = f.model_id
        """
    )
    op.execute(
        """
        UPDATE model_file_versions v
        SET print_file_id = (
            SELECT f.id FROM model_files f
            WHERE f.version_id = v.id AND f.is_sliced
            ORDER BY f.is_primary DESC, f.uploaded_at DESC
            LIMIT 1
        )
        """
    )
    op.alter_column("model_files", "version_id", nullable=False)

    op.create_table(
        "model_file_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "model_id", sa.Uuid(), sa.ForeignKey("models.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "version_id",
            sa.Uuid(),
            sa.ForeignKey("model_file_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_file_id",
            sa.Uuid(),
            sa.ForeignKey("model_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("pos_x", sa.Float(), nullable=False),
        sa.Column("pos_y", sa.Float(), nullable=False),
        sa.Column("pos_z", sa.Float(), nullable=False),
        sa.Column("normal_x", sa.Float(), nullable=False),
        sa.Column("normal_y", sa.Float(), nullable=False),
        sa.Column("normal_z", sa.Float(), nullable=False),
        sa.Column("layer", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column(
            "resolved_in_version_id",
            sa.Uuid(),
            sa.ForeignKey("model_file_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "carried_to_version_id",
            sa.Uuid(),
            sa.ForeignKey("model_file_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "carried_from_note_id",
            sa.Uuid(),
            sa.ForeignKey("model_file_notes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "author_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'carried_forward')", name="ck_model_file_notes_status"
        ),
        sa.CheckConstraint("layer IS NULL OR layer >= 0", name="ck_model_file_notes_layer"),
        sa.CheckConstraint(
            "length(text) BETWEEN 1 AND 2000", name="ck_model_file_notes_text_length"
        ),
        sa.CheckConstraint(
            "status <> 'resolved' OR resolved_in_version_id IS NOT NULL",
            name="ck_model_file_notes_resolved_version",
        ),
        sa.CheckConstraint(
            "status <> 'carried_forward' OR carried_to_version_id IS NOT NULL",
            name="ck_model_file_notes_carried_version",
        ),
    )
    for column in ("tenant_id", "model_id", "version_id", "model_file_id"):
        op.create_index(f"ix_model_file_notes_{column}", "model_file_notes", [column])

    if op.get_bind().dialect.name == "postgresql":
        for table in NEW_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_tenant_isolation ON {table} "
                f"USING ({TENANT_MATCHES}) WITH CHECK ({TENANT_MATCHES})"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in NEW_TABLES:
            op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.drop_table("model_file_notes")
    op.drop_constraint(
        "fk_model_file_versions_print_file_id", "model_file_versions", type_="foreignkey"
    )
    op.drop_index("ix_model_files_version_id", table_name="model_files")
    op.drop_constraint("fk_model_files_version_id", "model_files", type_="foreignkey")
    op.drop_column("model_files", "measurement_reason")
    op.drop_column("model_files", "is_sliced")
    op.drop_column("model_files", "version_id")
    op.drop_table("model_file_versions")
