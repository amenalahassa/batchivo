# Research: Send a Print to a Bambu Lab Printer (spec 011)

Decisions taken while planning, with what was weighed. Deviations from
`docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §8 are marked **Deviation**.

## R1. File transfer protocol

- **Decision**: implicit FTPS on port 990, user `bblp`, password = LAN access
  code, TLS without certificate verification (the printer's certificate is
  self-signed, as for MQTT today), protected data channel (`PROT P`) with TLS
  session reuse on the data connection. Upload to the printer's storage root as
  `batchivo-<send short id>.gcode.3mf`. Python standard library `ftplib.FTP_TLS`
  subclassed for implicit TLS and session reuse; run in `asyncio.to_thread` so
  the event loop is not blocked. No new dependency.
- **Rationale**: this is the transport Bambu printers expose in LAN mode with
  Developer Mode, the one used by Bambu Studio's LAN send and by the open-source
  integrations read as reference (GPL code read only, nothing copied; Batchivo
  is MIT). X1-series firmware refuses a data channel that does not reuse the
  control channel's TLS session, hence the subclass.
- **Alternatives**: `aioftp` (no implicit-TLS session reuse, new dependency);
  `pycurl` (native dependency on Alpine). Rejected.

## R2. Start command

- **Decision**: MQTT `print.command = "project_file"` on
  `device/<serial>/request`, QoS 1, with `param = "Metadata/plate_<n>.gcode"`,
  `url = "ftp:///<remote file name>"`, `subtask_name` = remote file stem,
  `use_ams` = true when any filament maps to an AMS slot, `ams_mapping` = list
  indexed by the plate's filament number (slicer filament id − 1), each value
  the global tray index `ams_id * 4 + tray_id`, `254` for the external spool,
  `-1` for a filament the plate does not use; `timelapse=false`,
  `bed_levelling=true`, `flow_cali=true`, `vibration_cali=true`,
  `layer_inspect=false`, `bed_type="auto"`, `md5` of the file, ids `"0"`.
- **Rationale**: matches the community-documented LAN protocol already used by
  `bambu_mqtt.py`; defaults are the slicer's (spec assumption).
- **Alternatives**: `gcode_file` command (prints a bare G-code, no AMS
  mapping) — rejected, the feature is about plates and AMS slots.

## R3. Slicer filament number per plate (dependency on spec 004 reader)

- **Decision**: reuse the existing 3MF reader (`parse_3mf_metadata`,
  `ThreeMFPlateMetadata`) for plate time, weight and filaments, and add the
  slicer filament `id` to `ThreeMFFilamentUse` (additive, optional field).
- **Rationale**: Constitution III — one reader of `slice_info.config`. A second
  parser in the send service would be a parallel implementation.
- **Status**: approved (out-of-zone files `schemas/model_file.py`,
  `services/model_file_service.py`). A sliced plate whose filaments carry no id
  is refused at prepare with "re-slice with Bambu Studio".

## R4. Two-step API and the confirmation reference

- **Decision**: `POST /api/v1/printers/{id}/prints/prepare` creates a
  `print_sends` row and returns the summary plus a confirmation token (32
  random bytes, URL-safe) shown once; only its SHA-256 is stored.
  `POST /api/v1/printers/{id}/prints/confirm` takes `{confirmation_token,
  acknowledge_warnings}`. The send row is locked `FOR UPDATE`, checked
  (tenant, printer, status `prepared`, not expired, acknowledgement when
  warnings exist), then moved to `confirming` and committed **before** any
  network call, so a token can never start two prints.
- **Rationale**: FR-005/006/007; an MCP client (spec 010, `print` scope) calls
  the same two endpoints with the same body — nothing is browser-specific (no
  cookie, no form state). The token is the only thing a client must carry
  between the calls.
- **Window**: 5 minutes (`PRINT_SEND_CONFIRM_WINDOW_SECONDS`, default 300).
- **Missing acknowledgement**: refused with 409 `acknowledgement_required`,
  the row stays `prepared` (token reusable within the window, FR-004a).

## R5. Atomicity: no half-started job

- **Decision**: order = consume token → upload → start command → create the
  `PrintJob` (status `printing`) and link it. The job is created only after the
  start command succeeded; a transfer failure sets the send `transfer_failed`,
  a start failure sets `start_failed` and deletes the remote file best-effort.
  Each failure leaves no job (FR-009, SC-004).
- **Alternatives**: create the job first as `queued` then roll back — rejected:
  a crash between the steps would leave a queued job behind.

## R6. Following the print (status → job)

- **Pre-existing defect found**: `BambuMQTTService.connect` wires paho callbacks
  as `asyncio.create_task(...)`, but paho calls them from its own network thread
  where no event loop runs, so every status message raises and is dropped.
  `status_update` has no listener anywhere. Without fixing this, FR-010 cannot
  work. **Decision**: fix inside `bambu_mqtt.py` (this feature's zone): capture
  the running loop in `connect()` and schedule callbacks with
  `asyncio.run_coroutine_threadsafe`. Regression test added.
- **Decision**: a `PrintSendTracker` registers on `status_update` at
  application start (one line in `main.py` lifespan). It reacts only when a
  printer's `gcode_state` changes (kept in memory per printer), then loads the
  active send for that printer through a tenant-scoped session (tenant id
  carried in `BambuConnectionConfig`). Transitions:
  - `PREPARE`/`RUNNING`/`PAUSE` with our file (`gcode_file` or `subtask_name`
    matches) → send `printer_started_at` set;
  - `FINISH` with our file → job `completed`;
  - `FAILED` with `print_error == 50348044` (task cancelled) → job `cancelled`;
    other `FAILED` → job `failed`;
  - `IDLE` after start seen → `cancelled`.
  Updates are conditional (`WHERE status = 'printing'`), so two pods holding
  a connection to the same printer cannot apply a transition twice.
- **Why file matching**: right after the start command the printer still
  reports the previous print's `FINISH`; matching our file name prevents
  completing the new job instantly.
- **Printer status** (`printers.current_status`, `current_job_id`) moves with the
  job, as `PrintQueueService` does.

## R7. Two backend pods

- **Constraint found**: the deployment runs 2 backend replicas and the MQTT
  client is an in-process singleton; `connect` may have run on the other pod.
- **Decision**: confirm calls `ensure_connected(config, timeout=10s)`: reuses
  this pod's connection or opens one and waits for the first status report
  (gives the busy check). Uploaded files are stored through the shared storage
  (S3 in production, local in dev) so prepare and confirm may run on different
  pods. The tracker is idempotent (R6).
- **Consequence**: a printer may hold one MQTT client per pod; Bambu LAN
  firmware accepts several local clients. Noted as a risk.

## R8. Uploaded files

- **Decision**: an uploaded sliced file is stored with the model-file storage
  helpers of `ModelFileService` (same local/S3 backend, key
  `print-sends/<tenant>/<send id>/<name>`), not as a `ModelFile`, unless the
  operator picks "attach to model", in which case it goes through
  `ModelFileService.upload_file` and becomes that model's file. A stored
  upload is deleted when the send reaches a terminal state (started, failed)
  and expired unconfirmed uploads are deleted lazily at the tenant's next
  prepare. Size limit: the model-file limit (500 MB).
- **Alternatives**: keeping bytes in the database — rejected (size); local temp
  dir — rejected (two pods). The generic owner-keyed storage is 007's work;
  this feature does not touch `image_storage.py`.

## R9. Mismatch rules

- **Material**: compare the plate filament type with the spool's material type
  code (Batchivo mapping) and with the printer's reported tray type; key =
  first word, upper-cased (`PLA`, `PETG`, `PLA-CF`). Different keys → warning.
- **Colour**: "clearly different" = Euclidean RGB distance > 80 (of 441);
  missing colour on either side → no colour warning.
- **Codes**: `material_mismatch`, `color_mismatch`, `empty_slot` (printer
  reports no filament), `unknown_spool` (no spool mapped in Batchivo),
  `reported_mismatch` (printer's tray report differs from the plate).
  Blockers (not acknowledgeable): `printer_busy`, `printer_unreachable`.
- **Acknowledgement**: required when any warning exists (FR-004a).

## R10. Developer Mode and the transfer test

- **Decision**: `printer_connections.developer_mode` boolean, default false,
  set by the operator (connection settings, admin role as today). `POST
  /printers/{id}/connection/test-file-transfer` (member role) logs in over
  FTPS, lists the root and quits; never writes. Result `{ok, message}`.
- **Send visibility**: `developer_mode && connection_type == bambu_lan`.

## R11. Single access point for the access code (for spec 009)

- **Decision**: `services/printer_secrets.py::get_access_code(connection)`
  returns the plaintext column today. Every read in this feature goes
  through it; 009 switches it to decryption. Approved: used
  in `printer_bambu.connect_to_printer` too. Remaining direct read:
  `printer_ws.py` (Moonraker API key stored in `access_code`) — listed for 009.
  The code is never logged nor returned.

## R12. Spool deduction proposal (clarification 5 = C)

- `variance_service` handles learned cost estimates (`estimate_revisions`), not
  stock; it is not the right mechanism and is not touched.
- The stock trail is `InventoryTransactionService`. The proposal (lines,
  status) lives on `print_sends`. On accept, each line writes through the
  inventory service. **Pending orchestrator decision**:
  (a) call `create_adjustment_transaction` as is (entry typed ADJUSTMENT), or
  (b) add `create_print_usage_transaction` (USAGE without production run) to
  `services/inventory_transaction.py`. **Approved: option (b)**, no change to
  existing methods or models, no inventory migration.
- Weights are `Decimal` (grams, 2 places) end to end, strings on the wire.

## R13. Roles

- Prepare, confirm, list sends, accept/dismiss proposal, transfer test:
  `RequireMember` (clarification 3). Developer Mode setting: existing
  connection endpoints (`RequireAdmin`), unchanged.

## R14. Session dependency

- New endpoints use `TenantDB` (`get_tenant_db`) and `CurrentTenant`, unlike
  the older `printer_bambu.py` endpoints which use `get_db`; tenant filters are
  also applied in queries (Constitution I, belt and braces).
