# E2E Verification: the e2e gate takes 20–35 minutes

- **Slug**: e2e-slow-gate
- **Run**: 2026-11-24, branch `fix/e2e-slow-gate` on local main 2a590e2 (six app bugs merged,
  fixme tests restored)
- **Result**: pass — 238/238 (237 first try, 1 flaky passed on its retry), 0 skipped, 0 failed

## Command

```bash
# throwaway stack: postgres:16 on 5455, redis:7 on 6420, backend (E2E_TEST_HOOKS_ENABLED=true)
# on 8020 + celery worker (pool=solo), vite on 5190; migrated to printer_serial_v1, seed_e2e.py
cd frontend
PLAYWRIGHT_BASE_URL=http://localhost:5190 PLAYWRIGHT_API_URL=http://localhost:8020 \
  npx playwright test --project=chromium --project=pricing --reporter=list
```

3 workers (config default); the pricing projects ran on their own single worker.

## Before / after

Same machine, fresh seed, chromium + pricing in one run.

| Run | Workers | Tests | Result | Wall time |
|-----|---------|-------|--------|-----------|
| before: main 134d821 | 1 | 236 | 230 passed / 6 skipped | 27.3 min |
| before: main a32b6e0 | 1 | 237 | 231 passed / 6 skipped | 20.3 min |
| before: app-bugs merge, two runs | 1 | 238 | 218 + 20 passed | 21.3 + 1.5 = 22.8 min |
| **after: 2a590e2 + this fix** | 3 | 238 | 238 passed (1 flaky) | **9.7 min** (583 s; Playwright: 9.6 min) |

About 2.3× faster than the comparable 22.8 min, with the same tests: no `test(`, `test.fixme`,
`test.skip` or `expect(` line changed. The 6 skips of older baselines were the fixme tests that
2a590e2 restored, so 0 skipped is expected.

## Flaky test

`tests/products/product-fields.spec.ts:206` "should create product with all fields populated":
first attempt failed with `apiRequestContext.get: read ECONNRESET` on the `apiAs` GET of the new
product. The request never reached the backend (its log shows no such GET at that time, no
reload, no error): a socket reset on the Node side of the request pool, not an assertion. Passed
on retry #1 (11.2 s). Not seen on this test before; parallel load makes connection reuse more
frequent. Follow-up candidate: retry an `apiAs` call once on a connection reset.

## Notes

- A pre-run smoke (`api-tokens` + `dashboard-workflow`, 15 tests, `--retries=0`) passed in 50.7 s.
- Stack torn down after the run: containers removed, backend, celery and vite stopped, ports
  5455/6420/8020/5190 free.
