"""Let a user read their own memberships before a tenant is chosen.

Revision ID: user_tenants_member_policy_v1
Revises: rls_uncovered_tenant_tables_v1

Bug rls-unscoped-routes, option (a). Resolving which tenant a request acts for
means reading the user's rows in `user_tenants` across every tenant they
belong to -- before any tenant is set, so the tenant-only policy from
`8c3c671816d9` hid them all and no authenticated request could succeed with RLS
on. The SELECT policy now also admits a row whose `user_id` matches
`app.current_user_id`, which `get_current_user` sets once the token is verified.

Only reading widens. INSERT, UPDATE and DELETE stay tenant-only, so a user can
never write themselves into another tenant.
"""

from alembic import op

revision = "user_tenants_member_policy_v1"
down_revision = "rls_uncovered_tenant_tables_v1"
branch_labels = None
depends_on = None

TENANT = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
USER = "user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS tenant_isolation_select ON user_tenants")
    op.execute(
        f"CREATE POLICY tenant_isolation_select ON user_tenants "
        f"FOR SELECT USING ({TENANT} OR {USER})"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS tenant_isolation_select ON user_tenants")
    op.execute(f"CREATE POLICY tenant_isolation_select ON user_tenants FOR SELECT USING ({TENANT})")
