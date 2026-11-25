# Bug Assessment: An inactive product's detail page is a 404

- **Slug**: product-inactive-detail-404
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator brief)
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

`test.fixme` "should toggle product active status" in `frontend/e2e/tests/products/product-crud.spec.ts`, from `.specify/bugs/e2e-stale-specs/fix.md`.

## Symptom

Saving a product as inactive redirects to its detail page, which shows "Error loading product" (404). The edit page uses the same GET, so the product cannot be switched back on. Expected: the detail page with an "Inactive" badge.

## Reproduction

1. Open a product, Edit, switch "Active Status" off, Save.
2. The detail page fails with 404.

## Suspected Code Paths

- `backend/app/api/v1/products.py` `get_product` - filters `Product.is_active.is_(True)`

## Root Cause Hypothesis

The detail endpoint treats inactive as deleted. A soft delete does set `is_active=False`, but purge (`DELETE ?purge=true`) is only allowed on inactive products, so the admin is meant to reach them. Confidence: high.

## Proposed Remediation

**Preferred**: Drop the `is_active` filter from `GET /products/{id}` only (tenant scope kept). Cost, margin and pricing endpoints keep it: an inactive product is not for sale. The list endpoint already filters by default.

**Files likely to change**:
- `backend/app/api/v1/products.py`
- `backend/tests/integration/test_products_api.py`

**Tests to add or update**:
- pytest: deactivate via PUT, GET returns 200 with `is_active` false, reactivate works.
- Update `test_delete_product`: after a soft delete GET is 200 (inactive); after a purge it is 404.
- e2e: drop the fixme.

## Risks & Considerations

- Behaviour change: a soft-deleted product now opens (marked inactive) instead of 404. The shop uses its own endpoints and is unaffected.

## Open Questions

None.
