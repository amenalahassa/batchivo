# API Contract: Model File Versions and Notes

Base: `/api/v1/models/{model_id}`. All routes: Bearer JWT, tenant from token, `get_tenant_db`.
Writes need member role or above (`RequireMember`); reads any tenant user. Money is not involved;
dimensions are decimal strings in mm, as in the existing measurement payloads.

Common errors: 401 no/invalid token · 403 role too low (writes) · 404 model/version/file/note not
in tenant · 422 validation.

## Versions

### GET `/file-versions`
200 → `FileVersion[]`, newest `sequence` first.

```json
{
  "id": "uuid", "sequence": 2, "label": "2", "note": "thicker walls",
  "is_active": false, "print_file_id": "uuid|null",
  "created_by": {"id": "uuid", "name": "Konrad"} , "created_at": "2026-11-03T10:00:00Z",
  "files": [ModelFileResponse, "..."],
  "open_note_count": 1
}
```

### POST `/file-versions`
Body `{ "label"?: string(1..50), "note"?: string(..2000) }` → 201 `FileVersion`.
Created inactive unless the model has no version yet (then active).

### PATCH `/file-versions/{version_id}`
Body `{ "label"?, "note"?, "print_file_id"? }` → 200 `FileVersion`.
`print_file_id` on the **active** version → 409 `{"detail": ..., "code": "review_required"}`; the
client uses the activation preview/apply instead (FR-012a). On an inactive version it is set
directly. 422 if the file is not in the version or not sliced.

### GET `/file-versions/{version_id}/activation-preview?print_file_id=`
`print_file_id` optional (preview a different print file within the version).
200:

```json
{
  "version_id": "uuid", "print_file_id": "uuid|null", "dimension_file_id": "uuid|null",
  "rows": [
    {"field": "print_time_minutes", "target": "model_printer_config|model",
     "current": "95", "proposed": "112", "selectable": true},
    {"field": "prints_per_plate", "target": "model", "current": "4", "proposed": "6", "selectable": true},
    {"field": "weight_grams", "target": "model_material", "current": "38.20", "proposed": "41.00",
     "selectable": true, "reason": null},
    {"field": "dimensions", "target": "dimensions",
     "current": {"length_mm": "80.0", "width_mm": "60.0", "height_mm": "40.0", "source": "entered"},
     "proposed": {"length_mm": "82.0", "width_mm": "60.0", "height_mm": "41.5"}, "selectable": true}
  ],
  "notices": ["The active version has no measurable file"]
}
```

Only rows whose value differs are returned. Non-selectable rows carry `reason`
(e.g. `"several materials"`, `"not in the file"`).

### POST `/file-versions/{version_id}/activate`
Body `{ "apply": ["print_time_minutes", "prints_per_plate", "weight_grams", "dimensions"], "print_file_id"?: "uuid" }`
→ 200 `FileVersion` (now active, print file updated if given). Values are re-read at apply time.
Applied fields are recorded `measured` (user, today). Works on the already-active version too
(used to switch its print file, FR-012a). 422 for a non-selectable field.

## Files (existing routes, changed compatibly)

### POST `/files` (multipart, existing)
New optional form fields: `version_id` (uuid) **or** `new_version_label` + `new_version_note`.
Neither given → file goes into the active version (creating version 1 if none).
Response `ModelFileUploadResponse` adds on `file`: `version_id`, `is_sliced`,
`measurement.reason`. Also adds top-level `version_created: bool` so the UI can offer
"Make active" (FR-009a).

### DELETE `/files/{file_id}` (existing)
409 `{"code": "last_file_of_active_version"}` or `{"code": "active_print_file"}` (research D9).
Otherwise 204; its notes are archived.

### GET `/files`, GET `/files/{id}` (existing)
Response adds `version_id`, `is_sliced`, `measurement.reason`. Unchanged otherwise.

## Notes

### GET `/file-notes?file_id=&version_id=&status=open|resolved|carried_forward&include_archived=false&ghosts_for_file_id=`
200 → `Note[]`. With `ghosts_for_file_id`, returns the open notes of earlier versions as well,
each flagged `"ghost": true`.

```json
{
  "id": "uuid", "number": 1, "model_file_id": "uuid|null", "version_id": "uuid",
  "position": [12.5, 3.0, 40.2], "normal": [0, 0, 1], "layer": 87,
  "text": "overhang sags here", "status": "open",
  "resolved_in_version_id": null, "carried_to_version_id": null, "carried_from_note_id": null,
  "author": {"id": "uuid", "name": "Konrad"}, "created_at": "...", "archived_at": null,
  "ghost": false
}
```

### POST `/files/{file_id}/notes`
Body `{ "position": [x,y,z], "normal": [x,y,z], "layer"?: int≥0, "text": string(1..2000) }`
→ 201 `Note`. 422 bad vector / empty text; 409 if the file is archived/deleted.

### PATCH `/file-notes/{note_id}`
Body `{ "text"?, "position"?, "normal"?, "status"?: "open"|"resolved", "resolved_in_version_id"? }`
→ 200 `Note`. `resolved` requires `resolved_in_version_id` of the same model with sequence ≥ the
note's version (422 otherwise). A `carried_forward` note → 409.

### POST `/file-notes/{note_id}/carry-forward`
Body `{ "target_file_id": "uuid" }` (a file of a newer version) → 201 new `Note` (open, linked).
Original becomes `carried_forward`. 422 when the target is not newer; 409 when the note is not open.
