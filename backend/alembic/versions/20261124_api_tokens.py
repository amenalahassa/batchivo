"""Personal API tokens.

Revision ID: api_tokens_v1
Revises: print_sends_v1
Create Date: 2026-11-24

Spec 010 (data-model.md). `api_tokens`: one hashed, scoped, expiring token per
row, bound to a user and a tenant. Tenant-scoped with row-level security (four
policies, FORCE). SELECT and UPDATE also admit the one row whose hash the
request proved it knows (`app.current_api_token_hash`), so a token can be found
before any tenant is set without a privileged session (research R4). The
application query filters by the exact hash too: RLS is the second belt.

No existing row changes. Downgrade drops the table.
"""

import sqlalchemy as sa
from alembic import op

revision = "api_tokens_v1"
down_revision = "print_sends_v1"
branch_labels = None
depends_on = None

_TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
_HASH = "token_hash = NULLIF(current_setting('app.current_api_token_hash', true), '')"


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.UUID(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(trim(name)) BETWEEN 1 AND 100", name="ck_api_tokens_name_length"
        ),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
    )
    op.create_index("ix_api_tokens_tenant_id", "api_tokens", ["tenant_id"])
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_index(
        "ix_api_tokens_tenant_user", "api_tokens", ["tenant_id", "user_id", "created_at"]
    )

    op.execute(sa.text("ALTER TABLE api_tokens ENABLE ROW LEVEL SECURITY"))
    op.execute(sa.text("ALTER TABLE api_tokens FORCE ROW LEVEL SECURITY"))
    for action, clause in (
        ("select", f"FOR SELECT USING ({_TENANT} OR {_HASH})"),
        ("insert", f"FOR INSERT WITH CHECK ({_TENANT})"),
        ("update", f"FOR UPDATE USING ({_TENANT} OR {_HASH})"),
        ("delete", f"FOR DELETE USING ({_TENANT})"),
    ):
        op.execute(sa.text(f"CREATE POLICY tenant_isolation_{action} ON api_tokens {clause}"))


def downgrade() -> None:
    for action in ("select", "insert", "update", "delete"):
        op.execute(sa.text(f"DROP POLICY IF EXISTS tenant_isolation_{action} ON api_tokens"))
    op.drop_index("ix_api_tokens_tenant_user", table_name="api_tokens")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_index("ix_api_tokens_tenant_id", table_name="api_tokens")
    op.drop_table("api_tokens")
