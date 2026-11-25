# Bug E2E Run: Printer serial number is silently dropped

- **Slug**: printer-serial-dropped
- **Run**: 2026-11-24
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

The test that was `test.fixme`'d for this bug (`frontend/e2e/tests/printers/printer-fields.spec.ts` › "should save serial_number correctly") now runs and passes, alone and in the full chromium + pricing suite on a freshly seeded database.

## Checks Performed

| Spec file | Command | Result | Notes |
|-----------|---------|--------|-------|
| `frontend/e2e/tests/printers/printer-fields.spec.ts` | `npx playwright test --project=chromium --retries=0 -g "<the six regression titles>"` | pass | 6/6, throwaway stack: backend 8033 (`E2E_TEST_HOOKS_ENABLED=true`), Vite 5193, PostgreSQL 5466 |
| whole suite | `npm run test:e2e -- --project=chromium --project=pricing --reporter=list` | pass | fresh seed: 236 passed, 1 failed (`pricing/scenario.spec.ts`: no Celery worker on the throwaway stack, run stayed queued). With the worker started, that spec alone: 3 passed |

## Output Excerpt

`ok [chromium] › e2e/tests/printers/printer-fields.spec.ts › … › should save serial_number correctly`

## Recommendation

Fix confirmed by `frontend/e2e/tests/printers/printer-fields.spec.ts`; close the bug.
