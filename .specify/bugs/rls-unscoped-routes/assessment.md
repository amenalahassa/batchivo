# Bug Assessment: 120 tenant routes still run on a session without RLS

- **Slug**: rls-unscoped-routes
- **Created**: 2026-10-24
- **Source**: pasted text (side finding S2 from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 21 round)
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

> `NOT_YET_SCOPED` in `tests/integration/test_rls_pricing.py` pins about a hundred tenant routes
> still on `get_db` "with no deliberate reason", so each relies on an application-level
> `tenant_id` filter alone. Constitution I requires RLS via `get_tenant_db`.

## Symptom

These routes open a session with `get_db`, which never runs `SET LOCAL app.current_tenant_id`.
With `settings.rls_enabled = True` in production, the RLS policies either deny every row (if the
policy has no fallback) or the route is protected only by its hand-written `WHERE tenant_id = …`.
Expected: every tenant-scoped route uses `get_tenant_db`, so PostgreSQL enforces isolation even
when a query forgets the filter.

## Reproduction

1. `cd backend && grep -n "NOT_YET_SCOPED" tests/integration/test_rls_pricing.py` — the set
   starting at line 855 lists 120 `(method, path)` pairs.
2. `test_every_route_is_scoped_or_named` (line ~1020) passes because it accepts any route in the set.
3. Pick one, e.g. `GET /api/v1/categories`: its handler in `app/api/v1/categories.py` depends on
   `get_db`, not `get_tenant_db`.

## Suspected Code Paths

Routers pinned in `NOT_YET_SCOPED`, with route counts:

- `app/api/v1/audit.py` (5), `categories.py` (8), `dashboard.py` (6), `designers.py` (5),
  `forecasting.py` (4), `model_files.py` (10), `modules.py` (2), `newsletter.py` (1),
  `pages.py` (5), `payments.py` (2), `printer_bambu.py` (12 — AMS sync writes
  `spool.current_weight`), `printers.py` (1), `production_runs.py` (1, failure reasons),
  `reviews.py` (6), `settings.py` (16), `shipping.py` (3), `shop.py` (5), `sku.py` (2),
  `spoolmandb.py` (6), `tenant_members.py` (4), `test.py` (4), `users.py` (1), `webhooks.py` (11).
- `backend/app/auth/dependencies.py` — `get_tenant_db` (the dependency they should use).
- `backend/tests/integration/test_rls_pricing.py:855` — the allow-list to shrink to empty.

## Root Cause Hypothesis

These routers predate the RLS dependency and were never migrated; the pricing feature migrated
its own routers and pinned the rest so the derived route test could go green. Confidence: high.

## Proposed Remediation

**Preferred**: Router by router, swap `Depends(get_db)` for `Depends(get_tenant_db)` on every
tenant-scoped route and delete its entries from `NOT_YET_SCOPED`. Routes that genuinely run
before a tenant is known (public shop entry points, webhooks verified by signature, `test.py`)
move to `UNSCOPED_ROUTES_BY_DESIGN` with their reason. End state: `NOT_YET_SCOPED` is empty and
removed, and the derived test fails on any new unscoped route. Do it in small batches (one or two
routers per commit) so a regression is easy to bisect.

**Alternatives**:
- Make `get_db` set the tenant when `request.state.tenant_id` is present — one change, but it
  blurs the line between scoped and unscoped sessions that the guardrail test relies on.

**Files likely to change**:
- the 23 routers listed above
- `backend/tests/integration/test_rls_pricing.py`

**Tests to add or update**:
- For each migrated router, one cross-tenant test (tenant B cannot read or write tenant A's row) run on Postgres with RLS on.
- Remove `NOT_YET_SCOPED`; keep `test_every_route_is_scoped_or_named`.

## Risks & Considerations

- A route that queries a table whose RLS policy lacks the tenant setting will start returning
  nothing; run the integration suite with RLS enabled after each batch.
- Webhook and shop routes resolve their tenant differently (signature, domain); they need
  `get_shop_tenant` or a by-design entry, not a blind swap.
- Background tasks that reuse these handlers' sessions must set the tenant too.

## Open Questions

- [NEEDS CLARIFICATION: `dashboard.py`, `shipping.py`, `payments.py` and `shop.py` may read revenue, postage or prices the pricing feature owns — if so, those routes belong in that feature's scope rather than this bug.]
