# Implementation Plan: Send a Print to a Bambu Lab Printer, with Confirmation

**Branch**: `claude/011-bambu-print-send-07c5b3` | **Date**: 2026-11-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/011-bambu-print-send/spec.md`

## Summary

A two-step send for Bambu LAN printers in Developer Mode. **Prepare** reads the
sliced `.gcode.3mf` (stored model file or upload) with the existing 3MF reader,
builds a summary per plate filament (expected material/colour/grams, mapped AMS
slot, the spool Batchivo maps there, the printer's live tray report, mismatch
warnings) and returns it with a single-use confirmation token valid 5 minutes.
**Confirm** (token + explicit acknowledgement when there are warnings) uploads
the file over implicit FTPS, sends the MQTT `project_file` command, and only
then creates a `PrintJob`. A tracker listening to MQTT status moves the job to
completed/failed/cancelled and opens a spool-deduction proposal the operator
accepts, corrects or dismisses. The connection settings gain a Developer Mode
flag with an explanation and an on-demand file-transfer test. Architecture:
`docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §8; decisions and deviations in
[research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.9 / React 19 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Alembic, paho-mqtt (existing), stdlib `ftplib` (implicit FTPS, R1); TanStack Query, shadcn/ui. No new dependency.

**Storage**: PostgreSQL (new `print_sends` table with RLS, `printer_connections.developer_mode`); uploaded files in the existing model-file storage (local / S3).

**Testing**: pytest + pytest-asyncio (FTPS and MQTT always mocked), Vitest + Testing Library, Playwright targeted e2e (`e2e/tests/printers/`).

**Target Platform**: Linux server (k3s, 2 backend pods) + browser SPA.

**Project Type**: web application (backend + frontend).

**Performance Goals**: prepare < 3 s for a 50 MB file stored on S3; confirm bounded by upload time; the status tracker reacts only to state changes (no DB query per status message).

**Constraints**: no print without confirm (FR-006); no half-started job (FR-009); access code never logged or returned (FR-017); 5-minute window; works when prepare and confirm hit different pods (R7).

**Scale/Scope**: a handful of printers per tenant; tens of sends per day.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | How |
|---|---|---|
| I. Multi-tenant isolation | ✅ | `print_sends.tenant_id` + RLS (4 policies, FORCE) in the migration; new endpoints use `CurrentTenant` + `TenantDB`; queries filter `tenant_id` too; tracker opens a tenant-scoped session (tenant id carried in the MQTT config); cross-tenant tests for prepare/confirm/list/accept. |
| II. Tests ship with the change | ✅ | Each endpoint: success, 401, 422, 404 (+ 403/409/410/502/503 cases); service tests for mismatch rules, token lifecycle, failure atomicity, tracker transitions; FTPS client and MQTT command unit tests with mocks; migration CRUD/constraint tests; Vitest for dialogs; targeted e2e. |
| III. One implementation per calculation | ✅ | Plate time/weight/filaments come from the existing 3MF reader (R3, extended additively, not duplicated); stock movement goes through `InventoryTransactionService` (R12); no cost or margin computed. |
| IV. Money exact / settings honoured | ✅ | Grams are `Decimal` strings; the 5-minute window is a setting (`print_send_confirm_window_seconds`). No money involved. |
| V. Derived figures expire | ✅ | The summary is a snapshot of what was shown (provenance of a confirmation), not a reused derived figure: confirm re-checks live printer state before sending. |
| VI. History immutable, provenance visible | ✅ | `print_sends.summary` is written once; the confirmed file/plate/mapping/acknowledgement/user/time are kept (FR-018); the proposal records proposed vs accepted grams and who decided. |
| VII. Deployment through the pipeline | ✅ | No manual deploy; commit only, no push. |

No violation; Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/011-bambu-print-send/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/print-send-api.md
├── checklists/requirements.md
└── tasks.md
```

### Source Code

```text
backend/
├── alembic/versions/20261123_print_sends.py          # new table + developer_mode + RLS
├── app/
│   ├── config.py                                     # + print_send_confirm_window_seconds (shared, 1 line)
│   ├── main.py                                       # + router include, + tracker registration (shared)
│   ├── models/print_send.py                          # new
│   ├── models/printer_connection.py                  # + developer_mode, can_send_prints
│   ├── models/print_job.py                           # + read-only print_send relationship
│   ├── models/__init__.py                            # export PrintSend (shared, 1 line)
│   ├── schemas/print_send.py                         # new
│   ├── schemas/printer_connection.py                 # + developer_mode, can_send_prints
│   ├── schemas/model_file.py                         # + ThreeMFFilamentUse.id (approved)
│   ├── services/printer_secrets.py                   # new: single access-code accessor (for 009)
│   ├── services/bambu_ftps.py                        # new: implicit FTPS upload/test/delete
│   ├── services/bambu_mqtt.py                        # + start_project_print, ensure_connected,
│   │                                                 #   tenant_id in config, print_error, thread-safe callbacks (bug fix)
│   ├── services/print_send_service.py                # new: prepare, confirm, list, proposal accept/dismiss
│   ├── services/print_send_tracker.py                # new: status → job transitions, proposal opening
│   ├── services/model_file_service.py                # + filament id in plate parse (approved)
│   ├── services/inventory_transaction.py             # + create_print_usage_transaction (approved, option b)
│   └── api/v1/print_sends.py                         # new router (prepare/confirm/list/get/consumption/test)
│   └── api/v1/printer_bambu.py                       # connect: accessor + tenant_id (approved, 2 lines)
└── tests/
    ├── api/test_print_sends_api.py
    ├── unit/test_print_send_service.py
    ├── unit/test_print_send_tracker.py
    ├── unit/test_bambu_ftps.py
    ├── unit/test_bambu_mqtt_start.py
    ├── unit/test_printer_secrets.py
    └── integration/test_print_sends_migration.py

frontend/src/
├── types/printSend.ts                                # new
├── types/printer.ts                                  # + PrinterConnection type (developer_mode, can_send_prints)
├── lib/api/printSends.ts                             # new
├── lib/api/printers.ts                               # + connection get/save, test-file-transfer
├── hooks/usePrintSends.ts                            # new
├── components/printers/PrinterConnectionDialog.tsx   # new: LAN settings + Developer Mode explanation + test
├── components/printers/SendPrintDialog.tsx           # new: pick file/plate/mapping → summary → confirm
├── components/printers/PrintSendSummary.tsx          # new
├── components/printers/PrinterSendsDialog.tsx        # new: recent sends + deduction proposal
├── components/printers/PrinterList.tsx               # + row actions (Connection, Send print, Sends)
└── (tests co-located *.test.tsx)
frontend/e2e/tests/printers/print-send.spec.ts        # new
```

**Structure Decision**: web application layout already in place. The send API
is a dedicated router `api/v1/print_sends.py` mounted under
`/api/v1/printers` (tag `printers-send`) rather than more endpoints in
`printers.py`, so the feature stays in its own files. No new frontend route:
the dialogs open from the existing Printers page.

## What later features find (extension points)

- **009 Preflight foundations (encryption)**: every access-code read of this
  feature goes through `services/printer_secrets.get_access_code(connection)`.
  009 changes that function (and adds `set_access_code`) to decrypt; the FTPS
  client, the MQTT config builder and the transfer test do not change. Other
  direct reads 009 must also switch: `api/v1/printer_bambu.py:connect_to_printer`
  (switched to the accessor by this feature), `api/v1/printer_ws.py` (Moonraker API key in `access_code`), and the
  connection create/update writes in `printer_bambu.py`. `cloud_token` is not
  read by this feature.
- **010 MCP server**: tools map 1:1 onto `POST .../prints/prepare` and
  `POST .../prints/confirm` (contract §MCP note). The confirm body already
  carries an explicit `acknowledge_warnings`; the `print` token scope only has
  to be checked by the auth dependency in front of these routes (and the
  consumption accept/dismiss routes). Nothing in the endpoints relies on a
  browser session.
- **009 print test results**: `print_sends.print_job_id` gives the exact file,
  plate and mapping of the job a `PrintTestResult` will point at.

## Out-of-zone files (all approved by the user via the orchestrator, 2026-11-23)

1. `schemas/model_file.py` + `services/model_file_service.py`: add the plate
   filament `id` (R3). **Approved.** Without the id the AMS mapping cannot be built, so a
   refusal means the orchestrator chooses between a second reader (contrary to
   principle III) and waiting; the feature does not work around it.
2. `services/inventory_transaction.py`: **approved 2026-11-23, option (b)** —
   add `create_print_usage_transaction` only; no change to existing methods or
   models, no inventory migration, new test file (R12).
3. `api/v1/printer_bambu.py`: connect through the accessor and pass `tenant_id`
   (R11, R6). **Approved.** Without it, the tracker only follows printers connected by this
   feature's confirm (which passes the tenant itself).

## Complexity Tracking

None.
