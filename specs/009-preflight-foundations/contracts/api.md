# API contract: Preflight foundations (spec 009)

All under `/api/v1`, JWT or personal API token (`bvt_`), tenant from the credential, `TenantDB`
session. Viewers read; writes need `RequireMember`. Errors: 401 unauthenticated, 403 role/scope,
404 not found in this shop, 409 conflict, 422 validation (detail names the field). Token scope in
brackets: `[read]`, `[write]`, `[jwt]` = tokens refused.

## Design briefs (`app/api/v1/design_briefs.py`)

| Method | Path | Handler | Scope | Result |
|---|---|---|---|---|
| GET | `/ideas/{idea_id}/design-brief` | `get_idea_brief` | read | 200 `DesignBrief`, 404 if idea or brief absent |
| POST | `/ideas/{idea_id}/design-brief` | `start_idea_brief` | write | 201 new, 200 existing |
| GET | `/models/{model_id}/design-brief` | `get_model_brief` | read | 200 (own brief, else the source idea's), 404 |
| POST | `/models/{model_id}/design-brief` | `start_model_brief` | write | 201 new; 200 existing (own or source idea's, then stamped with model_id) |
| GET | `/design-briefs/{brief_id}` | `get_brief` | read | 200 |
| PATCH | `/design-briefs/{brief_id}` | `update_brief` | write | 200 `DesignBriefUpdateResult` |
| GET | `/design-briefs/{brief_id}/revisions?part=intent\|risk\|plan&skip&limit` | `list_brief_revisions` | read | 200 list newest first |
| DELETE | `/design-briefs/{brief_id}` | `delete_brief` | jwt | 204 (member) |

`POST` start bodies: `{}` or `{"intent": {...}}` / `{"intent_yaml": "..."}` (optional first intent).

`PATCH` body (any subset; at least one field):

```json
{
  "intent": {"schema_version": 1, "...": "..."},
  "intent_yaml": "schema_version: 1\n...",
  "risk": {"risk_class": "moyen", "risk_md": "# Risque ...", "triage": {"...": "..."}},
  "plan_md": "# Plan ...",
  "params": {"wall_mm": {"value": 1.8, "unit": "mm", "provenance": "dfam.wall.extrusion-multiple"}},
  "params_yaml": "wall_mm: ...",
  "steps": {"risk": "done", "plan": "in_progress"}
}
```

`intent` and `intent_yaml` are exclusive (422 if both); same for `params`/`params_yaml`. A `risk`
object replaces the whole risk part (absent keys → null). Unknown step or status → 422.

`DesignBrief` response:

```json
{
  "id": "uuid", "idea_id": "uuid|null", "model_id": "uuid|null",
  "idea_title": "str|null", "model_name": "str|null",
  "intent": {}, "intent_schema_version": 1,
  "risk_class": "moyen|null", "risk_md": "str|null", "triage": {},
  "plan_md": "str|null", "params": {}, "params_updated_at": "dt|null",
  "steps": [{"step": "intent", "status": "done", "updated_at": "dt|null", "updated_by": {"id": "uuid", "name": "str"}}],
  "validation": {"to_clarify": ["loads[0].value"], "unconfirmed": [{"field": "loads[0]", "status": "déduit"}], "missing": []},
  "revision_counts": {"intent": 3, "risk": 1, "plan": 0},
  "created_by": {}, "updated_by": {}, "created_at": "dt", "updated_at": "dt"
}
```

`steps` always lists the 14 steps in Preflight order. `DesignBriefUpdateResult` = `DesignBrief` +
`"created_revisions": ["intent", "risk"]`.

Revision: `{"id", "part", "content", "schema_version", "author": {id,name}|null, "created_at"}`.

Intent validation errors (422): `{"detail": [{"loc": ["intent", "loads", 0, "duration"], "msg":
"must be one of cyclic, permanent, short, shock or [À PRÉCISER]"}]}`.

## Model file notes (extended, `app/api/v1/model_file_notes.py`)

- `POST /models/{model_id}/files/{file_id}/notes` body adds optional `source`, `rule_id`,
  `severity` (accepts `attention`, `échec`), `measured_value`, `expected_value` (decimal; returned as decimal strings, kept exactly), `value_unit`.
- `PATCH /models/{model_id}/file-notes/{note_id}` adds `status: "dismissed"` with required
  `dismissal_reason` (422 without), and editable `severity`, `rule_id`, `measured_value`,
  `expected_value`, `value_unit`. Dismissing a non-open note → 409 (same rule error as resolve).
- `GET /models/{model_id}/file-notes` adds `source` and `severity` query filters; `status` accepts
  `dismissed`.
- `NoteResponse` adds `source`, `rule_id`, `severity`, `measured_value`, `expected_value`,
  `value_unit`, `dismissal_reason`, `dismissed_at`, `dismissed_by`.
- Carry-forward copies `source`, `rule_id`, `severity`, values and unit.

## Calibrations (`app/api/v1/calibrations.py`)

| Method | Path | Handler | Scope |
|---|---|---|---|
| GET | `/printers/{printer_id}/calibrations?current_only&fit_type&orientation&material_type_id&filament_type_id&skip&limit` | `list_printer_calibrations` | read |
| POST | `/printers/{printer_id}/calibrations` | `record_calibration` | write |
| GET | `/calibrations/lookup?printer_id&fit_type&orientation&material_type_id\|material&filament_type_id` | `lookup_calibration` | read |
| GET | `/calibrations/atelier?printer_id` | `export_atelier_calibrations` | read |
| GET | `/calibrations/{calibration_id}` | `get_calibration` | read |

`POST` body: `{"material_type_id" | "material": "PLA", "filament_type_id"?, "orientation",
"fit_type", "value_mm": "0.200" | 0.2, "provenance", "source_print_job_id"?,
"source_test_result_id"?, "measured_at"?, "notes"?}` → 201 `Calibration`; 409 when a concurrent
record won the race. No PUT/PATCH/DELETE (405).

`Calibration`: `{id, printer_id, printer_name, material_type_id, material_code, filament_type_id,
filament_label, orientation, fit_type, value_mm: "0.150", provenance, source_print_job_id,
source_test_result_id, measured_at, notes, recorded_by, superseded_by_id, superseded_at,
is_current, created_at}`.

Lookup: `{"found": true, "calibration": {...}, "matched_on": "filament|material"}` or
`{"found": false, "calibration": null, "matched_on": null}`; unknown material code → 422.

Atelier export: `{"calibrations": [{"id", "printer": "<printer name>", "printer_id", "material":
"PLA", "filament": "Brand Colour|null", "orientation", "fit", "value_mm": 0.15, "provenance",
"measured_at": "ISO", "source_print_job_id"}]}` — current values only, `value_mm` as a JSON
number for `pf.py` compatibility.

## Print test results (`app/api/v1/print_test_results.py`)

| Method | Path | Handler | Scope |
|---|---|---|---|
| POST | `/print-test-results` | `create_test_result` | write |
| GET | `/print-test-results?model_id&model_file_version_id&print_job_id&printer_id&outcome&kind&skip&limit` | `list_test_results` | read |
| GET | `/print-test-results/{result_id}` | `get_test_result` | read |
| PATCH | `/print-test-results/{result_id}` | `update_test_result` | write |
| POST | `/print-test-results/{result_id}/photo` (multipart `file`) | `upload_test_result_photo` | write |
| GET | `/print-test-results/{result_id}/photo?variant=full\|thumb` | `get_test_result_photo` | read |

Create body: `{kind, outcome, model_id?, model_file_version_id?, print_job_id?, printer_id?,
material_type_id? | material?, filament_type_id?, orientation?, measurements: [{name, value,
unit?, expected?, ...}], failure_mode?, notes?}`. Patch: `outcome`, `measurements`,
`failure_mode`, `notes`. Response adds `id`, `photo_available`, `recorded_by`, `updated_by`,
timestamps, `model_name`, `version_label`.

## Printer connection (changed, `app/schemas/printer_connection.py`)

`PrinterConnectionResponse` adds `access_code_state` and `cloud_token_state`
(`set|unset|unreadable`). Masking unchanged. Requests unchanged.
