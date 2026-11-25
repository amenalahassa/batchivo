# Bug Fix: Dashboard "Add spool" / "Edit spool" used the pre-FilamentType payload

- **Slug**: spool-create-missing-filament-type
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The Dashboard's "Add spool" now opens `AddFilamentDialog`, which creates spools through `POST /filament-types/bulk-create` like the Filaments page. `EditSpoolDialog` edits spool-level fields only and shows the filament type read-only; `SpoolUpdate` mirrors the backend, so typecheck rejects filament-level keys.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/src/components/inventory/SpoolList.tsx` | modified | mounts `AddFilamentDialog` instead of `AddSpoolDialog` |
| `frontend/src/hooks/useFilamentTypes.ts` | modified | bulk/batch create also invalidate `['spools']`, so the Dashboard list refreshes |
| `frontend/src/components/inventory/EditSpoolDialog.tsx` | modified | material/brand/colour/finish inputs → read-only filament block; batch and notes fields removed (not in `SpoolUpdate`); error shows `apiErrorDetail` |
| `frontend/src/types/spool.ts` | modified | `SpoolUpdate` = backend `SpoolUpdate` |
| `frontend/src/components/inventory/AddSpoolDialog.tsx` | modified | compile fix only; no longer mounted |
| `frontend/src/components/inventory/EditSpoolDialog.test.tsx` | updated + added tests | |

## Tests Added or Updated

- `EditSpoolDialog.test.tsx::EditSpoolDialog filament type::shows the filament type read-only`
- `...::sends only spool-level fields` — payload has no `brand`, `color`, `material_type_id`, `finish`, `notes`, batch keys.
- Existing purchase-price tests kept, mock moved to the nested shape.

## Local Verification

- `npx tsc -b` → clean; affected vitest suites → passed (162 tests).

## Deviations from Assessment

- `AddSpoolDialog` left in place, unmounted (removal is a follow-up per the assessment).
- No dedicated SpoolList test for the add-dialog swap: the dialog component is already tested in its own suite; covered by typecheck and the existing "renders Add Spool button" test.

## Follow-ups

- Delete `AddSpoolDialog.tsx` and the legacy `SpoolBase`/`SpoolCreate` types.
- Decide whether the Dashboard keeps a spool list or redirects to Filaments.
