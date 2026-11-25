# Bug Assessment: Print queue compatibility check reads a field ModelMaterial does not have

- **Slug**: print-queue-material-code
- **Created**: 2026-10-25
- **Re-assessed**: 2026-10-25 (against `7a2776e`)
- **Source**: side finding from `/speckit-converge` on `002-pricing-engine-rebuild`, Phase 22 round
- **Verdict**: valid (still open)
- **Severity**: medium

## Report (verbatim or summarized)

> `print_queue_service.py:650` reads `material.material_code` on a `ModelMaterial`; the code lives on
> the spool's material type, not on the BOM line.

## Re-assessment changes

- **Corrected path to the code.** `Spool` no longer has a material type of its own. It has
  `filament_type` (`app/models/spool.py:142`), and `FilamentType` has `material_type`
  (`app/models/filament_type.py:134`). The code therefore lives at
  `material.spool.filament_type.material_type.code`, not `material.spool.material_type.code`.
- **The existing unit test masks the bug.** `tests/unit/test_print_queue_service.py:39-41` builds
  BOM lines as `SimpleNamespace(material_code=...)`, an attribute the real model does not have.
  The tests pass while production code fails.
- **Loading.** `_get_pending_jobs` (`print_queue_service.py:820-834`) eager-loads
  `Model.materials` through `with_landed_cost`, which follows spool to purchase but not
  `Spool.filament_type.material_type`. Once the attribute is fixed, the walk would lazy-load on an
  async session and raise `MissingGreenlet` unless the loader is extended.

## Symptom

Auto-assigning a pending job, for a model with a BOM, to a printer whose `capabilities` lists
`materials` and that has no model-specific printer config raises
`AttributeError: 'ModelMaterial' object has no attribute 'material_code'`, and the request
returns 500. Expected: the printer is judged compatible or not by each BOM line's material type.

## Reproduction

1. Give a printer `capabilities = {"materials": ["PLA"]}` and no `printer_configs` entry for the model.
2. Queue a job for a model with at least one `ModelMaterial` line.
3. `POST /api/v1/print-queue/auto-assign`. Observe a 500.

## Suspected Code Paths

- `backend/app/services/print_queue_service.py:647-652`: the compatibility loop.
- `backend/app/services/print_queue_service.py:820-834`: `_get_pending_jobs`, the eager-load options.
- `backend/app/models/model_material.py`: has `spool_id`, `weight_grams`, `cost_per_gram` and a
  `spool` relationship, but no `material_code`.
- `backend/tests/unit/test_print_queue_service.py:39-41`: the fake BOM line.

## Root Cause Hypothesis

The loop was written against an older BOM shape, and its unit test was written to the same
assumption with a duck-typed stand-in, so the drift never surfaced. Confidence: high.

## Proposed Remediation

**Preferred**:

1. In `_is_printer_compatible`, resolve each line's code through
   `material.spool.filament_type.material_type.code`. A line whose chain is broken (no spool, no
   filament type) counts as unknown and is skipped, not judged incompatible.
2. In `_get_pending_jobs`, add
   `selectinload(PrintJob.model).selectinload(Model.materials).selectinload(ModelMaterial.spool).selectinload(Spool.filament_type).selectinload(FilamentType.material_type)`
   alongside `with_landed_cost`.
3. Rewrite the unit test's `make_material` to build the real chain, and add a service-level test
   on a real session covering a compatible and an incompatible printer.

**Alternatives**:
- Compare against `material_type_id` and store IDs in printer capabilities. This avoids the
  string code, but capabilities are user-entered codes ("PLA") today, so it would need a migration.

**Files likely to change**:
- `backend/app/services/print_queue_service.py`
- `backend/tests/unit/test_print_queue_service.py`
- `backend/tests/integration/test_print_queue_auto_assign.py` (new, or an existing service test)

**Tests to add or update**:
- Compatible printer is chosen, incompatible printer is skipped, and a line with no resolvable
  code does not block assignment.
- The auto-assign route returns 200 for a model with a BOM.

## Risks & Considerations

- Capability codes are free text. Compare case-insensitively, or users who typed "pla" will see
  every printer refused.
- The extra eager load adds four `selectin` queries per auto-assign. That is negligible.

## Open Questions

None.
