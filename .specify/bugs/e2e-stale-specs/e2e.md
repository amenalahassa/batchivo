# Bug E2E Run: Playwright specs drifted from the current UI

- **Slug**: e2e-stale-specs
- **Run**: 2026-11-24
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified on Chromium. WebKit failed for browser-engine reasons on this machine,
  and Firefox cannot run here (see below).

## Summary

The bug is the suite itself, so the check is the whole suite. On Chromium it went from 107 failed to
0 failed: 210 passed and 6 skipped, the six being `test.fixme`s for real app bugs listed in fix.md.
WebKit fails about 40% of tests on this Windows host with page crashes, interrupted navigations and
lost sessions, none of them locator mismatches. Firefox's executable is refused by the OS.

## Checks Performed

Stack: throwaway PostgreSQL 16 (5444), Redis (6390), backend 8011 (`E2E_TEST_HOOKS_ENABLED=true`),
Vite 5183. Command prefix: `PLAYWRIGHT_BASE_URL=http://localhost:5183 PLAYWRIGHT_API_URL=http://localhost:8011`.

| Spec file | Command | Result | Notes |
|-----------|---------|--------|-------|
| all (pre-fix, 35b7667) | `npx playwright test --project=chromium --retries=0 --workers=4 --reporter=list` | fail | 107 failed, 106 passed: the reproduction |
| all (post-fix, ab479f0) | `… --project=chromium --retries=0 --workers=3` | pass | 208 passed, 6 skipped, 0 failed (214 tests, 10.5 min) |
| all (post-fix, aaaf05c, ideas merged) | same | pass | **210 passed, 6 skipped, 0 failed** (216 tests, 15.2 min) |
| `e2e/pricing/cost-and-margin.spec.ts` | `… --project=pricing` on a fresh `seed_e2e.py` DB, after `history-and-tiers` added the 10+ tier | pass | 3/3: the margin button is scoped to the base (1+) row |
| all | `… --project=webkit --retries=0 --workers=2` | fail (env) | stopped after 48 tests to sync main: 29 ok, 19 x. Failures were "Frame load interrupted", "Page crashed", and app redirects to `/login?redirect=…`. All 19 passed on Chromium; none is a locator mismatch |
| all | `… --project=firefox` | not-run | `browserType.launch: spawn UNKNOWN`; running `firefox.exe` directly gives "Permission denied" (OS execution policy). Not worked around |

## Output Excerpt

```
Running 216 tests using 3 workers
  6 skipped
  210 passed (15.2m)
```

WebKit (sample):

```
Error: page.goto: Frame load interrupted
Error: page.goto: Page crashed
Error: page.goto: Navigation to "http://localhost:5183/dashboard" is interrupted by another navigation to "http://localhost:5183/login?redirect=%2Fdashboard"
```

## Recommendation

Chromium can gate merges again. Re-seed before each pricing run (README), because
`history-and-tiers.spec.ts` "the history shows the current price" also matches two buttons when
rerun on a database that already has the 10+ tier. That file is outside this fix's scope.
WebKit needs its own investigation, for two reasons:

- The frontend loads zone.js in every build, even with OTEL off: `src/lib/telemetry.ts` statically
  imports `@opentelemetry/context-zone`. On WebKit, zone.js turns promise results into
  `ZoneAwarePromise` objects. That already broke Playwright's `waitForFunction`, and the helper
  works around it.
- `AuthContext` clears the session on any failed `/users/me`.

Either may explain the lost sessions on Safari-class engines. Until that is understood, gate on
`--project=chromium` (plus `--project=pricing`) on this machine.
