# Bug Assessment: Reordering newly created categories does nothing

- **Slug**: category-reorder-noop
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator brief)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

`test.fixme` "should reorder categories created from the dialog" in `frontend/e2e/tests/categories/category-management.spec.ts`, from `.specify/bugs/e2e-stale-specs/fix.md`.

## Symptom

Clicking the down arrow on a category created from the dialog leaves the order unchanged. Expected: it swaps with the next one.

## Reproduction

1. Create two categories from the "Add Category" dialog.
2. Click the down arrow on the first.
3. The order does not change.

## Suspected Code Paths

- `backend/app/api/v1/categories.py` `create_category` - stores `display_order` from the schema, default 0
- `frontend/src/components/categories/CategoryList.tsx:136` `handleMove` - swaps the two `display_order` values

## Root Cause Hypothesis

The dialog sends no order, so every new category gets 0. Swapping two equal orders changes nothing. Confidence: high.

## Proposed Remediation

**Preferred**: Backend: a category created without an explicit `display_order` goes after the tenant's existing ones (max + 1, or 0 for the first). Frontend: a move renumbers the shown list 0..n-1 in its new order and patches only the categories whose order changes, so tenants whose categories already share 0 can reorder too.

**Files likely to change**:
- `backend/app/api/v1/categories.py`
- `backend/tests/integration/test_categories_api.py`
- `frontend/src/lib/api/categories.ts`
- `frontend/src/components/categories/CategoryList.tsx`
- `frontend/src/lib/api/categories.test.ts`

**Tests to add or update**:
- pytest: two categories created without an order get max+1 and max+2; the first of a tenant gets 0.
- vitest: `displayOrderUpdatesForMove` moves within all-zero orders, swaps distinct ones, and is a no-op at the ends.
- e2e: drop the fixme.

## Risks & Considerations

- An explicit `display_order` (including 0) is still honoured.
- With the "Active" filter, renumbering the visible list can tie with a hidden inactive category; harmless (ties sort by name).

## Open Questions

None.
