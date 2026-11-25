# Bug Assessment: Categories "Show All" never lists inactive categories

- **Slug**: category-show-all-param
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator brief)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

`test.fixme` "should list inactive categories under Show All" in `frontend/e2e/tests/categories/category-management.spec.ts`, from `.specify/bugs/e2e-stale-specs/fix.md`.

## Symptom

Clicking "Show All" on the Categories page still shows only active categories. Expected: inactive categories listed too, with their switch off.

## Reproduction

1. Create a category and switch it off.
2. Click "Show All".
3. The category does not appear.

## Suspected Code Paths

- `frontend/src/components/categories/CategoryList.tsx:93` - sends `is_active: showInactive ? undefined : true`
- `frontend/src/lib/api/categories.ts:74` - serialises it as `?is_active=`
- `backend/app/api/v1/categories.py:31` - reads `include_inactive` (default false) and ignores `is_active`

## Root Cause Hypothesis

The client and the API disagree on the parameter name. The API never sees a request for inactive categories, so it always filters them out. Confidence: high.

## Proposed Remediation

**Preferred**: Rename the client parameter to `include_inactive` (sent only when true) and have "Show All" set it. The API stays as is. Callers that passed `is_active: true` drop it, since active-only is the default.

**Files likely to change**:
- `frontend/src/lib/api/categories.ts`
- `frontend/src/components/categories/CategoryList.tsx`
- `frontend/src/components/products/ProductCategoriesEditor.tsx`
- `frontend/src/components/products/ProductWizard/WizardCategorySelection.tsx`
- `frontend/src/lib/api/categories.test.ts` (new)

**Tests to add or update**:
- vitest: `listCategories({ include_inactive: true })` sends `include_inactive=true` and no `is_active`; the default sends neither.
- e2e: drop the fixme on "should list inactive categories under Show All".

## Risks & Considerations

- None for the API (unchanged). The two product-side callers already relied on the default.

## Open Questions

None.
