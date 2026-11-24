# Bug Fix: File-versions journey matches the "no measurable file" note as the Active badge

- **Slug**: e2e-file-versions-active-locator
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Both Active-badge assertions match the text exactly, so the FR-013 note is no longer a second match.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `frontend/e2e/pricing/file-versions.spec.ts` | modified | `getByText('Active', { exact: true })` on both badge assertions |

## Tests Added or Updated

- `file-versions.spec.ts › a new version is made active with only the figures chosen`: the journey itself.

## Local Verification

- Full pricing project, runs 9 and 10 → 20/20 each (before: failed in runs 3 and 7).
- `npx eslint e2e/pricing/` → clean.

## Deviations from Assessment

None.

## Follow-ups

- None.
