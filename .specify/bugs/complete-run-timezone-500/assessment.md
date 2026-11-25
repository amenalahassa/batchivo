# Bug Assessment: CompleteRunDialog mixes UTC and local time: negative duration and a 500 west of UTC

- **Slug**: complete-run-timezone-500
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator brief)
- **Verdict**: valid
- **Severity**: high

## Report (verbatim or summarized)

`test.fixme` "completes a run that has no estimated print time" (America/New_York) in `frontend/e2e/tests/production/production-run.spec.ts`, from `.specify/bugs/e2e-stale-specs/fix.md`.

## Symptom

West of UTC, completing a run with no duration shows "Network Error"; the run is in fact completed with a negative `duration_hours`. Expected: the run completes and the dialog closes.

## Reproduction

1. Browser in America/New_York.
2. Complete a run with no estimated print time.
3. The PATCH moves `started_at` 5 h ahead; `/complete` derives a negative duration, commits, then fails response validation (`ge=0`) -> 500.

## Suspected Code Paths

- `frontend/src/components/production-runs/CompleteRunDialog.tsx:149` - fills the datetime-local field from `toISOString()` (UTC)
- `frontend/src/components/production-runs/CompleteRunDialog.tsx:265` - reads it back with `new Date(value)` (local)
- `backend/app/services/production_run.py` complete/cancel/fail - duration = completed - started, unclamped
- `backend/app/api/v1/production_runs.py` PATCH - same derivation

## Root Cause Hypothesis

The round trip through the datetime-local input shifts the start by the browser's UTC offset; the backend trusts the result and can produce a negative duration after the commit. Confidence: high.

## Proposed Remediation

**Preferred**: Frontend: format the field in local time and convert back to UTC (`src/lib/datetimeLocal.ts`). Backend, defence in depth: one `elapsed_hours()` helper, never negative, used by complete, cancel, fail and the PATCH auto-calculation, so a skewed start can no longer 500 after a commit.

**Files likely to change**:
- `frontend/src/lib/datetimeLocal.ts` (new)
- `frontend/src/components/production-runs/CompleteRunDialog.tsx`
- `backend/app/services/production_run.py`
- `backend/app/api/v1/production_runs.py`
- tests

**Tests to add or update**:
- vitest: a start time round-trips to the same instant in New York, UTC and Tokyo; New York shows local wall-clock time.
- pytest: `elapsed_hours` rounds, clamps at 0, treats naive as UTC; completing a run started 5 h in the future answers 200 with 0 h.
- e2e: drop the fixme.

## Risks & Considerations

- Clamping records a start after the end as 0 h instead of failing; the frontend fix removes the usual cause. The PATCH path now rounds to 2 places like the others.

## Open Questions

None.
