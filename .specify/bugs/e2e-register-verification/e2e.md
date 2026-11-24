# Bug E2E Run: e2e registerAndLogin broken by business name + email verification

- **Slug**: e2e-register-verification
- **Run**: 2026-11-24
- **Assessment**: ./assessment.md
- **Fix**: ./fix.md
- **Result**: verified

## Summary

`registerAndLogin` is the bug's subject, and every journey under `e2e/tests/models` and
`e2e/tests/products` uses it. Across 69 test runs, 68 called it and all 68 completed: register 201,
token hook 200, verify-email 200, business-type step 200, then `/dashboard`. The 18 failing tests
all fail after login, on product screens whose specs no longer match the UI.

## Checks Performed

| Spec file | Command | Result | Notes |
|-----------|---------|--------|-------|
| `e2e/tests/models/model-fields.spec.ts` | `npx playwright test e2e/tests/models e2e/tests/products --project=chromium --reporter=list` | pass (19/19) | |
| `e2e/tests/products/product-fields.spec.ts` | same run | 12 pass, 2 fail | fail after login: `toBeTruthy` on a stock value; description text not visible after save |
| `e2e/tests/products/product-crud.spec.ts` | same run | 2 pass, 9 fail | fail after login: no "New Product" control on `/products` (7 time out on it); strict-mode violation on `getByRole('button', {name: /Active/})` (2 matches); products heading |
| `e2e/tests/products/shop-visibility.spec.ts` | same run | 0 pass, 7 fail | fail after login in the spec's own `createTestProduct` (`networkidle` / `/products/new` never settles); 1 run hit `ERR_NETWORK_IO_SUSPENDED` (host suspended) |

Total: 33 passed, 18 failed (33.5 min, 1 worker, retries 1).

Backend log over the run (backend started with `E2E_TEST_HOOKS_ENABLED=true`, its own DB on 5433):
68 × `POST /onboarding/register` 201, 68 × hook 200, 68 × `POST /verify-email` 200,
68 × `PUT /onboarding/wizard/step/2` 200. No 429s and no 500s.

## Output Excerpt

```
product-crud.spec.ts:223  await page.click('text=New Product')  → Test timeout of 30000ms exceeded.
product-crud.spec.ts:268  strict mode violation: getByRole('button', { name: /Active/i }) resolved to 2 elements
  33 passed / 18 failed (33.5m)
```

## Recommendation

The fix holds: throwaway users now register, verify and reach `/dashboard`, and the 3D-print
modules are on. Before this fix every one of these journeys failed in `beforeEach`. The remaining
product failures could not be compared with main, because the helper was broken there. They are
spec drift in `e2e/tests/products/` (renamed or moved "New Product" control, ambiguous `Active`
button, waits on `networkidle`). Track them as a separate e2e maintenance item; they do not block
closing this bug.

Run notes: an earlier run was voided. The backend was launched through a PowerShell pipe with SQL
echo on (`DEBUG=true`). Once about 5 MB of log had gone through, the pipe blocked the server's
stdout and the backend hung. For long e2e runs, start the backend with logs redirected to a file
and `DEBUG=false`.
