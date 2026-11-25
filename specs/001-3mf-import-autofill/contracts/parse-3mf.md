# Contract: Parse 3MF Metadata

## `POST /api/v1/models/files/parse-3mf`

Parses an uploaded `.3mf` file for print-time/weight/plate-count metadata
without creating or modifying any record. Mirrors the existing
`POST /api/v1/models/validate-local-path` pattern (auth-gated, no DB write,
no `model_id` required) rather than the existing
`POST /api/v1/models/{model_id}/files` pattern (which requires an existing
model).

**Auth**: Standard JWT auth + tenant resolution (`CurrentUser`,
`CurrentTenant`), per [CLAUDE.md](../../../CLAUDE.md) multi-tenant
convention — required for consistency with every other endpoint even
though this one does not query tenant-scoped data.

### Request

`multipart/form-data`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | file | yes | The `.3mf` file. Same size/type validation as the existing upload endpoint (`ALLOWED_EXTENSIONS`, `MAX_FILE_SIZE` in `model_file_service.py`). |

### Response `200 OK`

```json
{
  "print_time_minutes": 187,
  "filament_weight_grams": 42.5,
  "plate_count": 2,
  "source_plate_index": 1,
  "slicer_detected": "bambu_orca",
  "thumbnail_available": true
}
```

All fields except `thumbnail_available` are nullable; a fully-unparseable
file returns all nulls with `thumbnail_available: false` rather than an
error (FR-007, Story 2) — the response is always `200` as long as the
upload itself was a valid file.

### Response `400 Bad Request`

Reused from the existing file-validation path, for:
- File too large (`MAX_FILE_SIZE`)
- Extension not in `ALLOWED_EXTENSIONS`

A file with a valid `.3mf` extension whose *content* is actually corrupted
or not a real zip archive is **not** rejected with `400` — consistent with
`extract_3mf_thumbnail()`'s existing precedent (and `parse_3mf_metadata()`,
by the same design — research.md §3), it degrades gracefully to a `200`
with all metadata fields `null`, identical to "valid zip, no recognizable
metadata." Only extension/size fail fast; content-level corruption never
does, matching how the real upload endpoint already behaves today.

```json
{ "detail": "Invalid file type: .step. Allowed: .stl, .3mf, .gcode, .gco, .g" }
```

### Response `401 Unauthorized`

Standard auth failure, no body contract beyond the existing convention.

## Non-goals of this contract

- Does **not** create a `Model` or `ModelFile` record — purely informational
  (FR-003).
- Does **not** accept or return a `spool_id` — spool/material selection for
  the weight suggestion stays a separate, existing interaction
  (`POST /api/v1/models/{model_id}/materials`, FR-004a). This endpoint's
  `filament_weight_grams` is just a number the frontend carries forward.
