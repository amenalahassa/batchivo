# Bug Fix: Tenant tables without row-level security

- **Slug**: product-variants-rls
- **Fixed**: 2026-10-25
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

A migration enables and forces RLS, with a tenant policy, on the six tenant tables no earlier
revision covered. A catalog-derived test now fails on any tenant table without RLS that is not a
named, reasoned exception.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/alembic/versions/20261025_rls_uncovered_tenant_tables.py` | added | revision `rls_uncovered_tenant_tables_v1`: `product_variants`, `external_listings`, `model_files`, `order_items`, `product_categories`, `tenant_modules`; guarded by `to_regclass`; reversible |
| `backend/tests/integration/test_every_tenant_table_has_rls.py` | added test | asks `pg_class`/`pg_policy` for every table with `tenant_id`, with no hand-kept list |

## Tests Added or Updated

- `test_every_tenant_table_has_rls_enabled_and_a_policy`: every `tenant_id` table in a database
  built from migrations has RLS on and at least one policy, apart from
  `NOT_TENANT_ISOLATED_BY_DESIGN`.
- `test_every_by_design_exception_is_still_a_tenant_table`: an exception for a table that is gone
  fails.

## Local Verification

- On the test Postgres: before the migration, the catalog test listed the six tables plus
  `commerce_handover`. After it, it passes with `commerce_handover` as the one named exception.
- `alembic heads` reports a single head, `rls_uncovered_tenant_tables_v1`.
- Full CI-equivalent run: see `../FIX-RUN.md`.

## Deviations from Assessment

- **A seventh table surfaced**: `commerce_handover`. It exists only in migrations, not in the
  models, so the model-based sweep in the assessment could not see it. It is deliberately **not**
  isolated: `app/services/commerce_handover.py` reads it on its own engine, under an advisory
  lock, outside any tenant session, as a platform write fence. A tenant policy would break that
  fence once RLS is on, so it is listed in `NOT_TENANT_ISOLATED_BY_DESIGN` with that reason.
- **Open question resolved**: `product_categories.tenant_id` is `NOT NULL` in the model
  (`app/models/category.py:21`), so forcing the policy cannot hide existing links.
- **Not added**: the behavioural "tenant B cannot read tenant A's variant" test. It needs the
  `app_user` role with RLS enabled, which the test harness does not run as (see
  `rls-unscoped-routes`).

## Follow-ups

- No effect in production until `RLS_ENABLED` is turned on. While it is off, the app connects as
  the migration role, which bypasses RLS.
- Before turning RLS on, check who reads `tenant_modules`. Module gating may read it before a
  tenant session exists.
