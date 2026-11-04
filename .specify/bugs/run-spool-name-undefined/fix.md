# Bug Fix: Create Run wizard shows "undefined undefined" for a manually added spool

- **Slug**: run-spool-name-undefined
- **Fixed**: 2026-11-03
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The wizard names a manually added spool with `spoolName(spool)` and `spoolMaterialName(spool)` from `lib/spool.ts`, which read the nested filament type.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/src/components/production-runs/CreateRunWizard.tsx` | modified | lines ~403-404 |
| `frontend/src/components/production-runs/CreateRunWizard.test.tsx` | updated | spool mock moved to the nested shape |

## Tests Added or Updated

- Helper behaviour pinned by `frontend/src/lib/spool.test.ts` (`spoolName`, no `undefined`).

## Local Verification

- `npx tsc -b` → clean; `npx vitest run src/components/production-runs` → passed.

## Deviations from Assessment

- None.

## Follow-ups

- None.
