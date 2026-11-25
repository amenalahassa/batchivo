# Bug-fix run: 2026-10-25

Two passes of `/speckit-bug-fix` over the open bugs in this directory. The second pass applied
`rls-unscoped-routes` once option (a) was chosen: a `user_tenants` policy that admits a user's own
memberships through `app.current_user_id`.

| Slug | Status |
|---|---|
| postgres-naive-datetime-writes | applied (severity was lower than assessed; see its fix.md) |
| product-variants-rls | applied |
| viewer-write-guards | applied |
| onboarding-wizard-steps-missing | applied |
| print-queue-material-code | applied |
| hardcoded-gbp-outside-pricing | applied |
| login-validation-object-object | applied |
| rls-unscoped-routes | applied (second pass, option a); the production flag is not flipped |
| product-variants-no-create-migration | already fixed (`dde8924`) |

## Verification

Backend, CI stages via `backend/scripts/run_ci_tests.sh all 4` against `docker-compose.test.yml`
(PostgreSQL 16), after the second pass:

- `ruff check` and `ruff format`: clean.
- unit: 4380 passed.
- integration (PostgreSQL): 2732 passed, 66 skipped, 2 failed. Both failures were in
  `tests/integration/test_rls_tenant_isolation.py::TestGetTenantDbDependency`, which called the
  old `get_tenant_db(request)` signature. The class was rewritten for the new contract (it
  returns the request session; the scope is recorded on the session only with RLS on). That
  file was re-run: 13 passed, 6 skipped. The rest of the stage was not re-run after that
  test-only change.
- `tests/integration/test_rls_enforced.py` (the application as `app_user` with RLS on): 14 passed.

Frontend, after the first pass. The second pass did not change the frontend.

- `npm run lint`, `npm run typecheck`: clean.
- `npm test`: 1164 passed, after adding `@vitest-environment node` to `lib/apiError.test.ts`.

## Not done

- `RLS_ENABLED` is still `"false"` in `infrastructure/k8s/backend/deployment.yaml`, and it is off
  in the local `.env`. The steps to switch it on in production are in
  `docs-site/docs/self-hosting/kubernetes.md#row-level-security`.
