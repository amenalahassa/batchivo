# Bug Assessment: The Dashboard's "Add spool" and "Edit spool" dialogs still use the pre-FilamentType payload

- **Slug**: spool-create-missing-filament-type
- **Created**: 2026-11-03
- **Source**: pasted text (side finding of `spool-flat-fields-undefined`, 2026-11-03)
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

Found while assessing `spool-flat-fields-undefined`: `AddSpoolDialog` creates a spool without `filament_type_id`, which the API now requires (422); `EditSpoolDialog` edits brand/colour/material that `SpoolUpdate` no longer accepts, so those edits are silently dropped.

## Symptom

On the Dashboard (`/dashboard`, the app's landing page, which renders `SpoolList`), "Add spool" always fails with a 422 (shown as "Failed to create spool: Request failed with status code 422"). "Edit spool" saves, but any change to brand, colour, material, finish or the filament specifications is discarded without a word. Expected: adding a spool creates it under a filament type, and editing never claims to save a field it ignores.

## Reproduction

1. Open `/dashboard` → "Add spool", fill in material, brand, colour, weights → Create.
2. `POST /api/v1/spools` body has `material_type_id`, `brand`, `color`, … but no `filament_type_id` → 422 `filament_type_id: Field required`.
3. Open an existing spool → Edit → change the colour → Save → 200, but the colour is unchanged after refresh.

## Suspected Code Paths

- `backend/app/schemas/spool.py:16-20` — `SpoolBase.filament_type_id` is required; brand/colour/material/specs live on `FilamentType`.
- `backend/app/schemas/spool.py:~60-80` — `SpoolUpdate` accepts `filament_type_id` and spool-level fields only; unknown keys are ignored.
- `frontend/src/types/spool.ts:9-60` — `SpoolBase`/`SpoolCreate`/`SpoolUpdate` still model the old flat spool.
- `frontend/src/components/inventory/AddSpoolDialog.tsx:80,229-275` — builds and posts the old payload.
- `frontend/src/components/inventory/EditSpoolDialog.tsx:95-97,162,179-180` — edits and posts filament-level fields.
- `frontend/src/components/inventory/SpoolList.tsx:36,673-676` — mounts both dialogs.
- The current creation flow already exists: `frontend/src/components/filaments/AddFilamentDialog.tsx` (same props `open`/`onOpenChange`) → `POST /api/v1/filament-types/bulk-create` (`backend/app/api/v1/filament_types.py:260`), which finds or creates the filament type and creates N spools with sequential `FIL-NNN` ids.

## Root Cause Hypothesis

The filament-inventory refactor moved spool creation to the Filaments page (`AddFilamentDialog` → bulk-create) but left the Dashboard's legacy dialogs wired to the old flat schema. Confidence: **high**.

## Proposed Remediation

**Preferred**: in `SpoolList`, mount `AddFilamentDialog` instead of `AddSpoolDialog` (same props), so the Dashboard creates spools through the same endpoint as the Filaments page. In `EditSpoolDialog`, send only spool-level fields (`spool_id`, weights, purchase info, storage, notes, `is_active`), and show the filament type (material, brand, colour) read-only, read from `spool.filament_type`, with a note that those belong to the filament type. Correct `types/spool.ts` (`SpoolCreate`/`SpoolUpdate`) to the backend schemas so typecheck enforces it.

**Alternatives**:
- Teach `POST /api/v1/spools` to accept the old flat payload and find-or-create the filament type. Keeps the old dialog working but duplicates `bulk-create` logic in a second place.

**Files likely to change**:
- `frontend/src/components/inventory/SpoolList.tsx`
- `frontend/src/components/inventory/EditSpoolDialog.tsx` (+ `.test.tsx`)
- `frontend/src/types/spool.ts`
- `frontend/src/components/inventory/AddSpoolDialog.tsx` (left unused, or removed in a follow-up)

**Tests to add or update**:
- EditSpoolDialog submits no filament-level keys and shows the filament type read-only.
- SpoolList opens the filament creation dialog from "Add spool".

## Risks & Considerations

- `AddSpoolDialog` has SpoolmanDB lookup features; check `AddFilamentDialog` covers them before deleting the old dialog (removal is a follow-up, not part of this fix).
- Changing the colour of a filament type changes it for every spool of that type; the edit dialog must not do that implicitly.

## Open Questions

- [NEEDS CLARIFICATION: should the Dashboard keep a spool list at all, or redirect to the Filaments page?]
