# Bug Assessment: onboarding wizard calls endpoints that do not exist

- **Slug**: onboarding-wizard-steps-missing
- **Created**: 2026-10-25
- **Re-assessed**: 2026-10-25 (against `7a2776e`)
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 25 round
- **Verdict**: valid (still open; impact larger than first assessed)
- **Severity**: high (raised from medium)

## Report (verbatim or summarized)

> The onboarding wizard saves each step with `PUT /api/v1/onboarding/wizard/step/{1..4}`, but the
> onboarding router mounts only three `POST` routes and none of them is a wizard step.

## Re-assessment changes

- **Six endpoints are missing, not four.** `frontend/src/lib/api/onboarding.ts` calls:
  - `GET /onboarding/wizard/status` (line 83)
  - `PUT /onboarding/wizard/step/1` through `/step/4` (lines 95, 105, 118, 131)
  - `POST /onboarding/wizard/logo` (line 141)

  The backend router (`app/api/v1/onboarding.py`, mounted at `/api/v1/onboarding` in
  `main.py:257`) defines only `register_tenant`, `verify_email` and `resend_verification`. No
  `wizard` route exists anywhere in `backend/app`.
- **Every new tenant hits it.** `VerifyEmail.tsx:65` sends every newly verified tenant to
  `/onboarding`. The status query fails, so the page starts at step 1. Step 1's mutation fails and
  only sets an error (`Onboarding.tsx:62`), so the user cannot advance. Only step 4 has a skip, so
  there is no way out of the wizard short of typing `/dashboard` into the address bar. This is
  why severity rises to high: it is the first screen of self-serve signup.
- The step 4 symbol map at `Step4FirstProduct.tsx:79` is unchanged.

## Symptom

After verifying their email, a new tenant lands on a wizard whose every save returns 404. They
are stuck on step 1. The business details (step 1), craft type (step 2), shop currency, timezone
and colour (step 3), first product (step 4) and logo are never stored.

Step 4 also labels its price with `currency === 'GBP' ? '£' : currency === 'EUR' ? '€' : '$'`,
which shows `$` for every other currency. `symbolForCurrency` in `frontend/src/lib/money.ts:119`
already maps these.

## Reproduction

1. Register a new tenant and follow the verification link.
2. You land on `/onboarding`. In the network panel, `GET .../onboarding/wizard/status` returns 404.
3. Fill in step 1 and continue. `PUT .../onboarding/wizard/step/1` returns 404, an error shows,
   and the step does not advance.
4. `grep -n "@router\." backend/app/api/v1/onboarding.py` lists three `POST` routes.

## Suspected Code Paths

- `frontend/src/lib/api/onboarding.ts:80-145`: `getOnboardingStatus`, `updateOnboardingStep1..4`, `uploadLogo`
- `frontend/src/pages/Onboarding.tsx:33-108`: status query and step mutations. There is no escape
  on error.
- `frontend/src/pages/VerifyEmail.tsx:65`: the redirect into the wizard.
- `frontend/src/components/onboarding/Step4FirstProduct.tsx:79`: the local symbol map.
- `backend/app/api/v1/onboarding.py`, `backend/app/services/onboarding_service.py`: no wizard routes.

## Root Cause Hypothesis

The wizard frontend was built against a planned API that was never implemented on the backend.
Confidence: high.

## Proposed Remediation

**Preferred**: Implement the six routes on the onboarding router, on `TenantDB` with a
`RequireAdmin`/owner guard (only the tenant's owner should run onboarding):

- `GET /wizard/status` returns `current_step` and `is_completed`. Store progress in tenant
  settings, not a new table, unless a column is clearly needed.
- Step 1 updates name, slug and description. Step 2 sets `tenant_type`. That gates modules, so
  reuse whatever path changes it elsewhere.
- Step 3 writes the tenant's currency through the existing settings path, so its provenance is
  recorded (T272).
- Step 4 creates the product through the product service (skip allowed). Its typed price becomes
  a channel list price, not a stored cost.
- `POST /wizard/logo` reuses `ImageStorageService`.

Use `symbolForCurrency(currency)` in Step 4. As a safety net, give the wizard page an "I'll do this
later" link to `/dashboard`, so a backend failure can never trap a user again.

**Alternatives**:
- Remove the redirect in `VerifyEmail.tsx` and hide the wizard until the backend exists. This
  unblocks signup immediately but loses onboarding.

**Files likely to change**:
- `backend/app/api/v1/onboarding.py`, `backend/app/services/onboarding_service.py`, `backend/app/schemas/onboarding.py`
- `backend/tests/api/test_onboarding_wizard.py` (new)
- `frontend/src/components/onboarding/Step4FirstProduct.tsx`, `frontend/src/pages/Onboarding.tsx`

**Tests to add or update**:
- Per route: success, 401, 422, and 404 for an unknown step.
- Step 3 records currency provenance. Step 4 with `skip: true` completes without a product.
- Frontend: Step 4 shows `¥` for JPY. The wizard offers a way to the dashboard on error.

## Risks & Considerations

- Changing `tenant_type` after signup changes which modules are enabled. Make sure step 2 runs
  before any module-specific data exists, or refuse a change once it does.
- Tenants who signed up while this was broken have no recorded progress. `status` should treat
  them as complete, or offer the wizard without forcing it.

## Out of scope for 002-pricing-engine-rebuild

Onboarding is not a surface the pricing feature built or depends on. The only pricing-adjacent
part is the step 4 price, which today is never stored.

## Open Questions

- [NEEDS CLARIFICATION: is self-serve signup live in production? If not, the severity can drop
  back to medium.]
