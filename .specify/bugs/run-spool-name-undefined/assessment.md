# Bug Assessment: New production run shows "undefined undefined" for a manually added spool

- **Slug**: run-spool-name-undefined
- **Created**: 2026-11-03
- **Source**: pasted text (side finding of `spool-flat-fields-undefined`, 2026-11-03)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

Found while assessing `spool-flat-fields-undefined`: the production-run screens build spool names from `spool.brand`/`spool.color`, which the spool API no longer returns flat. The original note said the names were "saved"; on checking, they are display-only (see below).

## Symptom

In the Create Run wizard, adding a material spool by hand lists it as `undefined undefined` with an empty material type. Expected: `Bambu Lab Jade White (PLA Basic)` or similar. The run itself is saved correctly (only `spool_id` and weights are sent).

## Reproduction

1. Runs → New run → Materials step → add a spool manually (not from the BOM suggestion).
2. The material row reads `undefined undefined`; the review step shows the same.

## Suspected Code Paths

- `frontend/src/components/production-runs/CreateRunWizard.tsx:403-404` — `spool_name: \`${spool.brand} ${spool.color}\``, `material_type: spool.material_type_name` on a `GET /api/v1/spools` item (nested `filament_type`).
- `frontend/src/components/production-runs/CreateRunWizard.tsx:192-202` — submit maps materials to `ProductionRunMaterialCreate`; `spool_name` is not sent, so nothing wrong is persisted.
- Not affected (checked): BOM suggestions (`:255-270`) use `spool_name` built server-side (`backend/app/api/v1/models.py:668-676`); `CompleteRunDialog.tsx:99` and `EditRunDialog.tsx:115` read `material.spool`, a `SpoolSummary` that the backend flattens from the filament type (`backend/app/schemas/production_run.py:52-85`).

## Root Cause Hypothesis

Same drift as `spool-flat-fields-undefined`: the wizard reads flat fields from the spool list response. Confidence: **high**.

## Proposed Remediation

**Preferred**: build the name with the shared spool-label helper introduced by `spool-flat-fields-undefined` (`lib/spool.ts`), reading `spool.filament_type`. Fixed as part of that change.

**Files likely to change**:
- `frontend/src/components/production-runs/CreateRunWizard.tsx`

**Tests to add or update**:
- Covered by the `lib/spool.ts` helper tests; the wizard tests' spool mocks move to the nested shape.

## Risks & Considerations

- None beyond those of `spool-flat-fields-undefined`.

## Open Questions

- None.
