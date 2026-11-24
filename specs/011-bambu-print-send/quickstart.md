# Quickstart: validating the print send (spec 011)

No real printer is ever contacted: FTPS and MQTT are mocked in every automated
test. A real printer check is a manual, optional step for the operator.

## Prerequisites

- Test database up (`docker-compose.test.yml`, port 5433) — announce to the
  orchestrator before running pytest.
- `cd backend && poetry run alembic upgrade head` reaches `20261123_print_sends`
  and `poetry run alembic heads` shows one head.

## Automated checks

```powershell
cd backend; poetry run pytest tests/api/test_print_sends_api.py tests/unit/test_print_send_service.py tests/unit/test_print_send_tracker.py tests/unit/test_bambu_ftps.py tests/unit/test_bambu_mqtt_start.py tests/unit/test_printer_secrets.py tests/integration/test_print_sends_migration.py -q
```

```powershell
cd backend; poetry run ruff check; poetry run ruff format --check
```

```powershell
cd frontend; npm run test:run; npm run lint; npm run typecheck
```

```powershell
cd frontend; npm run test:e2e -- e2e/tests/printers --project=chromium --reporter=list
```

## Scenarios (see contract and spec)

1. **Prepare does nothing to the printer** — prepare plate 1 of the sample
   sliced file with one PETG-loaded slot for a PLA filament: 201, a
   `material_mismatch` warning, `requires_acknowledgement: true`; FTPS and MQTT
   mocks not called; no `print_jobs` row. (US1, FR-002/003/004)
2. **Acknowledgement** — confirm without `acknowledge_warnings`: 409
   `acknowledgement_required`, send still `prepared`; confirm with it: 200,
   upload called once, `project_file` published with `Metadata/plate_1.gcode`
   and the mapping, a `printing` job exists. (US2, FR-004a/006/008)
3. **Single use and expiry** — confirm the same token again: 409; a token
   prepared 6 minutes ago (clock frozen): 410. (FR-005/006)
4. **No half-started job** — FTPS mock raises: 502 `transfer_failed`, no job;
   MQTT publish fails: 502 `start_failed`, no job, remote delete attempted.
   (FR-009, SC-004)
5. **Status follows the printer** — feed the tracker `RUNNING` then `FINISH`
   for the remote file: job `completed`, `completed_at` set, proposal
   `pending`; `FAILED` with error 50348044: `cancelled`. (FR-010, SC-005)
6. **Proposal** — accept with one corrected amount: spool weights drop by the
   accepted grams, one inventory transaction each naming the job; accept again:
   409. (US4, FR-020, SC-006)
7. **Developer Mode gate** — connection with `developer_mode=false`: prepare
   409 `send_not_available`; the UI shows no "Send print". Transfer test with
   the FTPS mock refusing login: `{ok:false}` and saving still works. (US3)
8. **Tenant isolation** — another tenant's token: 404; another tenant's
   printer: 404. (FR-016)

## Optional manual check on a real printer (operator only)

Put the printer in LAN mode with Developer Mode on, set its connection (IP,
serial, access code, Developer Mode) in Batchivo, press "Test file transfer",
then send a small sliced plate and watch the job reach "completed".
