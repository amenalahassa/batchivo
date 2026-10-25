# Bug Assessment: product_variants has no row-level security

- **Slug**: product-variants-rls
- **Created**: 2026-10-25
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 23 round
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

> `product_variants` carries `tenant_id` but has RLS disabled and no policy, on the dev database
> and on any database built from migrations (`create_product_variants_v1` creates it as the
> existing environments have it).

## Symptom

`SELECT relrowsecurity FROM pg_class WHERE relname = 'product_variants'` is false and
`pg_policies` has no row for it, while every other tenant table (products, fee_rules,
estimate_revisions, ...) has RLS enabled with a tenant policy. Isolation of variant rows rests on
application-level `tenant_id` filters alone, which Constitution I rules out as the sole belt.

## Reproduction

1. On any environment, run the query above.
2. Observe `f` and zero policies.

## Suspected Code Paths

- `backend/alembic/versions/cffc14267961_enable_rls_on_tenant_tables.py` and
  `8c3c671816d9_create_rls_policies.py` — `TENANT_SCOPED_TABLES` predates the table.
- `backend/alembic/versions/20261025_create_product_variants.py` — creates the table without RLS.
- Readers: `app/api/v1/products.py` (variant routes), `app/api/v1/shop.py`, `app/services/shopify_sync.py`, `etsy_sync.py`, `export_service.py`.

## Root Cause Hypothesis

The table was created outside Alembic when size variants landed, after the RLS migrations had
enumerated the tenant tables, and no later revision added it.

## Proposed Remediation

A migration that enables RLS on `product_variants` and creates the same tenant policy the other
tables use (`tenant_id = current_setting('app.current_tenant_id')::uuid`), plus a test that
every table with a `tenant_id` column has RLS enabled and a policy, derived from the catalog
rather than a list.

## Risks & Considerations

Shop routes read variants on the shop-scoped session; confirm `get_shop_db` sets the tenant before
enabling, or those reads return nothing.

## Open Questions

None.
