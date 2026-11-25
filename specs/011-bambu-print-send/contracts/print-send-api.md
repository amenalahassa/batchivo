# API Contract: Print send (spec 011)

Base: `/api/v1/printers`. Auth: Bearer JWT (later also a spec 010 API token with
the `print` scope — the endpoints take nothing browser-specific). Every endpoint
is tenant-scoped (`CurrentTenant`, `TenantDB`); another tenant's printer or send
is a 404. Weights are decimal strings. Times are ISO 8601 UTC.

## POST `/{printer_id}/prints/prepare` — role: member

`multipart/form-data`:

| Field | Type | Rules |
|---|---|---|
| `plate` | int | ≥ 1, must exist in the file |
| `ams_mapping` | JSON string | `[{"filament_id":1,"slot":{"kind":"ams","ams_id":0,"tray_id":2}}, {"filament_id":2,"slot":{"kind":"external"}}]` — one entry per plate filament, no duplicate slot, `ams_id` 0–3, `tray_id` 0–3 |
| `model_file_id` | UUID, optional | exactly one of `model_file_id` / `file` |
| `file` | file, optional | `.gcode.3mf` (sliced: has `Metadata/plate_<n>.gcode`), ≤ 500 MB |
| `attach_to_model_id` | UUID, optional | with `file` only: store it as that model's file |

`201` → `PrintSendPrepared`:

```json
{
  "id": "uuid",
  "confirmation_token": "opaque, shown once",
  "expires_at": "2026-11-23T10:05:00Z",
  "status": "prepared",
  "printer": {"id": "uuid", "name": "X1C"},
  "file": {"name": "dragon.gcode.3mf", "model_id": "uuid|null", "model_file_id": "uuid|null"},
  "plate": {"index": 2, "print_time_minutes": 95, "filament_weight_grams": "41.20"},
  "lines": [
    {
      "filament_id": 1,
      "expected": {"type": "PLA", "color": "#FF0000", "grams": "30.10"},
      "slot": {"kind": "ams", "ams_id": 0, "tray_id": 2, "label": "AMS 1 · slot 3"},
      "mapped_spool": {"id": "uuid", "spool_id": "SP-0042", "material": "PETG", "color": "#FF0000", "current_weight": "640.00"},
      "reported": {"type": "PETG", "color": "#FF0000", "present": true},
      "warnings": ["material_mismatch", "reported_mismatch"]
    }
  ],
  "warnings": [{"code": "material_mismatch", "filament_id": 1, "message": "Plate expects PLA, slot holds PETG"}],
  "blockers": [{"code": "printer_busy", "message": "Printer is printing"}],
  "requires_acknowledgement": true
}
```

Errors: `401`; `403` (viewer); `404` printer; `409 send_not_available`
(Developer Mode off / not Bambu LAN / no connection); `422` (not sliced, plate
not in file — detail lists available plates —, bad mapping, both/neither file
sources, filament without id); `413` file too large.

Side effects: none on the printer; no print job (FR-002).

## POST `/{printer_id}/prints/confirm` — role: member

JSON `{"confirmation_token": "...", "acknowledge_warnings": false}`.

`200` → `PrintSendResponse` with `status: "started"`, `print_job_id`.

Errors (all leave the printer untouched unless stated):

| Code | `detail.code` | When |
|---|---|---|
| 404 | `send_not_found` | unknown token, other tenant, other printer |
| 410 | `send_expired` | past `expires_at` |
| 409 | `send_already_used` | status not `prepared` |
| 409 | `acknowledgement_required` | warnings and `acknowledge_warnings` false (send stays usable) |
| 409 | `printer_busy` | printer printing or paused |
| 503 | `printer_unreachable` | no status within 10 s |
| 502 | `transfer_failed` | upload failed; send `transfer_failed`, no job |
| 502 | `start_failed` | start command failed; send `start_failed`, no job, remote file deleted best-effort |

## GET `/{printer_id}/prints` — role: viewer+

Query `limit` (1–50, default 20). `200` → `{items: PrintSendResponse[]}`,
newest first. `PrintSendResponse` = the prepared summary fields **without**
the token, plus `confirmed_at`, `warnings_acknowledged`, `error_message`,
`print_job: {id, status, started_at, completed_at} | null`,
`consumption: {status, lines[]}`.

## GET `/{printer_id}/prints/{send_id}` — role: viewer+

`200` → `PrintSendResponse`; `404`.

## POST `/{printer_id}/prints/{send_id}/consumption/accept` — role: member

JSON `{"lines": [{"filament_id": 1, "spool_id": "uuid", "grams": "28.50"}]}`
(lines left out are not deducted; at least one line).
`200` → `PrintSendResponse` (`consumption.status = accepted`). Errors: `404`;
`409 consumption_not_pending`; `422` (grams ≤ 0, unknown filament, spool of
another tenant).

## POST `/{printer_id}/prints/{send_id}/consumption/dismiss` — role: member

`200` → `PrintSendResponse` (`dismissed`); `404`; `409 consumption_not_pending`.

## POST `/{printer_id}/connection/test-file-transfer` — role: member

`200` → `{"ok": true, "message": "Printer accepted the file connection"}` or
`{"ok": false, "message": "Login refused: check the access code"}`.
`404` no connection; `409` not a Bambu LAN connection. Never writes a file.

## Changed: connection schemas (`printer_bambu.py` endpoints, unchanged routes)

`PrinterConnectionCreate/Update/Response` gain `developer_mode: bool`
(default false). `PrinterConnectionResponse` gains `can_send_prints: bool`
(`developer_mode && connection_type == "bambu_lan"`).

## MCP note (spec 010)

An agent tool `printers.send_print` = prepare (returns summary + token) and a
separate `printers.confirm_print` taking the token and an explicit
`acknowledge_warnings`; the agent must surface the summary before confirming.
No other route starts a print.
