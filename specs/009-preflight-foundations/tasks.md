# Tasks: Preflight foundations — design brief, typed notes, calibrations and print test results

**Input**: Design documents from `specs/009-preflight-foundations/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, contracts/mcp-tools.md, quickstart.md

**Tests**: required by the constitution (principle II) and CLAUDE.md testing policy. Tests are
written with the code; they are **run only after the orchestrator's go-ahead** (T063).

**Organization**: by user story (spec.md). Paths are repo-relative.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [X] T001 Create migration `backend/alembic/versions/20261125_preflight.py` (`revision = "preflight_v1"`, `down_revision = "genai_v1"`) creating, in this order, `design_briefs`, `design_brief_revisions`, `print_test_results`, `calibrations` (calibrations reference test results) exactly as data-model.md (columns, CHECKs, FKs, partial unique indexes `(idea_id) WHERE idea_id IS NOT NULL`, `(model_id) WHERE model_id IS NOT NULL`, `uq_calibrations_current` with `COALESCE(filament_type_id, '00000000-0000-0000-0000-000000000000')` `WHERE superseded_at IS NULL`), RLS enable+force+`<table>_tenant_isolation` policy on PostgreSQL (pattern of `20261124_genai.py`), triggers `trg_design_brief_revisions_immutable` and `trg_calibrations_immutable`; downgrade drops all in reverse
- [X] T002 In the same migration add to `model_file_notes`: `source varchar(10) NOT NULL server_default 'person'` CHECK in (`person`,`preflight`,`print`), `rule_id varchar(100)`, `severity varchar(10) NOT NULL server_default 'info'` CHECK in (`info`,`warning`,`failure`), `measured_value float`, `expected_value float`, `value_unit varchar(20)`, `dismissal_reason text`, `dismissed_at timestamptz`, `dismissed_by_user_id` FK users SET NULL; replace `ck_model_file_notes_status` with `IN ('open','resolved','carried_forward','dismissed')`; add `ck_model_file_notes_dismissed_reason` (`status <> 'dismissed' OR dismissal_reason IS NOT NULL`); index `(model_id, source, severity)`; downgrade turns `dismissed` notes back to `open` before restoring the old CHECK
- [X] T003 In the same migration: widen `printer_connections.access_code` to `text`; data step encrypting every non-empty `access_code` and `cloud_token` that is not already a decryptable Fernet token (using `app.core.encryption`), idempotent; downgrade decrypts then narrows to `varchar(100)`

## Phase 2: Foundational (blocks all stories)

- [X] T004 [P] Create `backend/app/models/design_brief.py` (`DesignBrief`, `DesignBriefRevision`, constants `PREFLIGHT_STEPS` = (`intent`,`adopt`,`clarify`,`risk`,`plan`,`design`,`check`,`slice`,`print`,`test`,`learn`,`render`,`ship`,`quick`), `STEP_STATUSES`, `RISK_CLASSES` = (`faible`,`moyen`,`élevé`,`arrêt`), `REVISION_PARTS`) with CHECKs/indexes mirroring T001 and an `after_create` PostgreSQL DDL event creating the revision immutability trigger
- [X] T005 [P] Create `backend/app/models/calibration.py` (`Calibration`, `FIT_TYPES`, `ORIENTATIONS`, `CALIBRATION_PROVENANCES`; `value_mm Numeric(5,3)` CHECK 0–2; self FK `superseded_by_id`) with the current-value partial unique index and the `after_create` immutability trigger DDL
- [X] T006 [P] Create `backend/app/models/print_test_result.py` (`PrintTestResult`, `TEST_KINDS` = (`clearance_grid`,`critical_zone`,`full_part`), `TEST_OUTCOMES` = (`pass`,`fail`,`partial`)) per data-model.md
- [X] T007 Register the three model modules in `backend/app/models/__init__.py`
- [X] T008 [P] Model/constraint tests in `backend/tests/integration/test_preflight_models.py`: CRUD of each table, relationships, every CHECK, partial unique indexes (second brief on same idea/model refused, second current calibration refused), revision and calibration triggers refuse UPDATE of content/value, calibration allows `superseded_by_id` NULL→value once, cascade on printer delete, `SET NULL` on print job delete keeps the result
- [X] T009 [P] RLS isolation test in `backend/tests/integration/test_preflight_rls.py` (pattern of `test_rls_tenant_isolation.py`, non-superuser role): rows of the 4 new tables written under tenant A are invisible and not writable with `app.current_tenant_id` = tenant B (FR-027)
- [X] T010 [P] Migration test `backend/tests/integration/test_preflight_migration.py` (new file; imports `migration_support` read-only): upgrade from `genai_v1` creates tables with RLS and policies, old notes read `person`/`info`, a clear access code and cloud token become Fernet tokens that decrypt to the original, re-running the data step is a no-op, downgrade restores clear values and `dismissed` notes become `open`; `alembic heads` is single

## Phase 3: User Story 5 — Printer secrets encrypted at rest (P1)

**Goal**: secrets encrypted, every reader unchanged. **Independent test**: stored value ≠ clear; connection gets clear value; unreadable secret reported.

- [X] T011 [US5] In `backend/app/models/printer_connection.py` map the columns as `access_code_encrypted` (Text, column name `access_code`) and `cloud_token_encrypted` (column `cloud_token`); add properties `access_code`/`cloud_token` (setter `encrypt_value`, empty/None → None; getter `safe_decrypt`, None when unreadable); keep the class usable with `PrinterConnection(access_code=...)` and `setattr`
- [X] T012 [US5] In `backend/app/services/printer_secrets.py` keep `get_access_code` (now decrypting through the property) and add `secret_state(connection, field) -> "set"|"unset"|"unreadable"` logging one warning with the connection id only when unreadable; update module docstring
- [X] T013 [US5] In `backend/app/schemas/printer_connection.py` add `access_code_state` and `cloud_token_state` to `PrinterConnectionResponse` (computed through `secret_state`, model validator) keeping the existing masks
- [X] T014 [P] [US5] Extend `backend/tests/unit/test_printer_secrets.py`: round trip, empty value, unreadable token → None and state `unreadable`, warning log has no secret or ciphertext
- [X] T015 [P] [US5] `backend/tests/integration/test_printer_connection_encryption.py`: create/update via `/printers/{id}/connection` stores ciphertext (raw SQL), response masked as before (`****` + last 4), `access_code_state`, connect path receives clear value (bambu MQTT mocked), print-send `_config` receives clear value
- [X] T016 [P] [US5] Show "Access code can no longer be read — enter it again" when `access_code_state === 'unreadable'` (same for cloud token) in `frontend/src/components/printers/PrinterConnectionDialog.tsx`, types in `frontend/src/types/` connection type; test in `PrinterConnectionDialog.test.tsx`

## Phase 4: User Story 1 — Design brief on idea, then model (P1) 🎯 MVP

**Goal**: brief stored, validated, revised, follows the idea. **Independent test**: quickstart §3.

- [X] T017 [P] [US1] `backend/app/services/preflight_intent.py`: `PLACEHOLDER = "[À PRÉCISER]"`, enums (duration `permanent|cyclic|shock|short`, unit `kg|N`, fit `slide|press|snap|screw|insert|print-in-place|none`, status `déduit|estimée|validé|mesurée`, sales_channel `etsy|makerworld|shop|none`), `parse_yaml(text)` (safe_load, dates → ISO strings, must be a mapping), `validate_intent(doc) -> IntentReport(to_clarify, unconfirmed, missing)` raising `IntentInvalid(errors=[(loc, msg)])`; `schema_version` must be 1; size ≤ 256 KB
- [X] T018 [P] [US1] `backend/tests/unit/test_preflight_intent.py`: the skill's `templates/intent.yaml` content (copied as a fixture string) validates with the expected `to_clarify`/`unconfirmed`, each enum error names its path, placeholders accepted, wrong schema_version, YAML dates, non-mapping YAML, size limit, extra keys preserved
- [X] T019 [P] [US1] `backend/app/schemas/design_brief.py`: `DesignBriefStart`, `DesignBriefUpdate` (exclusive `intent`/`intent_yaml`, `params`/`params_yaml`; `risk: RiskPart{risk_class Literal, risk_md ≤100000, triage dict}`; `plan_md ≤100000`; `steps: dict[Literal steps, Literal statuses]`; at least one field), `DesignBriefResponse`, `StepState`, `IntentValidation`, `DesignBriefRevisionResponse`, `DesignBriefUpdateResult` per contracts/api.md
- [X] T020 [US1] `backend/app/services/design_brief_service.py` (`DesignBriefService(db, tenant, user)`): `for_idea`, `for_model` (own brief else source idea's), `start_on_idea`, `start_on_model` (reuse + stamp `model_id`), `get`, `update` (revision appended only when intent / risk part / plan actually change; steps stamped with time and user; params with `params_updated_at`; stamps `model_id` when reached through a model), `list_revisions(part, skip, limit)`, `delete`, `to_response` (14 steps in order, validation report, revision counts, idea title / model name); 404s for foreign idea/model; JSON size limits
- [X] T021 [US1] `backend/app/api/v1/design_briefs.py` routes of contracts/api.md (`get_idea_brief`, `start_idea_brief`, `get_model_brief`, `start_model_brief`, `get_brief`, `update_brief`, `list_brief_revisions`, `delete_brief`), `CurrentTenant` + `TenantDB`, writes `RequireMember`, `IntentInvalid` → 422 with loc; register router in `backend/app/main.py` (one `include_router` line, prefix `settings.api_v1_prefix`)
- [X] T022 [P] [US1] `backend/tests/unit/test_design_brief_service.py`: revision only on change, risk part replaced whole, step stamping, model reached through source idea, start on model reuses idea brief
- [X] T023 [P] [US1] `backend/tests/integration/test_design_briefs_api.py`: each route 200/201, 401, 422 (bad enum, both intent and intent_yaml, unknown step, oversized), 404 (other tenant's idea/model/brief); round trip of the template intent (SC-001); conversion of the idea → model and → product with its model, GET on the model returns the same brief; viewer cannot write (403); delete with JWT 204
- [X] T024 [P] [US1] Frontend types/API/hooks: `frontend/src/types/preflight.ts`, `frontend/src/lib/api/designBriefs.ts`, `frontend/src/hooks/useDesignBrief.ts` (query by idea or model, start, update, revisions; invalidate on success)
- [X] T025 [US1] `frontend/src/components/preflight/StepStrip.tsx` (14 steps, status colour + label, editable select for members) and `preflightText.ts` (labels for steps, statuses, risk classes, value statuses)
- [X] T026 [US1] `frontend/src/components/preflight/IntentView.tsx`: function, category, loads, environment, interfaces, success criteria; `[À PRÉCISER]` and `déduit`/`estimée` highlighted
- [X] T027 [US1] `frontend/src/components/preflight/IntentEditor.tsx`: form for function, category, quantity, selling, sales channel, country, success criteria and each value status; textarea (YAML/JSON) for loads, environment, interfaces sent as `intent_yaml` merged with the form fields; server 422 shown with its field, editor content kept
- [X] T028 [US1] `frontend/src/components/preflight/RiskPlanEditor.tsx` (risk class select, risk and plan Markdown edit + preview via `components/ideas/Markdown.tsx`) and `ParamsEditor.tsx` (YAML/JSON text sent as `params_yaml`)
- [X] T029 [US1] `frontend/src/components/preflight/BriefRevisionsDialog.tsx` (list by part, newest first, view content read-only)
- [X] T030 [US1] `frontend/src/components/preflight/DesignBriefPanel.tsx` (empty state "Start a design brief", sections, link idea ↔ model, edit actions for members only) and mount it: new "Design brief" tab in `frontend/src/pages/IdeaDetailPage.tsx`, new "Design brief" section in `frontend/src/components/models/ModelDetail.tsx`
- [X] T031 [P] [US1] Vitest: `DesignBriefPanel.test.tsx`, `IntentEditor.test.tsx`, `StepStrip.test.tsx`, `IntentView.test.tsx` in `frontend/src/components/preflight/`

## Phase 5: User Story 2 — Typed notes (P1)

**Goal**: notes gain type, filters, dismissal, without breaking anything. **Independent test**: old note requests unchanged; typed round trip; filters.

- [X] T032 [US2] `backend/app/models/model_file_note.py`: new columns and CHECKs of T002, `NOTE_STATUSES` + `dismissed`, `NOTE_SOURCES`, `NOTE_SEVERITIES`, `dismissed_by` relationship
- [X] T033 [US2] `backend/app/schemas/model_file_note.py`: `NoteCreate` optional `source` (default `person`), `rule_id ≤100`, `severity` (validator: `attention`→`warning`, `échec`/`echec`→`failure`), `measured_value`, `expected_value`, `value_unit ≤20`; `NoteUpdate` adds `status` `dismissed`, `dismissal_reason` 1–2000 (required when dismissing), `severity`, `rule_id`, values, unit; `NoteResponse` adds the fields + `dismissal_reason`, `dismissed_at`, `dismissed_by`
- [X] T034 [US2] `backend/app/services/model_file_note_service.py`: create with type fields; `list_notes` `source`/`severity` filters; `update` dismiss (only from `open`, else `VersionRuleError`; stamps reason/time/user), reopen from `dismissed` keeps dismissal fields, type field edits; `carry_forward` copies type fields
- [X] T035 [US2] `backend/app/api/v1/model_file_notes.py`: pass new fields, `source`/`severity` query params (severity aliases accepted), status filter accepts `dismissed`, `_response` returns new fields
- [X] T036 [P] [US2] `backend/tests/integration/test_typed_notes_api.py`: untyped note reads `person`/`info` and the existing flows; typed round trip; filters alone/combined with status/version; aliases; dismiss without reason 422, dismiss resolved note 409, reopen; carry forward keeps type; open counts per version exclude dismissed; and re-run `tests/integration/test_model_file_notes_api.py` unchanged (SC-002)
- [X] T037 [US2] Frontend: `frontend/src/types/model-file-version.ts` note fields and `NoteStatus` + `dismissed`; `frontend/src/lib/api/modelFileNotes.ts` params `source`, `severity`; `frontend/src/components/viewer/NotesPanel.tsx` severity/source badges, rule id, measured/expected values, source and severity filters, "Dismiss" with required justification, dismissed notes shown with their justification and "Reopen"; `NotePins.tsx` pin colour by severity
- [X] T038 [P] [US2] Vitest: extend `frontend/src/components/viewer/NotesPanel.test.tsx` and `NotePins.test.tsx` (badges, filters, dismiss dialog requires text, untyped note unchanged)

## Phase 6: User Story 3 — Calibrations (P2)

**Goal**: immutable superseding fit values + lookup + atelier export. **Independent test**: quickstart §4.

- [X] T039 [P] [US3] `backend/app/schemas/calibration.py`: `CalibrationCreate` (`material_type_id` xor `material` code, `filament_type_id?`, `orientation` Literal `vertical|horizontal`, `fit_type` Literal `slide|press|snap|print-in-place`, `value_mm` Decimal 0–2 max 3 decimals accepting number or string, `provenance` Literal `measured|assumed`, `source_print_job_id?`, `source_test_result_id?`, `measured_at?`, `notes ≤2000`), `CalibrationResponse` (value as decimal string, `is_current`), `CalibrationLookup`, `AtelierCalibration` (value_mm float)
- [X] T040 [US3] `backend/app/services/calibration_service.py` (`CalibrationService`): `record` (resolve material code case-insensitive → 422 if unknown; check printer, filament type (its material must match), print job, test result in tenant; lock current row `FOR UPDATE`, insert, link old `superseded_by_id`/`superseded_at`; `IntegrityError` → 409), `list_for_printer` (filters, current_only, newest first), `lookup` (filament-specific current, else material-level current, `matched_on`), `get`, `atelier_export(printer_id?)`
- [X] T041 [US3] `backend/app/api/v1/calibrations.py` (`list_printer_calibrations`, `record_calibration`, `lookup_calibration`, `export_atelier_calibrations`, `get_calibration`; route order puts `/calibrations/lookup` and `/calibrations/atelier` before `/{calibration_id}`); register in `backend/app/main.py`
- [X] T042 [P] [US3] `backend/tests/unit/test_calibration_service.py` (precedence, supersede chain, decimals exact) and `backend/tests/integration/test_calibrations_api.py` (201/200, 401, 422 bad fit/orientation/value 2.001/unknown material, 404 other tenant's printer, PATCH/DELETE → 405, history order, export shape readable by `pf.py clearance`'s filter keys)
- [X] T043 [US3] Frontend: `frontend/src/lib/api/calibrations.ts`, `frontend/src/hooks/useCalibrations.ts`, `frontend/src/components/preflight/CalibrationsDialog.tsx` (current values table + history per combination) and `RecordCalibrationForm.tsx`; "Calibrations" item in `frontend/src/components/printers/PrinterCard.tsx` menu
- [X] T044 [P] [US3] Vitest `CalibrationsDialog.test.tsx`, `RecordCalibrationForm.test.tsx` in `frontend/src/components/preflight/`

## Phase 7: User Story 4 — Print test results (P2)

**Goal**: results linked to job/version with photo. **Independent test**: record a fail with photo and list by model.

- [X] T045 [US4] Add `"print_tests"` to `OWNER_TYPES` in `backend/app/services/image_storage.py` (single line; out of zone — only once the orchestrator approves)
- [X] T046 [P] [US4] `backend/app/schemas/print_test_result.py`: `TestResultCreate` (`kind`, `outcome` Literals, ids optional, `material` code or id, `orientation` Literal, `measurements: list[dict]` ≤200 items and ≤64 KB, `failure_mode ≤2000`, `notes ≤10000`), `TestResultUpdate`, `TestResultResponse`
- [X] T047 [US4] `backend/app/services/print_test_result_service.py`: create (at least one of version/job; version required for `critical_zone`/`full_part`; version→model consistency; ids in tenant; model_id from version or job), list (filters, newest first, paging), get, update (stamps `updated_by`), `save_photo` / `open_photo` via `ImageStorage(owner_type="print_tests")` replacing an earlier photo
- [X] T048 [US4] `backend/app/api/v1/print_test_results.py` (`create_test_result`, `list_test_results`, `get_test_result`, `update_test_result`, `upload_test_result_photo`, `get_test_result_photo`); register in `backend/app/main.py`
- [X] T049 [P] [US4] `backend/tests/integration/test_print_test_results_api.py`: 201, 401, 422 (bad outcome, neither job nor version, part test without version, non-image photo, >10 MB), 404 (other tenant's job/version/result), filters, PATCH, photo upload/download (storage mocked as in idea image tests), deleted print job leaves result
- [X] T050 [US4] Frontend: `frontend/src/lib/api/printTestResults.ts`, `frontend/src/hooks/usePrintTestResults.ts`, `frontend/src/components/preflight/TestResultsPanel.tsx` (list per model with version, outcome badge, failure mode, photo thumbnail via `components/ideas/AuthImage.tsx`) and `RecordTestResultDialog.tsx`; mount a "Test prints" section, headed by a summary line (open `failure` notes count from the notes list with `severity=failure&status=open`, latest test outcome and its version) for SC-005, in `frontend/src/components/models/ModelDetail.tsx`
- [X] T051 [P] [US4] Vitest `TestResultsPanel.test.tsx`, `RecordTestResultDialog.test.tsx`

## Phase 8: User Story 6 — Agents through MCP (P2)

**Goal**: every read/write above reachable by tokens and tools. **Independent test**: quickstart §5.

- [X] T052 [US6] Rows in `backend/app/auth/api_token_policy.py` for every new handler (reads `read`, writes `write`, photo upload `write`, `delete_brief` absent = JWT-only); update the token-policy route test expectations if they enumerate routes
- [X] T053 [US6] `backend/app/mcp_server/tools/preflight.py` with the 16 tools of contracts/mcp-tools.md (incl. `get_test_result`) (Literal enums, `call_api`, `with_extra`), and append `preflight` to `GROUPS` in `backend/app/mcp_server/tools/__init__.py`
- [X] T054 [P] [US6] `backend/tests/mcp_server/test_tools_preflight.py` (each tool's request path/body, scope registration read vs write, API error surfaces as tool error) and add the tools' example args to `backend/tests/mcp_server/tool_args.py` if the coverage tests require them
- [X] T055 [P] [US6] Token tests in `backend/tests/integration/test_design_briefs_api.py` / `test_calibrations_api.py`: read token reads, read token write → 403, write token writes, any token on `DELETE /design-briefs/{id}` → 403

> Implementation note (round 1): the three API clients and three hooks of T024/T043/T050 are one
> module each, `frontend/src/lib/api/preflight.ts` and `frontend/src/hooks/usePreflight.ts`; pure
> helpers live in `frontend/src/components/preflight/preflightLogic.ts` (fast-refresh rule). The
> Calibrations action (T043) is on the printers page list (`PrinterList.tsx`, FR-019), not the
> live dashboard card. T058's spec is written; it runs with T063.

## Phase 9: Polish & cross-cutting

- [X] T056 Classify new services in `backend/tests/unit/pricing/money_modules.py` `NOT_MONEY_PATHS` if the money-path rule flags them (expected: `calibration_service` only if it imports a model with a money column), with reasons
- [X] T057 Confirm new write routes satisfy `backend/tests/unit/test_write_route_role_guards.py` (add `NOT_ROLE_GUARDED` entries only for genuine reads such as none expected)
- [X] T058 [P] E2E `frontend/e2e/tests/preflight/design-brief.spec.ts` (start brief on an idea, edit function and a load, set `risk` done, revision listed; record a calibration from a printer card; record a test result on a model) using existing e2e helpers and disposable accounts
- [X] T059 [P] Docs: `docs-site/docs/` page on design briefs, calibrations and test results (operator view) and a line in `specs/backlog.md` 009 block Status
- [X] T060 `cd backend; poetry run ruff check; poetry run ruff format --check; poetry run alembic heads` (single head `preflight_v1`)
- [X] T061 `cd frontend; npm run lint; npm run typecheck`
- [X] T062 Send the orchestrator the request for the test go-ahead (SendMessage) and end the turn
- [X] T063 After the go-ahead: disposable stack (Postgres/Redis containers, backend and Vite on free ports ≠ 5433/8000/5173); run the targeted suites of quickstart §2, the registry suites, `npm run test:run` (targeted folders), targeted e2e; fix failures; remove the stack

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → stories. US5 (secrets) depends only on T003/T011. US1 and US2 independent of each other. US3 independent; US4 needs T045 approval for the photo part and references calibrations only through `source_test_result_id` (FK created in T001). US6 needs the routes of US1–US4. Polish last; T063 only after go-ahead.
- Within a story: schema/service before route, route before frontend API, frontend API before components.

## Parallel examples

- Phase 2: T004, T005, T006 in parallel; then T007; T008/T010 in parallel.
- US1: T017, T018, T019, T024 in parallel; T022/T023/T031 in parallel once code exists.
- US3 and US4 backend in parallel with US1/US2 frontend.

## Implementation Strategy

MVP = Phases 1–4 (migration, secrets, design brief). Then US2 (notes), US3, US4, US6, polish.
Every task is implemented with its tests written; tests run in T063 only.

## Phase 10: Convergence

- [X] T064 Test on PostgreSQL (with the immutability triggers) that deleting a printer removes its calibrations and that deleting a print job keeps its test results and calibrations with the link cleared, in `backend/tests/integration/test_preflight_migration.py` per Edge cases "printer deleted" / "print job deleted" (partial)
- [X] T065 Test that a test-result photo over the image size limit is refused and nothing is stored, in `backend/tests/integration/test_print_test_results_api.py` per Edge case "photo exceeds the image size limit" (partial)
