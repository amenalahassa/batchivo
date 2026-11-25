# Data model: Preflight foundations (spec 009)

Migration `preflight_v1` (`backend/alembic/versions/20261125_preflight.py`), `down_revision =
"genai_v1"`. Every new table: `id` UUID PK, `tenant_id` FK `tenants.id` ON DELETE CASCADE (indexed),
`created_at`, `updated_at`; RLS enabled + forced with policy `<table>_tenant_isolation` (`tenant_id
= NULLIF(current_setting('app.current_tenant_id', true), '')::uuid`, USING and WITH CHECK).

## design_briefs (`app/models/design_brief.py`, `DesignBrief`)

| Column | Type | Rules |
|---|---|---|
| idea_id | UUID FK ideas SET NULL, null | partial unique `(idea_id) WHERE idea_id IS NOT NULL` |
| model_id | UUID FK models SET NULL, null | partial unique `(model_id) WHERE model_id IS NOT NULL` |
| intent | JSONB null | Preflight intent document as written |
| intent_schema_version | int null | `= 1` when intent set |
| risk_class | varchar(10) null | CHECK in (`faible`,`moyen`,`élevé`,`arrêt`) |
| risk_md | text null | ≤ 100 000 chars (service) |
| triage | JSONB null | `pf.py triage` output as written |
| plan_md | text null | ≤ 100 000 chars |
| params | JSONB null | params.yaml as JSON |
| params_updated_at | timestamptz null | |
| step_status | JSONB not null default `{}` | `{step: {status, updated_at, updated_by}}` |
| created_by_user_id / updated_by_user_id | UUID FK users SET NULL | |

Service rule: created with exactly one of idea_id / model_id; model_id later stamped when reached
through `models.source_idea_id` (research R1). Steps: `intent adopt clarify risk plan design check
slice print test learn render ship quick`; statuses `not_started in_progress done skipped blocked`.

## design_brief_revisions (`DesignBriefRevision`)

| Column | Type | Rules |
|---|---|---|
| brief_id | UUID FK design_briefs CASCADE | indexed |
| part | varchar(10) | CHECK in (`intent`,`risk`,`plan`) |
| content | JSONB | intent: the document; risk: `{risk_class, risk_md, triage}`; plan: `{plan_md}` |
| schema_version | int null | intent only |
| author_user_id | UUID FK users SET NULL | |

Immutable: `BEFORE UPDATE` trigger raises (`trg_design_brief_revisions_immutable`). Listed newest
first.

## model_file_notes (extended, `app/models/model_file_note.py`)

| New column | Type | Rules |
|---|---|---|
| source | varchar(10) not null, server default `person` | CHECK in (`person`,`preflight`,`print`) |
| rule_id | varchar(100) null | |
| severity | varchar(10) not null, server default `info` | CHECK in (`info`,`warning`,`failure`) |
| measured_value / expected_value | numeric null (unconstrained: kept exactly as sent; decimal string on the wire) | |
| value_unit | varchar(20) null | |
| dismissal_reason | text null | 1–2000 chars |
| dismissed_at | timestamptz null | |
| dismissed_by_user_id | UUID FK users SET NULL | |

Status CHECK becomes `IN ('open','resolved','carried_forward','dismissed')`; new CHECK
`status <> 'dismissed' OR dismissal_reason IS NOT NULL`. Index `(model_id, source, severity)`.

Transitions: `open → resolved | dismissed | carried_forward`; `resolved → open`;
`dismissed → open` (dismissal fields kept); `carried_forward` final.

## calibrations (`app/models/calibration.py`, `Calibration`)

| Column | Type | Rules |
|---|---|---|
| printer_id | UUID FK printers CASCADE | |
| material_type_id | UUID FK material_types RESTRICT | required |
| filament_type_id | UUID FK filament_types CASCADE, null | |
| orientation | varchar(12) | CHECK in (`vertical`,`horizontal`) |
| fit_type | varchar(16) | CHECK in (`slide`,`press`,`snap`,`print-in-place`) |
| value_mm | Numeric(5,3) | CHECK `value_mm >= 0 AND value_mm <= 2` |
| provenance | varchar(10) | CHECK in (`measured`,`assumed`) |
| source_print_job_id | UUID FK print_jobs SET NULL, null | |
| source_test_result_id | UUID FK print_test_results SET NULL, null | |
| measured_at | timestamptz not null | default now |
| notes | text null | ≤ 2000 |
| recorded_by_user_id | UUID FK users SET NULL | |
| superseded_by_id | UUID FK calibrations (no ON DELETE action), null | chain deleted together by cascade |
| superseded_at | timestamptz null | |

Unique current value: `uq_calibrations_current` on `(tenant_id, printer_id, material_type_id,
COALESCE(filament_type_id, '00000000-0000-0000-0000-000000000000'), orientation, fit_type) WHERE
superseded_at IS NULL` (set first when a value is superseded, so the old row leaves the index before the new one arrives). Trigger `trg_calibrations_immutable`: on UPDATE, raise unless only
`superseded_by_id`/`superseded_at`/`updated_at` change and `superseded_by_id` goes NULL → value.

## print_test_results (`app/models/print_test_result.py`, `PrintTestResult`)

| Column | Type | Rules |
|---|---|---|
| kind | varchar(16) | CHECK in (`clearance_grid`,`critical_zone`,`full_part`) |
| outcome | varchar(8) | CHECK in (`pass`,`fail`,`partial`) |
| model_id | UUID FK models SET NULL, null | set from the version when given |
| model_file_version_id | UUID FK model_file_versions SET NULL, null | |
| print_job_id | UUID FK print_jobs SET NULL, null | |
| printer_id | UUID FK printers SET NULL, null | |
| material_type_id | UUID FK material_types SET NULL, null | |
| filament_type_id | UUID FK filament_types SET NULL, null | |
| orientation | varchar(12) null | CHECK null or in (`vertical`,`horizontal`) |
| measurements | JSONB not null default `[]` | list of objects, ≤ 200 items, ≤ 64 KB |
| failure_mode | text null | ≤ 2000 |
| notes | text null | ≤ 10 000 |
| photo_url / photo_thumbnail_url | varchar(500) null | ImageStorage owner type `print_tests` |
| photo_content_type | varchar(50) null | |
| photo_original_filename | varchar(255) null | |
| recorded_by_user_id / updated_by_user_id | UUID FK users SET NULL | |

Service rules: version or job required (both allowed); version required for `critical_zone` and
`full_part`; version and job of this tenant; when both a model and a version are given the
version belongs to the model; when a job has a model and a version is given, they agree.
Indexes `(tenant_id, model_id, created_at)`, `(print_job_id)`.

## printer_connections (changed)

`access_code` varchar(100) → text. Both `access_code` and `cloud_token` hold Fernet tokens.
ORM attributes `access_code_encrypted` / `cloud_token_encrypted`; Python properties
`access_code` / `cloud_token` encrypt/decrypt (research R8). Data migration encrypts existing
values (idempotent), downgrade decrypts.
