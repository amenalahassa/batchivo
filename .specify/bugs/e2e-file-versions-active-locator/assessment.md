# Bug Assessment: File-versions journey matches the "no measurable file" note as the Active badge

- **Slug**: e2e-file-versions-active-locator
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator: `file-versions.spec.ts` fails on clean main; intermittent on the isolated stack, runs 3 and 7)
- **Verdict**: valid (test defect, not an app defect)
- **Severity**: medium (e2e gate red, no user impact)

## Report (verbatim or summarized)

```
Locator: getByRole('listitem', { name: 'Version 2' }).getByText('Active')
Error: strict mode violation: ... resolved to 2 elements:
    1) <div class="inline-flex ...">Active</div>
    2) <p role="status" class="text-sm text-amber-600">No measurable file in the active version. Upload ...</p>
```

## Symptom

Once version 2 (a sliced G-code only) is active, its block shows the Active badge and the
FR-013 note "No measurable file in the active version". `getByText('Active')` is a
case-insensitive substring match and finds both; it passes only when the assertion lands
before the note renders.

## Reproduction

1. Seed the e2e tenant; run `file-versions.spec.ts` several times.
2. Some runs fail at line 90 with the strict-mode violation above.

## Suspected Code Paths

- `frontend/e2e/pricing/file-versions.spec.ts:65,90`: `getByText('Active')`.
- `frontend/src/components/models/ModelFilesEditor.tsx` (`VersionBlock`): the badge and the
  `has_measurable_file` note, both as spec 004 FR-013 and acceptance scenario 6 require.

## Root Cause Hypothesis

The locator is too loose; the app shows what spec 004 asks. Confidence: high.

## Proposed Remediation

**Preferred**: `getByText('Active', { exact: true })` on both badge assertions.

**Files likely to change**:
- `frontend/e2e/pricing/file-versions.spec.ts`

**Tests to add or update**:
- The journey itself, two green runs in a row.

## Risks & Considerations

- None.

## Open Questions

- None.
