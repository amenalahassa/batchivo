# Bug Assessment: No migration creates product_variants

- **Slug**: product-variants-no-create-migration
- **Created**: 2026-10-25
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 22 round (found by the e2e stage, T266)
- **Verdict**: valid — fixed
- **Severity**: high (a fresh environment cannot list products)

## Report (verbatim or summarized)

> A database built from migrations alone has no `product_variants` table; the product list fails
> with `relation "product_variants" does not exist`.

## Symptom

`GET /api/v1/products` returns 500 on a freshly migrated database. Existing environments are
unaffected because their table predates the migration chain's gap.

## Reproduction

1. Create an empty database and run `alembic upgrade head` (before `create_product_variants_v1`).
2. Request the product list. Observe 500.

## Suspected Code Paths

- `backend/alembic/versions/` — `a0b1c2d3e4f5` and `f0g1h2i3j4k5` alter the table only if it exists; nothing creates it.

## Root Cause Hypothesis

The size-variants feature created its table outside Alembic (from the models) and later
revisions assumed it was there.

## Proposed Remediation

Applied in `dde8924`: `20261025_create_product_variants.py` (revision `create_product_variants_v1`)
creates the table exactly as the model maps it when `to_regclass` finds none, and does nothing
otherwise; downgrade never drops it. Covered by `tests/unit/test_product_variants_migration.py`
and by the e2e pipeline, which builds its database from migrations alone.

## Risks & Considerations

None for existing environments: the revision is a no-op where the table exists.

## Open Questions

None.
