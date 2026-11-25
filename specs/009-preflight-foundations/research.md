# Research: Preflight foundations (spec 009)

Sources read: `docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §6; the Preflight skill
(`~/.claude/skills/preflight`: `SKILL.md`, `ARCHITECTURE.md`, `commands/*.md`,
`templates/intent.yaml|risk.md|plan.md|atelier.yaml`, `kb/rules.yaml|materials.yaml|regulations.yaml`,
`scripts/pf.py`); Batchivo code for notes (spec 004), ideas (007), genai (008), MCP (010), print
send (011). The skill folder `C:\Users\Public\Documents\Konrad\claude\preflight` only holds a
filled `atelier.yaml`; the skill itself is installed in `~/.claude/skills/preflight`. Neither is
modified by this feature.

## R1. Where the brief lives, and how it follows the idea to the model

- **Decision**: one `design_briefs` row with nullable `idea_id` and `model_id` (partial unique index
  on each). A model's brief is the row with `model_id = M`, else the row whose `idea_id` is the
  model's `source_idea_id` (written by 007's conversion). A "start brief" on the model (`POST
  /models/{id}/design-brief`) stamps `model_id` on that row; edits go through the brief's own id
  and need no stamp. GETs never write.
- **Rationale**: no change to `idea_service.convert` (007's file, outside the 009 zone);
  `models.source_idea_id` already records the link the conversion makes, for both "model" and
  "product with its model" targets. No copy, so idea and model always show the same brief (FR-006).
- **Alternatives**: a hook in `IdeaService.convert` like 008's `carry_idea_drafts` (needs an
  out-of-zone edit; rejected); copying the brief at conversion (two diverging briefs; rejected).
- **Deviation from §6**: the "at least one of idea/model" rule is enforced by the service, not a
  database CHECK: `ideas` and `models` are soft-deleted today, but `ON DELETE SET NULL` on both
  keys would otherwise make a hard delete of either fail. Spec edge case "model deleted" therefore
  reads: a model is deactivated, its brief stays with it.

## R2. "Versioned" intent (clarification Q1 → B)

- **Decision**: the intent keeps Preflight's `schema_version` (only `1` accepted today) and every
  save that changes the intent, the risk part (class, text, triage) or the plan appends an
  immutable row to `design_brief_revisions` (`part`, full `content`, `schema_version`, author,
  date). Unchanged saves add nothing. Parameters and step statuses keep last value + date only.
- **Immutability**: no update/delete route; a PostgreSQL `BEFORE UPDATE` trigger raises on
  `design_brief_revisions` (created by the migration and by an `after_create` DDL event on the
  table so `create_all` test databases get it too).

## R3. Intent validation: one authority on Batchivo's side

- **Decision**: `services/preflight_intent.py` validates exactly what `pf.py validate` validates
  (enums `duration`, `fit`, `status`, `sales_channel`, `unit` ∈ {kg, N}; `[À PRÉCISER]` always
  allowed; `schema_version == 1`), refuses an invalid document with the field path, and returns
  the same report shape as `pf.py validate` (`to_clarify`, `unconfirmed`, `missing`). Missing
  required keys are reported, not refused, so a half-filled intent from the `intent` step can be
  stored. Extra keys are kept untouched.
- **YAML**: the API accepts the intent as JSON (`intent`) or as YAML text (`intent_yaml`, parsed
  with PyYAML `safe_load`, already a backend dependency); YAML dates are converted to ISO strings
  so the stored document is plain JSON. The frontend editor sends text as `intent_yaml` (YAML is a
  superset of JSON), so no frontend YAML dependency is added (clarification Q4).
- **Limits**: intent, triage and params ≤ 256 KB each once serialised; risk and plan text ≤ 100 000
  characters.

## R4. Step names and statuses

- **Decision**: per-part steps = the skill's per-part commands: `intent, adopt, clarify, risk,
  plan, design, check, slice, print, test, learn, render, ship, quick` (`init` is workshop-level,
  `status` is a report). Status ∈ `not_started, in_progress, done, skipped, blocked`; stored as
  JSONB `{step: {status, updated_at, updated_by}}`; absent step = `not_started`.
- **Deviation from §6**: §6 lists 8 steps (intent/clarify/risk/plan/check/slice/test/ship); the
  skill has 14 per-part commands and `status` must name any of them, so all 14 are accepted.
  `blocked` carries `risk`'s "arrêt net".

## R5. Typed notes, dismissal (clarification Q2 → A)

- **Decision**: additive columns on `model_file_notes`: `source` (NOT NULL, server default
  `person`; `person|preflight|print`), `rule_id` (≤100), `severity` (NOT NULL, default `info`;
  `info|warning|failure`), `measured_value`, `expected_value` (Float, like the table's geometry,
  research D7 of spec 004), `value_unit` (≤20), `dismissal_reason`, `dismissed_at`,
  `dismissed_by_user_id`. Status CHECK gains `dismissed`, with `dismissed ⇒ dismissal_reason IS
  NOT NULL`. Existing rows read `person`/`info` through the server defaults.
- **Severity aliases**: input accepts `attention` → `warning`, `échec`/`echec` → `failure`;
  output is always Batchivo's word (bijection, documented for the skill).
- **Behaviour**: only `open` notes can be dismissed or carried forward (unchanged rule); reopening
  a dismissed note keeps the last dismissal fields; open-note counts per version are unchanged
  (dismissed is not open). Carry-forward copies the type fields (FR-013).
- **Compatibility**: requests without the new fields behave exactly as before; responses only gain
  fields; the status filter gains a value.

## R6. Calibrations

- **Decision**: `calibrations` table, immutable except the supersede link: `printer_id`,
  `material_type_id` (required; shop-independent material list, matches Preflight's `material:
  PLA` by `material_types.code`, case-insensitive), `filament_type_id` (optional refinement),
  `orientation` (`vertical|horizontal`), `fit_type` (`slide|press|snap|print-in-place`),
  `value_mm` `Numeric(5,3)` 0–2 (§6: Numeric; decision-driving figure, principle VI), `provenance`
  (`measured|assumed`), `source_print_job_id`, `source_test_result_id`, `measured_at`, `notes`,
  `recorded_by`, `superseded_by_id`, `superseded_at`.
- **One current value**: partial unique index on `(tenant_id, printer_id, material_type_id,
  COALESCE(filament_type_id, nil uuid), orientation, fit_type) WHERE superseded_at IS NULL`; recording sets the old row's `superseded_at`, inserts the new row, then sets `superseded_by_id` (three flushes, so neither the index nor the self foreign key is broken).
  Recording locks the current row (`FOR UPDATE`), inserts the new one, links the old one, in one
  transaction; a concurrent duplicate hits the index → 409 "retry".
- **Immutability**: no update/delete route; `BEFORE UPDATE` trigger allows only
  `superseded_by_id`/`superseded_at` going from NULL to a value (and `updated_at`). Deleting a
  printer cascades (spec edge case).
- **Lookup** (`GET /calibrations/lookup`): printer + fit + orientation + material (id or code) [+
  filament]; filament-specific current value wins, else material-level, else `found: false`. Same
  precedence as `pf.py clearance` (measurement > rule): the caller falls back to its rule.
- **Wire format**: `value_mm` is a decimal string (`"0.200"`), as every `Numeric` in this API.

## R7. Print test results (clarification Q3 → B)

- **Decision**: `print_test_results`: `kind` (`clearance_grid|critical_zone|full_part`), `outcome`
  (`pass|fail|partial`), `model_id`, `model_file_version_id`, `print_job_id`, optional context for
  `learn` (`printer_id`, `material_type_id`, `filament_type_id`, `orientation`), `measurements`
  (JSONB list of `{name, value, unit?, expected?}` stored as given), `failure_mode`, `notes`,
  photo fields, `recorded_by`, `updated_by`. Service rule: at least one of version / print job;
  version required for `critical_zone` and `full_part`; version and job must belong to the shop
  (and to the given model). No DB CHECK for "at least one" because both keys are `SET NULL` (a
  deleted print job leaves the result, spec edge case).
- **Photo**: one image through `ImageStorage` with a new owner type `print_tests` (one line in
  `services/image_storage.py`, the extension point of architecture §3 — out-of-zone, asked to the
  orchestrator), served by an authenticated route like idea images; same 10 MB limit and
  thumbnail.

## R8. Printer secrets encrypted

- **Decision**: in `models/printer_connection.py`, the mapped attributes become
  `access_code_encrypted` / `cloud_token_encrypted` on the same columns (`access_code` widened to
  `Text`), and Python properties `access_code` / `cloud_token` encrypt on set (`encrypt_value`) and
  decrypt on get (`safe_decrypt`, `None` when unreadable). Every existing reader
  (`printer_bambu.py`, `printer_ws.py` Moonraker key, `print_send_service.py` via
  `printer_secrets.get_access_code`, response masking) keeps reading the clear value without
  change; the declarative constructor and `setattr` loops accept the properties.
- **Unreadable secret** (server key changed): the property yields `None`, so printer operations
  fail with the existing "missing access code" messages; `PrinterConnectionResponse` gains
  `access_code_state` / `cloud_token_state` (`set|unset|unreadable`) and the connection dialog
  says "enter the access code again". `printer_secrets.secret_state()` is the one place that
  decides the state; a warning is logged with the connection id only. Spec FR-025 is met without
  editing 011's routes.
- **Migration** (`preflight_v1`): widen column, encrypt every non-empty value that is not already a
  valid Fernet token (idempotent), downgrade decrypts. Uses `app.core.encryption` with the app's
  `SECRET_KEY`, so the migration must run with the same key as the app (already true for the
  deploy and VPS update paths).
- **Alternatives**: a `TypeDecorator` (cannot distinguish "unset" from "unreadable"); a separate
  encrypted column (two sources of truth during the move).

## R9. API shape for agents

- **Decision**: POST/PATCH/GET only (the MCP `BatchivoClient` has `get/post/patch/upload`; no
  change to 010's client). Briefs: one `PATCH /design-briefs/{id}` for any subset of intent /
  risk / plan / params / steps. Brief delete is JWT-only (no token policy row). Every new read is
  `read` scope, every write `write` in `auth/api_token_policy.py` (its documented 009 extension
  point). MCP tools in `mcp_server/tools/preflight.py`, registered in `tools/__init__.py`.
- **Atelier export**: `GET /calibrations/atelier` returns current calibrations in the
  `atelier.yaml` `calibrations:` item shape (`printer`, `material`, `filament`, `orientation`,
  `fit`, `value_mm`, `provenance`, `measured_at`, `source_print_job_id`, `id`), so `pf.py
  clearance --atelier` works unchanged on an exported file.

## R10. Registries and gates

New tables are tenant-scoped with RLS in the migration (covered by
`tests/integration/test_every_tenant_table_has_rls.py`, which reads the policies). New write
routes use `RequireMember` (`tests/unit/test_write_route_role_guards.py`). New services avoid
`Decimal` except `calibration_service` (value_mm); if `tests/unit/pricing/money_modules.py` flags a
service, it is added to `NOT_MONEY_PATHS` with its reason. New MCP tools are covered by
`tests/mcp_server/test_tool_coverage.py`, `test_tool_error_paths.py` and
`test_mcp_tools_reach_api.py`. New routes are classified in the token policy test.

## R11. Preflight ↔ Batchivo correspondence (field by field)

### Design brief ← `work/<slug>/` files

| Preflight | Batchivo | Notes |
|---|---|---|
| `intent.yaml` (whole document) | `design_briefs.intent` (JSONB) | Stored as written: every key, `[À PRÉCISER]`, statuses, extra keys. Comments in YAML are not kept (YAML comments are not data) |
| `intent.yaml.schema_version` | `intent.schema_version` + `design_briefs.intent_schema_version` | Only 1 accepted |
| `intent.slug` | `intent.slug` | Not used as key; the brief is keyed by idea/model |
| `function, category, quantity, selling, sales_channel, country, eu, third_party_model, third_party_license, alternatives, success_criteria[]` | same keys in `intent` | Form fields in the UI (Q4) |
| `loads[] {value, unit, direction, duration, cycles, status}` | same | `unit ∈ {kg,N}`, `duration` enum validated |
| `environment {max_temp_c, max_temp_source, outdoor, uv, humidity, chemicals, food_contact_claimed, children, safety_critical, status}` | same | |
| `interfaces[] {neighbour, fit, dimensions_mm, status}` | same | `fit` enum validated |
| `images[]` | same (references) | Image files stay on the idea timeline / model; gap: no upload into the brief |
| `intent.md` | not stored | Derived summary; the UI renders the intent |
| `pf.py validate` output | `PATCH` response `validation` | Same keys (`to_clarify`, `unconfirmed`) + `missing` |
| `risk.md` | `design_briefs.risk_md` | Markdown as written |
| triage `risk_class` (`faible|moyen|élevé|arrêt`) | `design_briefs.risk_class` | Same French tokens |
| `pf.py triage` JSON | `design_briefs.triage` (JSONB) | Stored as written |
| `plan.md` | `design_briefs.plan_md` | |
| `params.yaml` | `design_briefs.params` (JSONB) | Sent as JSON object (YAML parsed by the skill or sent as `params_yaml`) |
| step done by a command | `step_status[<command>]` | 14 commands, 5 statuses |
| `check/`, `slice/`, `tests/`, `release/` artefacts | not stored | Out of scope: files stay local or become model file versions |

### Typed notes ← `check` alerts and `learn`

| Preflight | Batchivo note field |
|---|---|
| position, normal, layer | `position`, `normal`, `layer` (existing) |
| alert text + proposed fix | `text` (existing, ≤2000) |
| `source: preflight` / `print` | `source` |
| rule id (`kb/rules.yaml` `id`, or `kb/regulations.yaml` `reg.*`) | `rule_id` (free text ≤100; not checked against the KB, which lives in the skill) |
| gravité `info` / `attention` / `échec` | `severity` `info` / `warning` / `failure` (aliases accepted on input) |
| valeur mesurée / attendue | `measured_value` / `expected_value` (+ `value_unit`) |
| alerte ignorée + justification | status `dismissed` + `dismissal_reason` |
| résoudre / reporter | existing `resolved` / carry-forward |
| confiance (`high/medium/low`) | **gap**: not a column; kept in the text. Adding it later is additive |

### Calibrations ← `learn` / `calibration.yaml` / `atelier.yaml calibrations[]`

| Preflight key | Batchivo |
|---|---|
| `printer` (atelier printer id, e.g. `principale`) | `printer_id` (Batchivo printer); the export writes the printer's name. **Gap**: the skill must map its atelier ids to Batchivo printers (it already reads printers from Batchivo in Batchivo mode) |
| `material` (`PLA`, …) | `material_type_id` via `material_types.code`; export writes the code |
| (brand/colour) | `filament_type_id` (optional) |
| `orientation` (free text in the skill) | `vertical` / `horizontal` (**change in skill**: use these two words) |
| `fit` (`slide/press/snap/print-in-place`) | `fit_type` (same tokens) |
| `value_mm` | `value_mm` (decimal string) |
| `provenance: measured` / rule default | `provenance` `measured` / `assumed` |
| `measured_at` | `measured_at` |
| impression d'origine | `source_print_job_id`, `source_test_result_id` |
| `superseded_by` | `superseded_by_id` (export only lists current ones, so `pf.py`'s filter is satisfied) |

### Print test results ← `test` protocol and `learn` results

| Preflight | Batchivo |
|---|---|
| pièce et version | `model_id`, `model_file_version_id` |
| impression | `print_job_id` |
| imprimante, filament, orientation | `printer_id`, `material_type_id`/`filament_type_id`, `orientation` |
| éprouvette: grille de jeux / zone critique / pièce | `kind` `clearance_grid` / `critical_zone` / `full_part` |
| issue `pass/fail/partial` | `outcome` (same tokens) |
| mesures | `measurements` (list as written) |
| mode de rupture | `failure_mode` |
| photo | photo upload |
| `history.jsonl` line | the result row itself |
| « impressions jusqu'à la version vendable » | **gap**: derived on read later (count of results per model); not built here |

### Not covered (stays in the skill's local `atelier.yaml`)

`country`, `eu`, `seller_status`, `sales_channels`, `cad.software/license`, `safety_policy`,
nozzle list, slicer path/version: no Batchivo entity today; out of scope (spec Assumptions).

## R12. Changes the skill needs (reported, not made)

Listed in `plan.md` §"Preflight skill changes".
