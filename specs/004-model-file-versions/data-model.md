# Data Model: Model File Versions and Pinned Notes

All tables carry `tenant_id` (FK `tenants.id`, `ON DELETE CASCADE`), RLS enabled and forced with
policy `<table>_tenant_isolation` on `app.current_tenant_id`. UUID primary keys and
`created_at`/`updated_at` via `UUIDMixin` + `TimestampMixin`.

## model_file_versions (new)

| Column | Type | Rules |
|--------|------|-------|
| id | uuid PK | |
| tenant_id | uuid | NOT NULL |
| model_id | uuid FK `models.id` ON DELETE CASCADE | NOT NULL |
| sequence | int | NOT NULL, ≥ 1; next = max(sequence)+1 per model; UNIQUE (model_id, sequence) |
| label | varchar(50) | NOT NULL, default = `str(sequence)`, editable, 1–50 chars |
| note | text | NULL; "what changed" |
| is_active | bool | NOT NULL default false; partial UNIQUE (model_id) WHERE is_active |
| print_file_id | uuid FK `model_files.id` ON DELETE SET NULL, `use_alter` | NULL; must reference a file of this version with `is_sliced = true` (service-enforced) |
| created_by_user_id | uuid FK `users.id` ON DELETE SET NULL | NULL for backfilled rows |

**Lifecycle**
- Created inactive, except a model's first version, which is created active (FR-009, Q3).
- `activate`: in one transaction the current active row → false, this row → true (partial
  unique index guards against two).
- `print_file_id`: set to the version's first sliced file when it gets one; changed only by the
  operator (FR-011a) or by deleting it on an inactive version (reassigned to newest remaining
  sliced file, D9).
- A version with no files left is deleted with its last file, unless it is active (delete refused).

## model_files (changed)

| Column | Change |
|--------|--------|
| version_id | **new** uuid FK `model_file_versions.id` ON DELETE CASCADE; NOT NULL after backfill; index (version_id) |
| is_sliced | **new** bool NOT NULL default false; set at upload (D3) |
| measurement_reason | **new** varchar(40) NULL; machine-readable reason for `measurement_status = failed/skipped` (e.g. `no_geometry`, `too_large`, `unreadable`) |
| version | kept, informational only; written with the version's label on upload and when the label changes; a legacy PATCH may still set it, but grouping always follows `version_id` |
| is_primary | kept, unchanged semantics (per file type) |

## model_file_notes (new)

| Column | Type | Rules |
|--------|------|-------|
| id | uuid PK | |
| tenant_id | uuid | NOT NULL |
| model_id | uuid FK `models.id` ON DELETE CASCADE | NOT NULL; index |
| version_id | uuid FK `model_file_versions.id` ON DELETE CASCADE | NOT NULL; index |
| model_file_id | uuid FK `model_files.id` ON DELETE SET NULL | NULL once the file is deleted |
| number | int | NOT NULL; per-file display number (1, 2, …) assigned at creation |
| pos_x, pos_y, pos_z | double precision | NOT NULL; file coordinates, mm |
| normal_x, normal_y, normal_z | double precision | NOT NULL; unit vector (validated length ≈ 1) |
| layer | int | NULL; set when placed on a sliced file; ≥ 0 |
| text | text | NOT NULL, 1–2000 chars |
| status | varchar(20) | NOT NULL, CHECK in (`open`, `resolved`, `carried_forward`), default `open` |
| resolved_in_version_id | uuid FK `model_file_versions.id` ON DELETE SET NULL | required when status = resolved |
| carried_to_version_id | uuid FK `model_file_versions.id` ON DELETE SET NULL | required when status = carried_forward |
| carried_from_note_id | uuid FK `model_file_notes.id` ON DELETE SET NULL | NULL unless this note continues another |
| author_user_id | uuid FK `users.id` ON DELETE SET NULL | |
| archived_at | timestamptz | NULL; set when its file is deleted (FR-030) |

**State transitions**
- `open` → `resolved` (in version V, V newer than or equal to the note's version)
- `open` → `carried_forward` (to version V newer than the note's version) — creates a new `open`
  note on a file of V with `carried_from_note_id` = this note, same text and position (Q2)
- `resolved` → `open` (reopen) allowed; `carried_forward` is final (the chain continues in the new note)

**Ghost pins (query)**: open, non-archived notes of the same model whose version's `sequence` is
lower than the viewed file's version sequence.

## Relationships

```text
Model 1─* ModelFileVersion 1─* ModelFile
ModelFileVersion ─0..1→ ModelFile (print_file)
Model 1─* ModelFileNote *─1 ModelFileVersion
ModelFileNote *─0..1 ModelFile
ModelFileNote ─0..1→ ModelFileNote (carried_from)
```

## Validation rules from requirements

- FR-009: exactly one active version once a model has files — partial unique index + service.
- FR-011a: print file must be in the version and `is_sliced` — service (422 otherwise).
- FR-015: refuse deleting last file of the active version — 409.
- FR-014: no write to `price_snapshots`, orders or production-run tables from any code path here.
- FR-031: `tenant_id` + RLS on both new tables; services filter by tenant as the second belt.
