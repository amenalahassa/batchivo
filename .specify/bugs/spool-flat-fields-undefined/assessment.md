# Bug Assessment: Spool screens read flat brand/colour/material fields the API no longer sends

- **Slug**: spool-flat-fields-undefined
- **Created**: 2026-11-03
- **Source**: pasted text (local bugcap #55; user symptom in bugcap #46)
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

bugcap #46 (user): "Bill of Materials (Per Unit) — Issue: FIL-002 - undefined (undefined) but I set the cost in the filament purchases setting."

bugcap #55 (code review, 2026-11-03): after the FilamentType refactor, `SpoolResponse` nests brand, colour and material under `filament_type`; the frontend still reads them flat, so labels show `undefined` and sorting the spool list by material/brand/colour throws.

## Symptom

Every screen that labels a spool shows `undefined` (or blanks) where the brand, colour and material should be, e.g. the BOM editor shows `FIL-002 - undefined (undefined)`. Expected: `FIL-002 - PLA Basic (Jade White)`. Sorting the spool list by Material, Brand or Colour crashes the list with a `TypeError`, and creating a spool from the old dialog is rejected.

## Reproduction

1. Have at least one spool whose filament type is set.
2. Open a model → Bill of Materials (Per Unit): the material line reads `FIL-00x - undefined (undefined)`.
3. Open the Dashboard (renders `SpoolList`), choose sort = Material (or Brand, Colour): `a.material_type_code.localeCompare` → `TypeError: Cannot read properties of undefined`.
4. Dashboard → Add spool: the payload has `material_type_id`/`brand`/`color` but no `filament_type_id` → 422 [NEEDS CLARIFICATION: confirm in the running app whether `AddSpoolDialog` is still reachable from the current nav].

## Suspected Code Paths

- `backend/app/schemas/spool.py:16-20,84-104` — `SpoolBase` now has `filament_type_id` (required) and `SpoolResponse` exposes brand/colour/material only under `filament_type: FilamentTypeResponse`.
- `backend/app/api/v1/spools.py:22-43` — `spool_to_response` builds the nested `filament_type` dict (including `material_type_code`/`material_type_name`) and nothing flat.
- `frontend/src/types/spool.ts:9-14,111-112` — `SpoolBase`/`SpoolResponse` still declare `material_type_id`, `brand`, `color`, `material_type_code`, `material_type_name` at top level, so `npm run typecheck` cannot catch the drift.
- Readers of the flat fields (all render `undefined`):
  - `components/models/BOMEditor.tsx:284` — the #46 label.
  - `components/inventory/SpoolList.tsx:207-211` (sort → crash), `:470-484` (rows).
  - `components/inventory/SpoolCard.tsx:107,180`, `ViewSpoolDialog.tsx:116-118`, `DeleteSpoolDialog.tsx:73-81`, `UpdateWeightDialog.tsx:122`.
  - `components/inventory/SearchableSpoolSelect.tsx:44,86-101,143-146,195` — the search haystack is `"FIL-002 undefined undefined undefined"`, so searching by colour or brand finds nothing.
  - `components/production-runs/CreateRunWizard.tsx:403-404`, `CompleteRunDialog.tsx:99`, `EditRunDialog.tsx:115` — spool names written into run materials as `undefined undefined`.
  - `components/dashboard/LowStockAlerts.tsx:44`, `pages/SpoolLabelPage.tsx:81-88` (printed labels), `pages/SpoolQuickUpdatePage.tsx:160-173`, `lib/db/indexeddb.ts:166` (offline search: `undefined.toLowerCase()` throws).
  - `components/inventory/AddSpoolDialog.tsx:80,229` and `EditSpoolDialog.tsx:95-97,162` — create without `filament_type_id` (422); edits of brand/colour are silently dropped by `SpoolUpdate`.
- Tests that pin the stale shape: `SpoolList.test.tsx`, `SearchableSpoolSelect.test.tsx`, `EditSpoolDialog.test.tsx`, `CreateRunWizard.test.tsx` (mocks with flat fields, so they pass against a shape the API never returns).

## Root Cause Hypothesis

The filament-inventory refactor split a spool into a `FilamentType` (brand, colour, material) and the physical `Spool`, and changed the backend response to nest the type. The frontend `Spool` type and its consumers were not migrated, and the component tests mock the old flat shape, so neither typecheck nor tests flagged it. Confidence: **high** (read directly from the schema, the response builder and the components).

## Proposed Remediation

**Preferred**: migrate the frontend to the nested shape. Update `types/spool.ts` so `SpoolResponse` carries `filament_type_id` and `filament_type?: FilamentTypeResponse | null` and drops the flat fields; let `npm run typecheck` list every broken reader and fix each one through a small helper (`spoolLabel(spool)`, `spoolBrand(spool)`, `spoolColor(spool)`, `spoolMaterialCode(spool)`) in `lib/spool.ts` that handles a missing `filament_type`. Make the sort comparators null-safe. Retire or rewrite `AddSpoolDialog`/`EditSpoolDialog` to pick a filament type (`filament_type_id`) the way the Filaments page does.

**Alternatives**:
- Add read-only flat fields (`brand`, `color`, `material_type_code`, `material_type_name`) back onto `SpoolResponse` in `spool_to_response`. Smallest diff and fixes every label at once, but keeps two representations of the same data on the wire and leaves the create/edit dialogs broken.

**Files likely to change**:
- `frontend/src/types/spool.ts`
- `frontend/src/lib/spool.ts` (new helper) + `frontend/src/lib/spool.test.ts`
- The components listed above, `lib/db/indexeddb.ts`
- `frontend/src/components/inventory/{SpoolList,SearchableSpoolSelect,EditSpoolDialog}.test.tsx`, `production-runs/CreateRunWizard.test.tsx`, `models/BOMEditor.test.tsx` (mocks to the nested shape)

**Tests to add or update**:
- BOMEditor renders `FIL-002 - PLA Basic (Jade White)` from a nested spool (regression for #46).
- SpoolList sorts by material/brand/colour without throwing, including a spool with `filament_type: null`.
- SearchableSpoolSelect finds a spool by colour/brand.
- Backend contract test: `GET /api/v1/spools` item has `filament_type.brand/color/material_type_code` (pins the shape the frontend relies on).

## Risks & Considerations

- Production run materials already saved with `spool_name = "undefined undefined"` stay wrong; decide whether to backfill from the spool's filament type.
- Offline IndexedDB cache holds the old shape; the search fix must tolerate both.
- Printed spool labels made since the refactor may read `undefined`; operators may need to reprint.

## Open Questions

- [NEEDS CLARIFICATION: is the Dashboard `SpoolList` / `AddSpoolDialog` path still meant to exist, or should it be removed in favour of the Filaments page from the inventory refinement?]
