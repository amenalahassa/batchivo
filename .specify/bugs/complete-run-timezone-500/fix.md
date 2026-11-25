# Bug Fix: CompleteRunDialog mixes UTC and local time: negative duration and a 500 west of UTC

- **Slug**: complete-run-timezone-500
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Frontend: format the field in local time and convert back to UTC (`src/lib/datetimeLocal.ts`). Backend, defence in depth: one `elapsed_hours()` helper, never negative, used by complete, cancel, fail and the PATCH auto-calculation, so a skewed start can no longer 500 after a commit.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/src/lib/datetimeLocal.ts` | added | `toDateTimeLocalValue`, `fromDateTimeLocalValue` |
| `frontend/src/components/production-runs/CompleteRunDialog.tsx` | modified | uses them |
| `backend/app/services/production_run.py` | modified | `elapsed_hours()`; complete, cancel, fail use it |
| `backend/app/api/v1/production_runs.py` | modified | PATCH auto-duration uses it |
| `frontend/src/lib/datetimeLocal.test.ts` | added test | zone round trip |
| `backend/tests/unit/test_elapsed_hours.py` | added test | helper |
| `backend/tests/integration/test_production_runs_api.py` | added test | `test_complete_run_started_in_the_future_answers_200` |
| `frontend/e2e/tests/production/production-run.spec.ts` | modified | fixme removed; a comment that pointed at it updated |

## Tests Added or Updated

- `frontend/src/lib/datetimeLocal.test.ts`
- `backend/tests/unit/test_elapsed_hours.py`
- `test_production_runs_api.py::TestProductionRunCompletion::test_complete_run_started_in_the_future_answers_200`
- `production-run.spec.ts` > completes a run that has no estimated print time

## Local Verification

- New backend tests run against a throwaway PostgreSQL 16 (port 5467); new vitest files run on their own; all pass.
- e2e: `npx playwright test --project=chromium --retries=0 -g "completes a run that has no estimated print time"` against a throwaway stack (backend 8033, Vite 5193) -> pass (see e2e.md).

## Deviations from Assessment

None.

## Follow-ups

None.
