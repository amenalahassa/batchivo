# Data Model: Send a Print to a Bambu Lab Printer (spec 011)

One new tenant-scoped table, one new column on an existing table. Migration
`20261123_print_sends` (down_revision = current head `ideas_v1`, re-pointed from `catalogue_columns_v1` after 007 merged;
re-pointed if another feature merges first, so there is a single head).

## `printer_connections` (existing) — new column

| Column | Type | Rules |
|---|---|---|
| `developer_mode` | `Boolean NOT NULL DEFAULT false` | Operator-declared (FR-012). Send allowed only when true **and** `connection_type = 'bambu_lan'`. |

## `print_sends` (new)

A prepared send, its confirmation, its outcome and the spool deduction
proposal of the print it started.

| Column | Type | Rules |
|---|---|---|
| `id` | UUID PK | `UUIDMixin` |
| `tenant_id` | UUID FK tenants, CASCADE, indexed, NOT NULL | RLS (4 policies, `FORCE`) |
| `printer_id` | UUID FK printers, CASCADE, indexed, NOT NULL | Same tenant (checked in service) |
| `prepared_by_user_id` | UUID FK users, SET NULL | |
| `model_id` | UUID FK models, SET NULL, nullable | Set when the file is (or is attached to) a model's file |
| `model_file_id` | UUID FK model_files, SET NULL, nullable | Source when picked from a model |
| `upload_url` | String(500), nullable | Storage URL of an uploaded file not attached to a model; cleared when deleted |
| `file_name` | String(255) NOT NULL | Original name shown on the summary |
| `file_size` | BigInteger NOT NULL | |
| `file_md5` | String(32) NOT NULL | Sent with the start command |
| `remote_file_name` | String(255) NOT NULL | `batchivo-<8 hex of id>.gcode.3mf` |
| `plate_index` | Integer NOT NULL, ≥1 | |
| `ams_mapping` | JSONB NOT NULL | `[{filament_id:int, slot:{kind:"ams",ams_id:int,tray_id:int} \| {kind:"external"}}]` |
| `summary` | JSONB NOT NULL | Snapshot of what was shown: plate time/weight, lines (expected, slot, mapped spool, reported tray, warnings), blockers. Written once (Constitution VI). |
| `warning_count` | Integer NOT NULL DEFAULT 0 | Slot warnings needing acknowledgement |
| `token_hash` | String(64) NOT NULL, unique | SHA-256 hex of the confirmation token; token never stored |
| `expires_at` | timestamptz NOT NULL | `created_at + 5 min` |
| `status` | String(20) NOT NULL, indexed | see states below |
| `confirmed_at` | timestamptz, nullable | |
| `confirmed_by_user_id` | UUID FK users, SET NULL | |
| `warnings_acknowledged` | Boolean NOT NULL DEFAULT false | True when confirmed with acknowledgement |
| `error_message` | Text, nullable | Transfer or start failure cause (no secret) |
| `print_job_id` | UUID FK print_jobs, SET NULL, unique, nullable | The job this send started (FR-008, FR-018) |
| `printer_started_at` | timestamptz, nullable | First printer report showing our file running |
| `consumption_status` | String(20) NOT NULL DEFAULT `none` | `none` → `pending` → `accepted` \| `dismissed` |
| `consumption_lines` | JSONB, nullable | `[{filament_id, spool_id \| null, proposed_grams:"12.34", accepted_grams:"…" \| null, transaction_id \| null}]` |
| `consumption_decided_at` | timestamptz, nullable | |
| `consumption_decided_by_user_id` | UUID FK users, SET NULL | |
| `created_at`, `updated_at` | `TimestampMixin` | |

Indexes: `(tenant_id, printer_id, created_at desc)`, `(printer_id, status)`.
Check constraints: `plate_index >= 1`; `status IN (...)`;
`consumption_status IN ('none','pending','accepted','dismissed')`.

### Send states

```text
prepared ──confirm (valid, acknowledged)──▶ confirming ──upload ok + start ok──▶ started
    │                                            ├── upload fails ──▶ transfer_failed
    │                                            └── start fails  ──▶ start_failed
    └── (expires_at passed) — derived "expired", row stays prepared, token refused
```

- A missing acknowledgement leaves `prepared` (FR-004a).
- `confirming` is committed before any network call: a token starts at most one
  print (FR-006).
- `started` / `transfer_failed` / `start_failed` are terminal for the send.

### Print job outcome (via tracker, R6)

`PrintJob.status`: `printing` (created at start) → `completed` | `failed` |
`cancelled`, `completed_at` set. On entering any of these, when the send has
at least one consumption line, `consumption_status` becomes `pending`
(FR-020).

### Proposal rules

- Lines: one per plate filament with grams; `spool_id` from the AMS slot mapping
  at confirm time (null for external spool or unknown slot).
- Accept body gives, per line to deduct, `spool_id` (required) and
  `grams` (Decimal > 0, ≤ 99999.99); lines left out are not deducted. Accept and
  dismiss only from `pending`; the row is locked `FOR UPDATE` (exactly once,
  SC-006).
- Each accepted line writes one inventory transaction (R12) and stores its
  `transaction_id`.

## Relationships

- `PrintSend.printer` → `Printer` (many-to-one).
- `PrintSend.print_job` → `PrintJob` (one-to-one, via `print_sends.print_job_id`);
  `PrintJob` gains a read-only `print_send` back-reference (no column on
  `print_jobs`).
- `PrintSend.model` / `model_file` (optional).

## Existing structures read, not changed

- `ams_slot_mappings` (printer, ams_id, tray_id → spool_id).
- `spools` → `filament_types` (`color_hex`) → `material_types` (`code`).
- `BambuPrinterState.ams_units` (live tray report: type, colour, presence).
- `ThreeMFPlateMetadata` (plate time, weight, filaments) — gains filament `id`
  (R3, pending approval).
