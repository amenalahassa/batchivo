# Bug Assessment: A designer typed in ModelForm is lost on blur (same for source and machine)

- **Slug**: model-form-custom-value-lost
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator brief)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

`test.fixme` "should save a new designer typed in the form" in `frontend/e2e/tests/models/model-fields.spec.ts`, from `.specify/bugs/e2e-stale-specs/fix.md`.

## Symptom

After "+ Add new designer" and typing a name, leaving the input resets the Select to its placeholder and the POST has no `designer`. Source and machine behave the same. Expected: the typed name is kept and saved.

## Reproduction

1. New model, Designer -> "+ Add new designer".
2. Type a name, tab out.
3. The Select shows "Select a designer"; the saved model has no designer.

## Suspected Code Paths

- `frontend/src/components/models/ModelForm.tsx` designer/source/machine `FormField`s - the input `onBlur` sets the field to the typed text, which has no `SelectItem`

## Root Cause Hypothesis

Inside a form, Radix Select keeps a hidden native `<select>`. When the value changes to one with no `<option>` yet, the native select reports an empty value and Radix calls `onValueChange('')`, wiping the field. Adding the item in the same render as the value is too late: the option registers after the change event. Confirmed in vitest. Confidence: high.

## Proposed Remediation

**Preferred**: Offer the typed value as a `SelectItem` while "+ Add new" is open (and the current value whenever it is not in the list, e.g. an inactive designer on edit), so the option already exists when blur sets the field.

**Files likely to change**:
- `frontend/src/components/models/ModelForm.tsx`
- `frontend/src/components/models/ModelForm.test.tsx`

**Tests to add or update**:
- vitest: for designer, source and machine, type a new value, blur, the Select shows it, and `createModel` receives it.
- e2e: drop the fixme.

## Risks & Considerations

- While typing, the closed dropdown holds an item for the partial text; it is not visible and goes away once the value is committed or changed.

## Open Questions

None.
