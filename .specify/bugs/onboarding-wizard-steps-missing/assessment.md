# Bug Assessment: onboarding wizard steps call endpoints that do not exist

- **Slug**: onboarding-wizard-steps-missing
- **Created**: 2026-10-25
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 25 round
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

> The onboarding wizard saves each step with `PUT /api/v1/onboarding/wizard/step/{1..4}`, but the
> onboarding router mounts only three `POST` routes and none of them is a wizard step.

## Symptom

Every wizard step's mutation in `frontend/src/pages/Onboarding.tsx` gets a 404 or 405. Step 3's
shop currency and step 4's first product (name, description, price) are never stored, so a tenant
finishing onboarding has neither the currency it chose nor the product it typed.

Step 4 also labels its price with its own symbol map,
`currency === 'GBP' ? '£' : currency === 'EUR' ? '€' : '$'`, which shows `$` for every other
currency (JPY, CHF, SEK...). `symbolForCurrency` in `frontend/src/lib/money.ts` already maps
these.

## Reproduction

1. Register a new tenant and open the onboarding wizard.
2. Complete step 1 and watch the network panel: `PUT .../onboarding/wizard/step/1` fails.
3. `grep -n "@router\." backend/app/api/v1/onboarding.py` lists three `POST` routes.

## Suspected Code Paths

- `frontend/src/lib/api/onboarding.ts` — `updateOnboardingStep1..4`, `uploadLogo`
- `frontend/src/pages/Onboarding.tsx` — the step mutations
- `frontend/src/components/onboarding/Step4FirstProduct.tsx:79` — the local symbol map
- `backend/app/api/v1/onboarding.py`, `backend/app/services/onboarding_service.py` — no wizard routes

## Root Cause Hypothesis

The wizard frontend was built against a planned API that was never implemented on the backend.

## Proposed Remediation

Implement the wizard routes on the onboarding router, on `TenantDB`. Step 3 writes the tenant's
currency through the settings path, so its provenance is recorded (T272). Step 4 creates the
product through the product service, and its typed price becomes a channel list price, not a stored
cost. Use `symbolForCurrency(currency)` in Step 4. Add tests: success, 401, 422, and a 404 for an
unknown step.

## Out of scope for 002-pricing-engine-rebuild

Onboarding is not a surface the pricing feature built or depends on. The only pricing-adjacent
part is the step 4 price, which today is never stored.
