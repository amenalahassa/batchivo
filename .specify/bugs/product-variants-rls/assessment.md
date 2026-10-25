# Bug Assessment: product_variants (and five other tenant tables) have no row-level security

- **Slug**: product-variants-rls
- **Created**: 2026-10-25
- **Re-assessed**: 2026-10-25 (against `7a2776e`)
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 23 round
- **Verdict**: valid (still open; scope widened)
- **Severity**: high

## Report (verbatim or summarized)

> `product_variants` carries `tenant_id` but has RLS disabled and no policy, on the dev database
> and on any database built from migrations (`create_product_variants_v1` creates it as the
> existing environments have it).

## Re-assessment changes

- **Still open.** None of the four migrations that touch `product_variants`
  (`20261025_create_product_variants.py`, `20261025_tenant_currency_provenance.py`,
  `a0b1c2d3e4f5`, `f0g1h2i3j4k5`) enables RLS or creates a policy.
- **Five more tables have the same gap.** I compared every model table with a `tenant_id` column
  against every migration that enables RLS or creates a policy. Six tables are never covered:
  - `product_variants`
  - `external_listings`
  - `model_files`
  - `order_items`
  - `product_categories`
  - `tenant_modules`

  `order_items` appears in `20261024_order_item_fx_provenance.py` only for a column change, not
  for RLS. This comparison reads the migration source only and was not run against a live
  catalog.
- **Production impact today is limited.** Production runs with `RLS_ENABLED: "false"` (see
  `rls-unscoped-routes`), so no table's RLS is in force yet. This gap must close before RLS is
  switched on, or these six tables stay open while the rest are protected.

## Symptom

`SELECT relrowsecurity FROM pg_class WHERE relname = 'product_variants'` returns false, and
`pg_policies` has no row for it. Every table in `cffc14267961`'s list does have RLS forced with a
tenant policy. Isolation of rows in the six tables rests on application-level `tenant_id` filters
alone, which Constitution I rules out as the only safeguard.

## Reproduction

1. On a database built with `alembic upgrade head`, run
   `SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ('product_variants','external_listings','model_files','order_items','product_categories','tenant_modules');`
2. Expect `f` for each, and no rows in `pg_policies` for them.

[NEEDS CLARIFICATION: not run in this pass, because no batchivo Postgres was running. The
evidence is the migration source.]

## Suspected Code Paths

- `backend/alembic/versions/cffc14267961_enable_rls_on_tenant_tables.py:43` (`TENANT_SCOPED_TABLES`)
  and `8c3c671816d9_create_rls_policies.py`. Both enumerate tables by hand, and the list predates
  these six or missed them.
- `backend/alembic/versions/20261025_create_product_variants.py` creates the table without RLS.
- Readers of variants: `app/api/v1/products.py` (variant routes), `app/api/v1/shop.py`,
  `app/services/shopify_sync.py`, `etsy_sync.py`, `export_service.py`.
- `tenant_modules` is read when resolving module access (`/api/v1/modules`), possibly before a
  tenant session exists. See Risks.

## Root Cause Hypothesis

The RLS migrations enumerated tenant tables by hand. Tables created later, or outside Alembic
like `product_variants`, were never added, and no test derives the expected set from the catalog.
Confidence: high.

## Proposed Remediation

**Preferred**: One migration that, for each of the six tables, runs `ENABLE` and
`FORCE ROW LEVEL SECURITY` and creates the same policy pair as `8c3c671816d9`
(`tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid`). Guard it with
`to_regclass` so it is idempotent. Then add an integration test that queries the catalog for
every table with a `tenant_id` column and asserts `relrowsecurity` plus at least one policy, with
no hand-kept list.

**Alternatives**:
- Add the six names to a list-based test. It is quicker, but the next new table repeats the bug.

**Files likely to change**:
- `backend/alembic/versions/<new>_rls_for_uncovered_tenant_tables.py`
- `backend/tests/integration/test_every_tenant_table_has_rls.py` (new)

**Tests to add or update**:
- Catalog-derived: every `tenant_id` table has RLS forced and a policy.
- With RLS on: tenant B cannot read tenant A's variant, order item or model file.

## Risks & Considerations

- Shop routes read variants and order items on `get_shop_db`, which does set the tenant
  (`dependencies.py:461-466`). Confirm each of those routes uses it before enabling.
- `tenant_modules` may be read by module-gating code on an unscoped session. Enabling RLS there
  without fixing the reader would hide every module. Check `/api/v1/modules` and `ModuleGuard`'s
  backend first.
- `product_categories` is a join table. Confirm its `tenant_id` is populated on every row before
  forcing a policy, or existing links become invisible.

## Open Questions

- [NEEDS CLARIFICATION: does `product_categories.tenant_id` have NULLs in existing environments?]
