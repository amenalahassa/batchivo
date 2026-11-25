# Bug Assessment: Row-level security cannot be switched on

- **Slug**: rls-unscoped-routes
- **Created**: 2026-10-24
- **Re-assessed**: 2026-10-25, second pass, after the first fix attempt stopped (see `fix.md`)
- **Source**: side finding S2 from `/speckit-converge` on `002-pricing-engine-rebuild`, plus the
  first fix pass's findings
- **Verdict**: valid
- **Severity**: high
- **Decision taken by the user**: option (a). `user_tenants` admits a row whose `user_id` matches
  a second session setting, `app.current_user_id`.

## Report (verbatim or summarized)

> `NOT_YET_SCOPED` in `tests/integration/test_rls_pricing.py` pins about a hundred tenant routes
> still on `get_db` "with no deliberate reason", so each relies on an application-level
> `tenant_id` filter alone. Constitution I requires RLS via `get_tenant_db`.

The real goal behind the report is to switch `RLS_ENABLED` on in production
(`infrastructure/k8s/backend/deployment.yaml:40` says `"false"`) without breaking anything.

## Symptom

With `RLS_ENABLED=true` and the `app_user` connection, the policies (`tenant_id =
NULLIF(current_setting('app.current_tenant_id', true), '')::uuid`, forced on the owner) hide every
row from a session that has not set the tenant. Today that would:

1. **Break every authenticated request.** `get_current_tenant` (`dependencies.py:73`) reads
   `user_tenants` by `user_id` to find the user's tenants before any tenant is set. It sees
   nothing, then tries to auto-create a workspace whose membership insert fails the policy.
2. **Break login, registration and email verification.** They read or insert `user_tenants`
   with no tenant set (`auth.py:81,129`, `onboarding_service.py`).
3. **Make every role guard 403.** `require_member`/`require_admin` read `user_tenants` on `get_db`.
4. **Empty the 120 `NOT_YET_SCOPED` routes.** They run on `get_db`, which never sets the tenant.
5. **Empty the platform admin.** `get_platform_admin_db` "bypasses RLS" by not setting a tenant.
   Under `app_user`, that shows **no** rows, not all rows.
6. **Empty the background jobs.** `tasks/margin_alerts.py`, `tasks/telemetry.py` (sweeps over
   every tenant), `tasks/power.py`, `tasks/scenario.py` and `api/v1/printer_ws.py` open sessions
   with no tenant set.
7. **Fail transactions after a commit or rollback.** `SET LOCAL` lasts only for the current
   transaction. A handler that commits and keeps working (`get_current_tenant` itself does) loses
   the setting.

There is also a **cross-tenant read once RLS is on**. `TenantContextMiddleware`
(`middleware.py:56`) takes `X-Tenant-ID` from the request unvalidated, and `get_tenant_db` scopes
its session to it. A route that takes `TenantDB` without `CurrentTenant` would serve the header's
tenant to any authenticated user. Membership is checked only by `get_current_tenant`.

## Reproduction

1. Build a database with `alembic upgrade head` and connect as `app_user` with
   `RLS_ENABLED=true`.
2. Log in, then `GET /api/v1/categories`. Expect a failure in tenant resolution, or an empty list.
3. `grep -n NOT_YET_SCOPED tests/integration/test_rls_pricing.py` lists 120 routes.

No test runs the application as `app_user` with RLS on, which is why none of this has surfaced.

## Suspected Code Paths

- `backend/app/auth/dependencies.py`: `get_current_user`, `get_current_tenant`,
  `require_role`/`require_member`/`require_admin`, `get_tenant_db`, `get_platform_admin_db`,
  `get_shop_db`, `get_shop_sales_channel`
- `backend/app/database.py`: `get_db`, `scope_session_to_tenant`, the engines
- `backend/app/auth/middleware.py`: unvalidated `X-Tenant-ID`
- `backend/app/auth/customer_dependencies.py:241`: its own `SET LOCAL`
- `backend/app/api/v1/auth.py`: login, register
- `backend/app/services/onboarding_service.py`: `verify_email`
- `backend/app/tasks/{margin_alerts,telemetry,power,scenario}.py`, `backend/app/api/v1/printer_ws.py`
- `backend/alembic/versions/8c3c671816d9_create_rls_policies.py`: the `user_tenants` policies
- `backend/tests/integration/test_rls_pricing.py:860`: `NOT_YET_SCOPED`

## Root Cause Hypothesis

RLS was designed table-first (migrations `ecce200bf082`, `cffc14267961`, `8c3c671816d9`), but the
application never ran as `app_user`. Each session dependency sets the tenant its own way, with a
transaction-scoped statement, and the cross-tenant paths (membership lookup, platform admin,
sweeps) were never given a mechanism that works under RLS. Confidence: high.

## Proposed Remediation

**Preferred**:

1. **One mechanism for session context** (`app/core/rls.py`):
   `set_rls_context(session, tenant_id=…, user_id=…)` records the values in `session.info` and
   applies them with `set_config(name, value, true)`. A `Session` `after_begin` listener re-applies
   them at the start of every transaction, so a commit or rollback can no longer drop them.
   `get_tenant_db`, `get_shop_db`, `scope_session_to_tenant` and the customer dependency all use
   it. It does nothing while `rls_enabled` is off.
2. **Policy (option a)**: replace the `user_tenants` SELECT policy with
   `tenant_id = <current tenant> OR user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid`.
   INSERT, UPDATE and DELETE stay tenant-only, so a user can never write themselves into another
   tenant.
3. **Auth sets the context where the facts become known.** `get_current_user` sets the user on its
   session. `get_current_tenant` sets the tenant on the same request session once it has
   validated membership, and sets it before inserting an auto-created workspace's membership.
   Login sets the user; register and email verification set the new tenant before inserting the
   membership.
4. **`TenantDB` becomes the validated request session.** `get_tenant_db` depends on
   `get_current_tenant` and yields the request's `get_db` session, which that dependency scoped.
   The tenant is then always the validated one, never the raw header. One request has one session,
   and the 120 `get_db` routes that resolve `CurrentTenant` are scoped by the same act. The derived
   test counts a route as scoped when its dependency tree resolves `get_current_tenant` on the
   request session. `NOT_YET_SCOPED` shrinks to the routes that never resolve a tenant, and each
   is fixed or named with a reason.
5. **A real bypass for cross-tenant work**: a privileged session maker on `DATABASE_URL` (the
   migration role, which bypasses RLS), used only by `get_platform_admin_db`. The sweeps enumerate
   `tenants` (not under RLS) and set each tenant's context before working on it. Lookups by device
   (power, websocket) resolve the tenant through the privileged session first, then scope.
6. **Prove it**: an integration suite that migrates a scratch database, connects the application
   as `app_user` with `rls_enabled` on, and drives the core flows. Login, `/auth/me`, a `get_db`
   route, a `TenantDB` route, a role-guarded write, cross-tenant invisibility, the `X-Tenant-ID`
   spoof, platform admin, and a shop route.
7. **Switch it on**: set `RLS_ENABLED: "true"` in the manifest only once 1–6 pass. This also needs
   the `rls-credentials` secret, with `RLS_DATABASE_URL` and a real `app_user` password, to exist
   in the cluster.

**Alternatives**:
- Swap the 120 routes to `TenantDB` one by one, as the first assessment proposed. With today's
  `get_tenant_db`, that opens a second session per request and scopes it to the unvalidated
  header, so it is worse than point 4.
- Option (c), exempting `user_tenants`: declined by the user.

**Files likely to change**:
- `backend/app/core/rls.py` (new), `backend/app/database.py`, `backend/app/auth/dependencies.py`,
  `backend/app/auth/customer_dependencies.py`, `backend/app/api/v1/auth.py`,
  `backend/app/services/onboarding_service.py`, the four task modules, `backend/app/api/v1/printer_ws.py`
- `backend/alembic/versions/<new>_user_tenants_member_policy.py`
- `backend/tests/integration/test_rls_pricing.py`, `backend/tests/integration/test_rls_enforced.py` (new)
- later, separately: `infrastructure/k8s/backend/deployment.yaml`, `CLAUDE.md`

**Tests to add or update**:
- As `app_user` with RLS on: each flow in point 6.
- The context survives a commit and a rollback.
- `user_tenants`: a user sees their own memberships in every tenant, and nobody else's; a user
  cannot insert a membership into another tenant.
- The derived route test accepts a route as scoped only through the validated tenant.

## Risks & Considerations

- **Order of deployment**: the code and migration can deploy with RLS still off, because the
  context calls are no-ops. The flag goes on afterwards, as its own change.
- **The privileged session** is the one deliberate hole. It is used only behind
  `get_platform_admin`, and a test pins that.
- **Commerce bridge** (`app/commerce_bridge.py` and its siblings) runs its own engine and role
  checks; it is out of scope here and needs its own check before RLS goes on.
- **Celery tasks**: any task not listed above that opens a session needs the same treatment.
  Grep for `async_session_maker()` again before switching the flag on.

## Open Questions

- [NEEDS CLARIFICATION: does the `rls-credentials` secret exist in the cluster, with a real
  `app_user` password? It could not be checked from this machine.]
