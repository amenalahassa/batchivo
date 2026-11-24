---
description: "Tasks for spec 011 — send a print to a Bambu Lab printer, with confirmation"
---

# Tasks: Send a Print to a Bambu Lab Printer, with Confirmation

**Input**: `specs/011-bambu-print-send/` (plan.md, spec.md, research.md, data-model.md, contracts/print-send-api.md, quickstart.md)

**Tests**: mandatory (Constitution II). FTPS and MQTT are always mocked; no test contacts a printer.

**Organization**: by user story (US1 prepare, US2 confirm, US3 Developer Mode, US4 deduction proposal).

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [X] T001 Add `print_send_confirm_window_seconds: int = 300` (env `PRINT_SEND_CONFIRM_WINDOW_SECONDS`, must be > 0) to `backend/app/config.py` (one setting line, nothing else reordered)
- [X] T002 [P] Add a sample sliced Bambu project fixture builder in `backend/tests/fixtures/sliced_3mf.py`: builds in memory a zip with `Metadata/slice_info.config` (two plates; plate 1 = filament id 1 PLA #FF0000 30.10 g + id 3 PETG #00FF00 5.00 g, prediction 5700 s, weight 35.10) and `Metadata/plate_1.gcode`, `Metadata/plate_2.gcode`; plus an unsliced 3MF variant (no plate G-code)

---

## Phase 2: Foundational (blocks every story)

- [X] T003 Add the slicer filament id to the existing 3MF reader: `id: Optional[int] = Field(None, description="Slicer filament number (1-based) as in slice_info.config")` on `ThreeMFFilamentUse` in `backend/app/schemas/model_file.py`, filled from the `<filament id="…">` attribute in `_parse_bambu_orca_plate` in `backend/app/services/model_file_service.py` (non-integer → None); test in `backend/tests/unit/test_threemf_filament_id.py` (id parsed; missing/invalid id → None; existing fields unchanged) — approved
- [X] T004 [P] Create the single access-code accessor `get_access_code(connection) -> Optional[str]` in `backend/app/services/printer_secrets.py` (returns `connection.access_code` today; docstring says spec 009 switches it to decryption; never logs) and its test `backend/tests/unit/test_printer_secrets.py`
- [X] T005 [P] Create `PrintSend` model in `backend/app/models/print_send.py` per data-model.md: all columns verbatim (`file_name` String(255) NOT NULL, `remote_file_name` String(255) NOT NULL, `upload_url` String(500) nullable, `file_md5` String(32), `token_hash` String(64) unique, `plate_index` Integer NOT NULL ≥1, `status` String(20) indexed, `consumption_status` String(20) default `none`, JSONB `ams_mapping`/`summary`/`consumption_lines`, FKs with the listed ON DELETE rules, `print_job_id` unique), check constraints `plate_index >= 1`, `status IN ('prepared','confirming','started','transfer_failed','start_failed')`, `consumption_status IN ('none','pending','accepted','dismissed')`, indexes `(tenant_id, printer_id, created_at)` and `(printer_id, status)`; `PrintSendStatus`/`ConsumptionStatus` str enums; property `is_expired(now)`
- [X] T006 Add `developer_mode: Mapped[bool]` (`Boolean NOT NULL DEFAULT false`, server_default `false`) and property `can_send_prints` (`developer_mode and connection_type == 'bambu_lan'`) to `backend/app/models/printer_connection.py`; add read-only `print_send` relationship (`uselist=False`, `viewonly=True`, via `print_sends.print_job_id`) to `backend/app/models/print_job.py`; export `PrintSend` in `backend/app/models/__init__.py` (one line)
- [X] T007 Create migration `backend/alembic/versions/20261123_print_sends.py` (revision `print_sends_v1`, down_revision = current single head `catalogue_columns_v1`): add `printer_connections.developer_mode`, create `print_sends` with constraints/indexes, `ENABLE` + `FORCE ROW LEVEL SECURITY` and the four `tenant_isolation_*` policies (pattern of `DATA_filament_type_migration.py`); downgrade drops all; verify `poetry run alembic heads` shows one head
- [X] T008 Schema tests `backend/tests/integration/test_print_sends_migration.py`: PrintSend CRUD, unique `token_hash`, check constraints reject `plate_index=0` and unknown status, `print_job_id` SET NULL on job delete, cascade on printer delete, `developer_mode` defaults false
- [X] T009 [P] Fix the MQTT callback threading defect in `backend/app/services/bambu_mqtt.py` (R6): capture `asyncio.get_running_loop()` in `connect()` and schedule `_on_connect/_on_disconnect/_on_message` with `asyncio.run_coroutine_threadsafe`; add `tenant_id: Optional[UUID] = None` to `BambuConnectionConfig`; parse `print_error` into `BambuPrinterState.print_error: int = 0`; regression test in `backend/tests/unit/test_bambu_mqtt_start.py` calling the wired callback from a foreign thread and asserting the state is updated
- [X] T010 Pydantic schemas in `backend/app/schemas/print_send.py` per contract: `AmsSlotRef` (discriminated `kind` ams|external, `ams_id`/`tray_id` 0–3), `AmsMappingEntry`, `PrintSendLine`, `PrintSendWarning`, `PrintSendPrepared` (with `confirmation_token`), `PrintSendResponse` (no token), `PrintSendConfirm` (`confirmation_token` min_length 20, `acknowledge_warnings: bool = False`, `model_config = ConfigDict(extra="forbid")` so a confirmation cannot change file, plate or mapping — FR-007), `ConsumptionAcceptLine` (`grams: Decimal` > 0, ≤ 99999.99, serialised as string), `ConsumptionAccept` (min 1 line), `FileTransferTestResult`; add `developer_mode: bool = False` to `PrinterConnectionBase`/`PrinterConnectionUpdate` and `can_send_prints: bool` to `PrinterConnectionResponse` in `backend/app/schemas/printer_connection.py`

**Checkpoint**: models, migration, accessor, reader id and MQTT fix in place.

---

## Phase 3: User Story 1 — Prepare and review the summary (P1) 🎯 MVP

**Goal**: a send can be prepared from a stored or uploaded sliced file; the summary shows printer, plate, time, weight, per-filament slot/spool/report and warnings; nothing reaches the printer.

**Independent test**: quickstart scenario 1.

- [X] T011 [P] [US1] Mismatch rules as pure functions in `backend/app/services/print_send_service.py` (`material_key`, `colors_differ` with RGB distance > 80, `line_warnings`) with tests in `backend/tests/unit/test_print_send_service.py` (PLA vs PETG, `PLA-CF` vs `PLA`, colour at 80 vs 81, missing colour, empty slot, unknown spool, external spool → no AMS check)
- [X] T012 [US1] `PrintSendService.prepare(...)` in `backend/app/services/print_send_service.py`: load printer + connection (tenant-filtered), refuse unless `can_send_prints` (`send_not_available`); exactly one of model_file_id/upload; read bytes (model file via `ModelFileService.get_file_content`; upload stored via the model-file storage helpers under `print-sends/<tenant>/<send id>/`, or `ModelFileService.upload_file` when `attach_to_model_id`); refuse unsliced (no `Metadata/plate_<n>.gcode`), unknown plate (list available), filaments without id, mapping not covering exactly the plate's filaments or reusing a slot; build lines from `parse_3mf_metadata` (plate filaments), `AMSSlotMapping` + spool → filament_type → material_type (Batchivo side) and `get_bambu_mqtt_service().get_ams_status` (printer side, `None` when not connected); blockers `printer_busy`/`printer_unreachable` from live state; persist `PrintSend` (summary snapshot, md5, size, remote name `batchivo-<8 hex>.gcode.3mf`, `token_hash` = sha256 of `secrets.token_urlsafe(32)`, `expires_at` = now + window from settings); lazily delete this tenant's expired unconfirmed uploads; return prepared summary with the token
- [X] T013 [US1] Service tests for prepare in `backend/tests/unit/test_print_send_service.py`: summary content for plate 1 (time 95 min, weight "35.10", two lines), mismatch warning and `requires_acknowledgement`, unsliced file 422, plate 3 → 422 listing [1,2], duplicate slot 422, Developer Mode off → refused, upload stored then cleaned when expired, upload with `attach_to_model_id` becomes a `ModelFile` of that model, printer not connected → lines with `reported: null` and blocker `printer_unreachable`, FTPS/MQTT mocks never called, no `PrintJob` row
- [X] T014 [US1] Router `backend/app/api/v1/print_sends.py` (`APIRouter()`, module docstring): `POST /{printer_id}/prints/prepare` (multipart, `RequireMember`, `CurrentTenant`, `TenantDB`), `GET /{printer_id}/prints` (limit 1–50, default 20), `GET /{printer_id}/prints/{send_id}`; map service errors to the contract's status/`detail.code`; register in `backend/app/main.py` with prefix `{api_v1_prefix}/printers`, tag `printers-send` (add lines only)
- [X] T015 [US1] API tests `backend/tests/api/test_print_sends_api.py` (prepare/list/get): 201 with token, 401 no auth, 403 viewer, 413 file over 500 MB (size limit mocked low), 422 bad mapping JSON / both sources / neither, 404 unknown printer and other tenant's printer, 409 Developer Mode off, list excludes token and other tenants' sends
- [X] T016 [P] [US1] Frontend types `frontend/src/types/printSend.ts` and API client `frontend/src/lib/api/printSends.ts` (`prepare` as FormData, `confirm`, `list`, `get`, `acceptConsumption`, `dismissConsumption`) and hooks `frontend/src/hooks/usePrintSends.ts`
- [X] T017 [US1] `frontend/src/components/printers/PrintSendSummary.tsx`: printer, file, plate, time, weight, one row per filament (expected type + colour swatch + grams, slot label, mapped spool, printer report) with warning badges and blockers; test `PrintSendSummary.test.tsx`
- [X] T018 [US1] `frontend/src/components/printers/SendPrintDialog.tsx` step 1: choose source (model → its sliced files via existing models API, or upload `.gcode.3mf` with optional "attach to model"), plate, slot per filament (AMS 1–4 × slot 1–4, external), "Prepare" → shows `PrintSendSummary`; test `SendPrintDialog.test.tsx` (prepare request body, summary displayed, server 422 message shown)

**Checkpoint**: US1 independently demonstrable.

---

## Phase 4: User Story 2 — Confirm to start the print (P1)

**Goal**: a valid, acknowledged confirmation uploads, starts, and records a printing job; status follows the printer.

**Independent test**: quickstart scenarios 2–5.

- [X] T019 [P] [US2] Implicit FTPS client `backend/app/services/bambu_ftps.py`: `ImplicitFTPS(ftplib.FTP_TLS)` (TLS on connect, port 990, no cert verification, `prot_p`, data-channel session reuse), async wrappers via `asyncio.to_thread`: `upload(host, access_code, remote_name, data)`, `delete(host, access_code, remote_name)` (best-effort, never raises), `check_login(host, access_code) -> (ok, message)` (login + `nlst` + quit, never writes); errors wrapped in `BambuFileTransferError` with a message free of the access code; tests `backend/tests/unit/test_bambu_ftps.py` with `ftplib` mocked (stor called with remote name, login refused → error, timeout → error, access code absent from messages and logs)
- [X] T020 [P] [US2] `BambuMQTTService.start_project_print(printer_id, *, remote_file_name, plate_index, ams_mapping, md5)` and `ensure_connected(config, timeout=10.0) -> Optional[BambuPrinterState]` in `backend/app/services/bambu_mqtt.py` (R2 payload: `param "Metadata/plate_<n>.gcode"`, `url "ftp:///<name>"`, `subtask_name` stem, `use_ams`, mapping list by filament id − 1 with `ams_id*4+tray_id`, `254` external, `-1` unused; QoS 1); tests in `backend/tests/unit/test_bambu_mqtt_start.py` (exact payload, external spool 254, gaps −1, not connected → False, ensure_connected times out → None with paho mocked)
- [X] T021 [US2] `PrintSendService.confirm(printer_id, token, acknowledge_warnings)` in `backend/app/services/print_send_service.py`: lookup by sha256 + tenant + printer `FOR UPDATE` (404), expired (410), status ≠ prepared (409 `send_already_used`), connection no longer `can_send_prints` (409 `send_not_available`, FR-012), warnings without acknowledgement (409, row unchanged), build config via `get_access_code` with `tenant_id`, `ensure_connected` (503), busy (409), set `confirming` + confirmer + `warnings_acknowledged` and **commit**, read bytes, FTPS upload (fail → `transfer_failed`, error, 502), start command (fail → `start_failed`, best-effort delete, 502), create `PrintJob` (status printing, `assigned_printer_id`, `started_at`, `model_id`, `estimated_duration_hours` = plate minutes / 60 as Decimal, `reference` "print-send <id>"), set printer `current_status=printing`/`current_job_id`, send `started` + `print_job_id`, delete a stored upload; logs without secrets
- [X] T022 [US2] Confirm service tests in `backend/tests/unit/test_print_send_service.py`: happy path (upload + payload + job printing + printer status), missing acknowledgement keeps token usable, second confirm 409, expired 410 (frozen clock), other tenant 404, busy 409, unreachable 503, transfer failure → no job, start failure → no job + delete attempted, Developer Mode turned off after prepare → 409, access code never in logs (caplog); plus a static test that `start_project_print` is called only from `print_send_service.py` (SC-002: no other route starts a print)
- [X] T023 [US2] `POST /{printer_id}/prints/confirm` in `backend/app/api/v1/print_sends.py` and API tests in `backend/tests/api/test_print_sends_api.py` (200, 401, 403 viewer, 422 short token, 422 extra field such as `plate`, 404, 409 codes, 410, 502, 503)
- [X] T024 [US2] `PrintSendTracker` in `backend/app/services/print_send_tracker.py` (R6): registered on `status_update` via `register_print_send_tracker(service)`; per-printer last `gcode_state` in memory, acts only on change; tenant-scoped session (`async_session_maker` + `set_rls_context` with `config.tenant_id`; skip when unknown); file match on `current_file`/`subtask_name`; set `printer_started_at`; FINISH → completed, FAILED + 50348044 → cancelled, other FAILED → failed, IDLE after start → cancelled; conditional `UPDATE … WHERE status='printing'`; printer back to idle, `current_job_id` cleared; then opens the proposal (US4 hook, no-op until T033). Call `register_print_send_tracker(get_bambu_mqtt_service())` in the `main.py` lifespan (add lines only)
- [X] T025 [US2] Tracker tests `backend/tests/unit/test_print_send_tracker.py`: previous FINISH before start ignored, RUNNING then FINISH → completed with `completed_at`, cancelled code, failed, IDLE after start, unrelated file ignored, repeated message applies once, unknown tenant skipped
- [X] T026 [US2] Confirm step in `frontend/src/components/printers/SendPrintDialog.tsx`: countdown to `expires_at`, "I have checked the warnings" checkbox shown and required when `requires_acknowledgement`, "Start print" disabled while blockers exist, error codes mapped to messages (expired → "Prepare again"), success shows job started; tests in `SendPrintDialog.test.tsx` (button disabled until ticked, confirm body carries `acknowledge_warnings`, 410 message)

**Checkpoint**: US1 + US2 = the full send.

---

## Phase 5: User Story 3 — Developer Mode setting and transfer test (P2)

**Goal**: the connection settings explain Developer Mode, store it, test file transfer; "Send print" shows only when allowed.

**Independent test**: quickstart scenario 7.

- [X] T027 [US3] `POST /{printer_id}/connection/test-file-transfer` in `backend/app/api/v1/print_sends.py` (`RequireMember`, 404 no connection, 409 not Bambu LAN, uses `get_access_code` + `bambu_ftps.check_login`) with API tests in `backend/tests/api/test_print_sends_api.py` (ok, login refused → ok false, 401, 404, 409) and a test that the connection create/update endpoints persist `developer_mode` and return `can_send_prints` (masked access code unchanged)
- [X] T028 [US3] Use the accessor and pass `tenant_id` in `connect_to_printer` in `backend/app/api/v1/printer_bambu.py` (2 lines) with a test in `backend/tests/api/test_print_sends_api.py` asserting the MQTT config gets the tenant — approved
- [X] T029 [P] [US3] Connection API client and types: `getConnection`, `saveConnection` (omits `access_code` when not edited), `testFileTransfer` in `frontend/src/lib/api/printers.ts`; `PrinterConnection` type with `developer_mode`, `can_send_prints` in `frontend/src/types/printer.ts`
- [X] T030 [US3] `frontend/src/components/printers/PrinterConnectionDialog.tsx`: Bambu LAN fields (serial, IP, access code as password field "leave blank to keep"), Developer Mode switch with the explanation (enables sending from Batchivo; disables Bambu cloud access, Bambu Handy and cloud sending; alternative Bambu Studio / Bambu Connect), "Test file transfer" button showing the result without blocking save; test `PrinterConnectionDialog.test.tsx`
- [X] T031 [US3] Row actions in `frontend/src/components/printers/PrinterList.tsx`: "Connection" (opens dialog), "Send print" only when the printer's connection has `can_send_prints`; test in new `frontend/src/components/printers/PrinterList.test.tsx` (Send print hidden when Developer Mode off, shown when on)

---

## Phase 6: User Story 4 — Spool deduction proposal (P3)

**Goal**: a finished sent print proposes per-spool deductions; nothing moves until accepted.

**Independent test**: quickstart scenario 6.

- [X] T032 [US4] Add `create_print_usage_transaction(spool, weight_used: Decimal, print_job_id: UUID, print_send_id: UUID)` to `backend/app/services/inventory_transaction.py` (atomic `current_weight` decrement + `create_transaction(USAGE, metadata={"print_job_id","print_send_id"}, description naming the job)`), test in `backend/tests/unit/test_inventory_print_usage.py` — approved (option b): do not modify existing methods or inventory models, no inventory migration
- [X] T033 [US4] Proposal opening in `backend/app/services/print_send_tracker.py`: on job end, build `consumption_lines` from the send summary (filament_id, mapped spool id or null, `proposed_grams` as 2-place Decimal string) and set `consumption_status='pending'` when at least one line; tests in `backend/tests/unit/test_print_send_tracker.py` (pending after FINISH and after FAILED, no spool weight changed)
- [X] T034 [US4] `PrintSendService.accept_consumption(send_id, lines)` / `dismiss_consumption(send_id)` in `backend/app/services/print_send_service.py` (row `FOR UPDATE`, only from `pending` → 409 otherwise, lines must reference plate filaments, spool of this tenant, grams Decimal > 0; one inventory transaction per line, store `accepted_grams` + `transaction_id`, decided by/at) and endpoints `POST /{printer_id}/prints/{send_id}/consumption/accept|dismiss` in `backend/app/api/v1/print_sends.py`; tests in `backend/tests/unit/test_print_send_service.py` and `backend/tests/api/test_print_sends_api.py` (corrected amount applied, left-out line not deducted, second accept 409, dismiss moves nothing, other tenant spool 422, 401/404)
- [X] T035 [US4] `frontend/src/components/printers/PrinterSendsDialog.tsx`: recent sends (status, plate, acknowledged warnings, job status/times) and, for a pending proposal, editable grams per spool, spool picker for lines without spool, Accept / Dismiss; add the "Sends" row action opening it in `frontend/src/components/printers/PrinterList.tsx`; test `PrinterSendsDialog.test.tsx`

---

## Phase 7: Polish & cross-cutting

- [ ] T036 [P] e2e `frontend/e2e/tests/printers/print-send.spec.ts` (user from `registerAndLogin`, local backend only): create printer + Bambu LAN connection with Developer Mode off → no "Send print"; turn it on → "Send print" visible; upload the sliced fixture, prepare → summary with plate time and slot lines; confirm → printer unreachable message (no printer on the network), no job created
- [X] T037 [P] Operator doc: Developer Mode trade-off and the send flow in `docs-site/docs/guides/send-print-to-bambu.md`
- [X] T038 Update `specs/backlog.md` (011 block only, Status line) and record approvals/deviations in `specs/011-bambu-print-send/plan.md`
- [ ] T039 Run gates: `cd backend; poetry run pytest` (after orchestrator go-ahead for the test DB), `poetry run ruff check`, `poetry run ruff format --check`; `cd frontend; npm run test:run; npm run lint; npm run typecheck`; targeted e2e T036

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → stories. T003 (approval) blocks T012. T005 → T006 → T007 → T008. T009 before T020/T024.
- US1 (T011–T018) before US2 (T021 needs prepared sends). US3 backend (T027) independent of US2; US3 UI T031 needs T018 and T030. US4 needs T024.
- T032 decides T034's call.

## Parallel Examples

- Phase 2: T004, T005, T009 together.
- US2: T019 and T020 together, then T021.
- Frontend: T016 alongside backend US1; T029 alongside T027.

## Implementation Strategy

MVP = US1 + US2 (prepare + confirm + tracking): the backlog's core promise. Then US3 (setting/explanation; Developer Mode column already exists from Phase 2 so the API gate works from the start), then US4.

## Phase 8: Convergence

- [X] T040 In `PrintSendService.confirm` (`backend/app/services/print_send_service.py`), refuse with 409 `printer_busy` when another send on the same printer is `confirming`, or is `started` with its print job still `printing`, even if the printer's cached MQTT state does not show it busy yet, so two quick confirmations cannot both start; tests in `backend/tests/unit/test_print_send_service.py` per spec Edge Cases "Two operators prepare sends to the same printer" (partial)
- [X] T041 Add a spool picker to each proposal line in `frontend/src/components/printers/PrinterSendsDialog.tsx`, so a line with no recorded spool (external spool holder or unknown slot) can be given a spool before it is deducted, or left out; test in `PrinterSendsDialog.test.tsx` per US4/AC5 and T035 (partial)
- [X] T042 Return who confirmed a send (`confirmed_by` user id and name) in `PrintSendResponse` (`backend/app/schemas/print_send.py`, `to_response` in `print_send_service.py`) and show, in `frontend/src/components/printers/PrinterSendsDialog.tsx`, each confirmed send's slot mapping (filament → slot) and who confirmed it; tests in `backend/tests/api/test_print_sends_api.py` and `PrinterSendsDialog.test.tsx` per FR-018 (partial)

## Phase 9: Convergence

- [X] T043 Stop counting a send left `confirming` for more than 30 minutes as in flight in `_send_in_flight` (`backend/app/services/print_send_service.py`), so a crash between the token's consumption and the outcome cannot block the printer for good; test in `backend/tests/unit/test_print_send_service.py` per spec Edge Cases "Two operators" and T040 (partial)
- [X] T044 Load every active spool page by page for the proposal's spool picker in `frontend/src/components/printers/PrinterSendsDialog.tsx` (the spool list API caps a page at 100); test in `PrinterSendsDialog.test.tsx` per US4/AC5 and T041 (partial)
