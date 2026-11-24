# Bug Assessment: Playwright specs drifted from the current UI

- **Slug**: e2e-stale-specs
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator session brief)
- **Verdict**: valid
- **Severity**: high — the full e2e suite is the acceptance gate for every backlog merge, and half of it is red for reasons unrelated to the change under review.

## Report (summarized)

After `registerAndLogin` was fixed (35b7667), the specs under `frontend/e2e/` get past login for the
first time in a long while, and about 180 of the first 248 tests fail: ambiguous strict-mode locators
(heading "Categories", printer cell "Test Printer …" vs "Machine cost for Test Printer", dashboard
link `/inventory/i`), renamed or removed buttons ("add spool"), `tests/auth/*` with their own signup
helper that skips email verification, `tests/products/*` (18 stale), plus categories, dashboard,
inventory, printers, orders, production and the root `production-run-*` specs. Fix the specs, not the
app; leave `frontend/e2e/pricing/` alone.

## Symptom

Observed: `npx playwright test --project=chromium` on 35b7667 against a clean local stack: **107 failed,
106 passed** (213 tests, 16 min, 4 workers, no retries). Expected: green, so the suite can gate merges.

## Reproduction

1. Throwaway PostgreSQL 16 (port 5444) migrated to head, Redis (6390), backend on 8011 with
   `E2E_TEST_HOOKS_ENABLED=true`, Vite on 5183 with `VITE_API_URL=http://localhost:8011`.
2. `cd frontend && PLAYWRIGHT_BASE_URL=http://localhost:5183 PLAYWRIGHT_API_URL=http://localhost:8011 npx playwright test --project=chromium --retries=0 --workers=4 --reporter=list`
3. 107 failures, by file:

| Spec | Failed |
|---|---|
| `e2e/categories.spec.ts` | 2 |
| `e2e/production-run-auto-population.spec.ts` | 4 |
| `e2e/production-run-edit-flow.spec.ts` | 3 |
| `e2e/production-run-multi-model-materials.spec.ts` | 1 |
| `tests/auth/login.spec.ts` | 4 |
| `tests/auth/registration.spec.ts` | 9 |
| `tests/categories/category-management.spec.ts` | 8 |
| `tests/dashboard/dashboard-workflow.spec.ts` | 5 |
| `tests/inventory/consumable-fields.spec.ts` | 2 |
| `tests/inventory/spool-fields.spec.ts` | 23 |
| `tests/inventory/spools.spec.ts` | 9 |
| `tests/models/model-fields.spec.ts` | 1 |
| `tests/orders/order-create.spec.ts`, `order-flow.spec.ts` | 1 + 1 |
| `tests/printers/printer-fields.spec.ts` | 12 |
| `tests/production/production-run.spec.ts` | 2 |
| `tests/products/*` | 18 |
| `tests/settings/settings-workflow.spec.ts` | 2 |

Firefox and WebKit could not be run: only Chromium builds are installed on this machine.

## Suspected Code Paths

Spec-side causes, each seen in the baseline `error-context.md` files:

- `frontend/src/components/ui/button.tsx:43` — `Button` ignores `asChild`, so every
  `<Button asChild><Link/></Button>` renders a `<button>` wrapping an `<a>`. Any
  `getByRole('link').or(getByRole('button'))` matches both → strict-mode violations (dashboard,
  settings, products, nav).
- Pages pair an `<h2>` title with an `<h3>` card title of the same word (`CategoryList.tsx:216/270`,
  `ProductList.tsx:104`) → `getByRole('heading', { name })` matches two.
- Lists render a mobile card view (`lg:hidden`) and a desktop table → `getByText(name)` hits a hidden
  and a visible element.
- `PrinterList.tsx:333` — the cost button is `aria-label="Machine cost for <name>"`, so a non-exact cell
  name matches two cells; `PrinterFormDialog.tsx:223` — Model is now a select, not a text input.
- `Signup.tsx` — business name required, password rules ("8+ characters", "Password must meet all
  requirements"), registration ends on "Check your email" (verification step).
- `App.tsx:222` — `/inventory` redirects to `/filaments`.
- `e2e/categories.spec.ts` — used a hard-coded production product id and name.
- `SquareSettings.tsx` — status reads "Credentials not configured".

## Root Cause Hypothesis

High confidence. The specs were written against an older UI and never ran green after the
signup/verification change broke `registerAndLogin`, so a year of UI changes (renames, layout
duplication, new required fields, routes) went undetected. A few specs also relied on data in a shared
account, which no longer exists now that each test registers a fresh tenant.

## Proposed Remediation

**Preferred**: update each spec to the current UI, keeping each test's intent:

- Use role queries scoped by level, row or dialog, with `exact` where names are prefixes; target the
  `link` role for `asChild` buttons.
- Seed data a test needs but does not test through the API, with a new `apiAs(page)` helper in
  `e2e/helpers.ts` (authorized calls with the stored session) and `uniqueSuffix()`.
- Rewrite `tests/auth/*` on the real signup → "Check your email" → token hook → `/verify-email` flow,
  reusing `registerAndLogin` / `fetchVerificationToken` (now exported) / `createTestUser` from helpers.
- Replace `if (await x.isVisible())` guards with real assertions, and check saved values through the
  API where the test claims a field "saves correctly".
- Where a spec exposes a real app bug, mark only that test `test.fixme` with the reason, and report it.

**Files likely to change**: every spec listed above and `frontend/e2e/helpers.ts`. No app code.

**Tests to add or update**: the specs themselves; the acceptance run is the full suite.

## Risks & Considerations

- `fixme` tests hide real bugs from the gate until fixed; each is listed in `fix.md` and reported to
  the orchestrator.
- Firefox/WebKit browsers are not installed; installing them is a download that needs the user's yes.
- Long runs: Python's stdout is block-buffered when redirected, so backend logs lag; not a test issue.

## Open Questions

- [NEEDS CLARIFICATION: may Playwright's Firefox and WebKit builds be installed to run those projects?]
  (asked the orchestrator)
