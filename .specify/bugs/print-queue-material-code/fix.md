# Bug Fix: Print queue compatibility check reads a field ModelMaterial does not have

- **Slug**: print-queue-material-code
- **Fixed**: 2026-10-25
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

The compatibility check now reads each bill-of-materials line's code through
`spool.filament_type.material_type.code`. The pending-jobs query eager-loads that chain, and the
unit test's stand-in now has the real shape.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/services/print_queue_service.py` | modified | `_material_code()` helper; case-insensitive comparison; a line with no resolvable code is skipped; `_get_pending_jobs` adds the four-level `selectinload` |
| `backend/tests/unit/test_print_queue_service.py` | updated test | `make_material` builds line → spool → filament type → material type; 3 new tests |
| `backend/tests/api/test_print_queue.py` | added test | auto-assign end to end with a real BOM line |

## Diff Highlights

```python
def _material_code(material: ModelMaterial) -> Optional[str]:
    spool = material.spool
    filament_type = spool.filament_type if spool else None
    material_type = filament_type.material_type if filament_type else None
    return material_type.code if material_type else None
```

## Tests Added or Updated

- `test_print_queue_service.py::TestMaterialCodeResolution`: a line with no spool does not block
  assignment; codes compare case-insensitively; `ModelMaterial` has `spool` and no
  `material_code` (this pins the shape the stand-in mirrors).
- `test_print_queue.py::TestAutoAssignReadsTheBillOfMaterials`: a PLA job goes to a printer that
  lists `pla`, and not to one that lists something else. Both return 200. Before the fix, the
  route returned 500.

## Local Verification

- `pytest tests/unit/test_print_queue_service.py`: 14 passed.
- `pytest tests/api/test_print_queue.py`: 39 passed.
- Full CI-equivalent run: see `../FIX-RUN.md`.

## Deviations from Assessment

- None of substance. The test fixture refreshes `test_model.materials` because the route shares
  the test's session, where the model was loaded before its BOM line existed. A real request's
  fresh session has no such stale state.

## Follow-ups

- None.
