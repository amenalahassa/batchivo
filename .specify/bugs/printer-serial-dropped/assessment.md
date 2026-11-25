# Bug Assessment: Printer serial number is silently dropped

- **Slug**: printer-serial-dropped
- **Created**: 2026-11-24
- **Source**: pasted text (orchestrator brief)
- **Verdict**: valid
- **Severity**: medium

## Report (verbatim or summarized)

`test.fixme` "should save serial_number correctly" in `frontend/e2e/tests/printers/printer-fields.spec.ts`, from `.specify/bugs/e2e-stale-specs/fix.md`.

## Symptom

The printer form has a Serial Number field; the value is accepted with no error but never stored. Expected: saved and returned.

## Reproduction

1. Add a printer with a serial number.
2. Reopen it or GET `/api/v1/printers/{id}`.
3. `serial_number` is missing.

## Suspected Code Paths

- `frontend/src/components/printers/PrinterFormDialog.tsx:247` - sends `serial_number`
- `backend/app/schemas/printer.py` - `PrinterBase`/`PrinterUpdate` have no such field (Pydantic drops it)
- `backend/app/models/printer.py` - no column (the Bambu connection has its own `serial_number`, a different record)

## Root Cause Hypothesis

The field exists only in the frontend. Confidence: high.

## Proposed Remediation

**Preferred**: Add a nullable `printers.serial_number` (String 100) with a migration on the single head (`api_tokens_v1`), and the field on `PrinterBase` and `PrinterUpdate` (max 100). The service already maps every schema field onto the model.

**Files likely to change**:
- `backend/app/models/printer.py`
- `backend/app/schemas/printer.py`
- `backend/alembic/versions/20261124_printer_serial_number.py` (new)
- `backend/tests/integration/test_printers_api.py`

**Tests to add or update**:
- pytest: create, get, update and clear a serial number; 101 characters is a 422.
- e2e: drop the fixme.

## Risks & Considerations

- Migration: additive nullable column, no data change; downgrade drops it. RLS policies are per table, so the column is covered.

## Open Questions

None.
