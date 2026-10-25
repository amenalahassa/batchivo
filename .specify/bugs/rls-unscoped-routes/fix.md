# Bug Fix: Row-level security cannot be switched on

- **Slug**: rls-unscoped-routes
- **Fixed**: 2026-10-25 (second pass; the first pass stopped without changes)
- **Assessment**: ./assessment.md (re-assessed for option a)
- **Status**: applied (the manifest flag is not flipped; see Follow-ups)

## Summary

The application now runs correctly as `app_user` with RLS on, proven by a new suite that drives it
against a database built from migrations. Every request session is scoped by the dependency that
validates its tenant. `user_tenants` admits a user's own memberships through
`app.current_user_id` (option a). The scope survives commits and rollbacks. Cross-tenant work uses
a real bypass. `NOT_YET_SCOPED` is gone.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/core/rls.py` | added | `set_rls_context(session, tenant_id=, user_id=)`; a `Session` `after_begin` listener re-applies it to every transaction; no-op with RLS off |
| `backend/alembic/versions/20261025_user_tenants_member_policy.py` | added | revision `user_tenants_member_policy_v1`: SELECT admits `tenant_id = current tenant OR user_id = app.current_user_id`; writes stay tenant-only |
| `backend/app/database.py` | modified | `privileged_session_maker()` on `DATABASE_URL`; `scope_session_to_tenant` delegates to `set_rls_context` |
| `backend/app/auth/dependencies.py` | modified | `get_current_user` sets the user; `get_current_tenant` sets the validated tenant (and before an auto-created membership); `get_tenant_db` **is** the request session after `get_current_tenant` (no second session, no raw header); `get_platform_admin_db` uses the privileged connection; `get_shop_tenant`, `get_shop_db` and `get_shop_sales_channel` scope through the mechanism |
| `backend/app/auth/customer_dependencies.py` | modified | customer lookups scoped from the signed token's tenant; `get_customer_db` uses the mechanism |
| `backend/app/api/v1/auth.py` | modified | login sets the user before reading memberships; register sets the tenant (it is disabled in code, but is now correct) |
| `backend/app/api/v1/customer_auth.py` | modified | refresh scopes from the token's tenant |
| `backend/app/services/onboarding_service.py` | modified | `verify_email` scopes to the new tenant before modules, policy and membership |
| `backend/app/tasks/margin_alerts.py`, `telemetry.py` | modified | each tenant in a sweep is scoped before its work |
| `backend/app/tasks/scenario.py`, `backend/app/api/v1/printer_ws.py` | modified | scoped to their known tenant |
| `backend/app/tasks/power.py` | modified | finds the printer's tenant on the privileged connection, then works scoped |
| `backend/tests/integration/test_rls_pricing.py` | modified | "scoped" means resolving a dependency that scopes the request session, or taking a separately scoped session; `NOT_YET_SCOPED` deleted (96 entries scoped, 24 moved to `UNSCOPED_ROUTES_BY_DESIGN` with reasons); new staleness checks; source checks follow the new mechanism |
| `backend/tests/integration/test_rls_enforced.py` | added test | the application as `app_user` with RLS on |

## Tests Added or Updated

`tests/integration/test_rls_enforced.py` (PostgreSQL; database built by `alembic upgrade head`):

- The connection is really filtered: an unscoped `app_user` session sees 0 categories while the
  owner sees 2, so nothing below can pass vacuously.
- The scope survives a commit and a rollback.
- Option (a): a user sees their own memberships and nobody else's; inserting yourself into another
  tenant fails the policy.
- Login, then `/users/me`.
- A `get_db` route (`GET /categories`) shows only its own tenant.
- A role-guarded write (`POST /categories`) lands in the right tenant.
- A `TenantDB` route (`GET /settings/pricing-policy`) works.
- `X-Tenant-ID` naming another tenant: 403.
- Email-verification signup creates a tenant and its membership.
- The platform admin sees every tenant.
- The storefront (`GET /shop/categories`, which has no tenant filter of its own) shows only its
  own shop's categories.
- Only `auth/dependencies.py` and `tasks/power.py` use the privileged connection.

`tests/integration/test_rls_pricing.py`: the derived population now has no escape hatch. Every
route is scoped or named by design, exceptions must be live and genuinely unscoped, and no pricing
route may be excused.

## Local Verification

- `pytest tests/integration/test_rls_enforced.py` on the test PostgreSQL: 14 passed.
- `pytest tests/integration/test_rls_pricing.py`: 490 passed, 51 skipped.
- Full CI-equivalent run: see `../FIX-RUN.md`.

## Deviations from Assessment

- **Most of the 120 routes needed no code change.** Once `get_current_tenant` scopes the shared
  request session, the 96 routes that resolve `CurrentTenant` (or a guard built on it) are under
  RLS without being edited. The remaining 24 touch no tenant table (static lists, SpoolmanDB
  reference data, Redis carts, carrier quotes, Square calls, the user's own record), so they are
  named by design. No route was swapped one by one.
- **`/auth/register` is disabled in code** (`auth.py:51`), so the suite tests the live signup path,
  email verification, instead.

## Side findings (not fixed here)

- **`tenants.settings` is `json` in a database built from migrations**
  (`9521683a2066_initial_schema…`, `sa.JSON()`), but `jsonb` in the model. The shop resolver calls
  `jsonb_extract_path_text`, so on such a database every storefront hostname lookup fails. The new
  suite converts the column in its scratch database and says why. Worth its own
  `/speckit-bug-assess`: an idempotent `ALTER … TYPE jsonb USING settings::jsonb` migration would
  close it. Production's column type should be checked first.
- **`GET /shop/categories` has no tenant filter** and relies on RLS alone. With RLS off, as in
  production today, it would list every tenant's categories. Production is single-tenant, so there
  is no exposure today, but it should either filter by `shop_tenant` or wait for RLS to be on.

## Follow-ups

- **Switching the flag on** (`infrastructure/k8s/backend/deployment.yaml:40`) is a deployment
  decision, deliberately left out of this change. It needs, in order:
  1. this change deployed with RLS still off (the context calls are no-ops);
  2. the `rls-credentials` secret in the cluster with `RLS_DATABASE_URL` for `app_user` and a real
     password (`ALTER ROLE app_user WITH PASSWORD …`). This could not be checked from here;
  3. `RLS_ENABLED: "true"`, pushed through git and synced by ArgoCD.
- The commerce bridge (`app/commerce_bridge.py` and its siblings) runs its own engine and role
  checks. Review it before step 3.
- Correct `CLAUDE.md`, which claims RLS is on in production.
