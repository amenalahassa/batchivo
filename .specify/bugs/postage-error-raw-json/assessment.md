# Bug Assessment: Postage save errors do not show the server's explanation

- **Slug**: postage-error-raw-json
- **Created**: 2026-11-03
- **Source**: pasted text (local bugcap #58; user report bugcap #40)
- **Verdict**: valid
- **Severity**: low

## Report (verbatim or summarized)

bugcap #40 "Postage" (user), quoting the response:

```json
{
    "detail": "'Canada colis' already covers 0.00g to any weight in zone 'CA'; two profiles claiming one parcel would make its postage depend on which row was read first"
}
```

"Fix: display proper error message"

## Symptom

When saving a postage (shipping) profile is refused, the operator does not get a readable reason in the panel: the alert renders the axios error's `message` (`Request failed with status code 422`), so the explanation is only visible as raw JSON in the response/devtools, as captured in the report. Expected: the alert says, in plain words, which existing profile already covers that zone and weight range.

## Reproduction

1. Settings → Postage → add a profile for zone `CA` covering 0 g to any weight (e.g. "Canada colis").
2. Add a second profile for zone `CA` whose weight range overlaps.
3. Save → the backend answers 422 with the `detail` above; the "Not saved" alert shows the generic axios message rather than that detail.

[NEEDS CLARIFICATION: the report's screenshot shows the JSON body itself; with the current `apiClient` (axios), `error.message` is the status line, so the JSON was probably read from the network tab. Either way the panel does not show the detail.]

## Suspected Code Paths

- `frontend/src/components/settings/ShippingProfilesPanel.tsx:189,214-218` — renders `saveError.message`.
- `frontend/src/lib/apiError.ts:34-40` — `apiErrorDetail(error)` already extracts a FastAPI `detail` (string, `{message}` or validation list) from an axios error; the panel does not use it.
- `backend/app/api/v1/shipping_profiles.py:186-194` — the overlap message itself is developer-worded (`repr` quotes, "which row was read first").
- Same pattern (raw `error.message`) in ~20 other components, e.g. `FilamentPurchaseForm.tsx:299`, `ModelCostProfileForm.tsx:282`, `ProvenanceFieldsPanel.tsx:70`, `PrinterCostPolicyForm.tsx:255`, `PricingPolicySettings.tsx:252`, `FeeRuleEditor.tsx:426`, `FeePreviewPanel.tsx:129`, `AddConsumableDialog.tsx:371`, `EditConsumableDialog.tsx:389`, `PrinterFormDialog.tsx:409`, `PlateFormDialog.tsx:359`, `ProductWizard/index.tsx:417`, `TeamSettings.tsx:273`.

## Root Cause Hypothesis

The panel displays the transport error instead of the API's `detail`. `apiErrorDetail` was introduced (login fix) but not adopted across the mutation alerts. Confidence: **high**.

## Proposed Remediation

**Preferred**: render `apiErrorDetail(saveError)` in `ShippingProfilesPanel`, and reword the backend overlap message for operators, e.g. `"Canada colis" already covers 0 g – any weight in zone CA. Change its weight range or edit that profile instead.` Apply the same `apiErrorDetail` swap to the other mutation alerts listed above in the same change (mechanical, one import + one expression each).

**Alternatives**:
- Normalise in the axios response interceptor (`lib/api.ts`): set `error.message = detailText(detail) ?? error.message` once. Fixes every screen without touching components, but mutates axios errors globally and hides the status line some screens may rely on.

**Files likely to change**:
- `frontend/src/components/settings/ShippingProfilesPanel.tsx` (+ `.test.tsx`)
- `backend/app/api/v1/shipping_profiles.py` (+ its overlap test)
- Optionally the other components listed above

**Tests to add or update**:
- ShippingProfilesPanel: a 422 with a string `detail` shows exactly that text in the "Not saved" alert.
- Backend: overlap refusal message names the existing profile and zone without `repr` quotes.

## Risks & Considerations

- Backend tests asserting the exact overlap wording must be updated.
- If the interceptor alternative is chosen, check code paths that branch on `error.message`.

## Open Questions

- [NEEDS CLARIFICATION: fix only the postage panel, or sweep all mutation alerts in the same change?]
