# Bug Assessment: No migration creates product_variants

- **Slug**: product-variants-no-create-migration
- **Created**: 2026-10-25
- **Re-assessed**: 2026-10-25 (against `7a2776e`)
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 22 round (found by the e2e stage, T266)
- **Verdict**: valid — fixed (fix re-verified)
- **Severity**: high (a fresh environment could not list products)

## Report (verbatim or summarized)

> A database built from migrations alone has no `product_variants` table; the product list fails
> with `relation "product_variants" does not exist`.

## Re-assessment changes

The fix was re-verified on the current code:

- `backend/alembic/versions/20261025_create_product_variants.py` is still present. It has
  `revision = "create_product_variants_v1"` and `down_revision = "pricing_estimate_confidence_v1"`,
  and it is guarded by `to_regclass('public.product_variants')`.
- `20261025_tenant_currency_provenance.py` builds on it. `alembic heads` reports a single head,
  `pricing_tenant_currency_prov_v1`.
- `poetry run pytest tests/unit/test_product_variants_migration.py`: 5 passed.

Remaining gap, tracked separately: the table is created without RLS. See `product-variants-rls`.

## Symptom

Before the fix, `GET /api/v1/products` returned 500 on a freshly migrated database. Existing
environments were unaffected because their table predates the gap in the migration chain.

## Reproduction

1. Create an empty database and run `alembic upgrade` to a revision before `create_product_variants_v1`.
2. Request the product list. Observe a 500.
3. Upgrade to head. The table exists and the list returns 200.

## Suspected Code Paths

- `backend/alembic/versions/a0b1c2d3e4f5_*` and `f0g1h2i3j4k5_*` alter the table only if it
  exists. Before the fix, nothing created it.

## Root Cause Hypothesis

The size-variants feature created its table outside Alembic (from the models), and later
revisions assumed it was there. Confidence: high.

## Proposed Remediation

Applied in `dde8924`: `20261025_create_product_variants.py` creates the table exactly as the model
maps it when `to_regclass` finds none, and does nothing otherwise. Its downgrade never drops the
table. It is covered by `tests/unit/test_product_variants_migration.py` and by the e2e pipeline,
which builds its database from migrations alone. No further change is needed for this bug.

## Risks & Considerations

- None for existing environments: the revision is a no-op where the table exists.
- The table is created late in the chain. Any revision before `create_product_variants_v1` that
  reads `product_variants` unconditionally would still fail on a fresh database. The two known
  ones are guarded.

## Open Questions

None.
