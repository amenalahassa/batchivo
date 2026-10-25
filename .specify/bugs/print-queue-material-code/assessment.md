# Bug Assessment: Print queue compatibility check reads a field ModelMaterial does not have

- **Slug**: print-queue-material-code
- **Created**: 2026-10-25
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 22 round
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

> `print_queue_service.py:650` reads `material.material_code` on a `ModelMaterial`; the code lives on
> the spool's material type, not on the BOM line.

## Symptom

Auto-assigning a print job to a printer whose `capabilities` lists `materials` raises
`AttributeError: 'ModelMaterial' object has no attribute 'material_code'` for any model with a BOM.
Expected: the printer is judged compatible or not by the material type of each BOM line.

## Reproduction

1. Give a printer `capabilities = {"materials": ["PLA"]}`.
2. Queue a job for a model with at least one `ModelMaterial` line.
3. Call auto-assign (`POST /api/v1/print-queue/auto-assign`). Observe a 500.

## Suspected Code Paths

- `backend/app/services/print_queue_service.py:647-652` — the compatibility loop.
- `backend/app/models/model_material.py` — `ModelMaterial` has `spool_id`, `weight_grams`, `cost_per_gram`; no `material_code`.

## Root Cause Hypothesis

The loop was written against an older BOM shape. The material code is reachable as
`material.spool.material_type.code` (or the spool's own material field), which also needs eager
loading so the async session does not lazy-load.

## Proposed Remediation

Resolve each BOM line's material code through its spool, load the relationship with `selectinload`
in the query that fetches the model, and add a service test covering a compatible and an
incompatible printer.

## Risks & Considerations

A spool may be deleted or unassigned; treat a line with no resolvable code as unknown, not as
incompatible.

## Open Questions

None.
