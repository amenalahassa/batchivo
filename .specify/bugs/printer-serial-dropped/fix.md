# Bug Fix: Printer serial number is silently dropped

- **Slug**: printer-serial-dropped
- **Fixed**: 2026-11-24
- **Assessment**: ./assessment.md
- **Status**: applied

## Summary

Add a nullable `printers.serial_number` (String 100) with a migration on the single head (`api_tokens_v1`), and the field on `PrinterBase` and `PrinterUpdate` (max 100). The service already maps every schema field onto the model.

## Changes

| File | Change | Notes |
|------|--------|-------|
| `backend/app/models/printer.py` | modified | `serial_number` column |
| `backend/app/schemas/printer.py` | modified | field on base and update schemas |
| `backend/alembic/versions/20261124_printer_serial_number.py` | added | `printer_serial_v1`, down_revision `api_tokens_v1` |
| `backend/tests/integration/test_printers_api.py` | added tests | round trip and length |
| `frontend/e2e/tests/printers/printer-fields.spec.ts` | modified | fixme removed |

## Tests Added or Updated

- `test_printers_api.py::TestPrintersEndpoints::test_serial_number_is_saved_and_updated`
- `test_printers_api.py::TestPrintersEndpoints::test_serial_number_too_long_is_rejected`
- `printer-fields.spec.ts` > should save serial_number correctly

## Local Verification

- New backend tests run against a throwaway PostgreSQL 16 (port 5467); new vitest files run on their own; all pass.
- e2e: `npx playwright test --project=chromium --retries=0 -g "should save serial_number correctly"` against a throwaway stack (backend 8033, Vite 5193) -> pass (see e2e.md).
- `alembic upgrade head`, then `downgrade -1`, then `upgrade head` on the throwaway database; `alembic heads` -> `printer_serial_v1` (single head).

## Deviations from Assessment

None.

## Follow-ups

None.
