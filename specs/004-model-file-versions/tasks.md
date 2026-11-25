---

description: "Task list for model file versions, measurable source file, 3D viewer and pinned notes"
---

# Tasks: Model File Versions, Measurable Source File, 3D Viewer and Pinned Notes

**Input**: Design documents from `specs/004-model-file-versions/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: Required — the constitution (II) and the spec's constraints demand tests for every
endpoint (200/201, 401, 404, 422) and for the no-geometry, version-switch, delete-active, note
carry-over and oversized-file cases. Write each story's tests first and see them fail.

**Organization**: by user story (spec.md). US1 and US2 are both P1; US1 is the MVP.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on an incomplete task)
- **[Story]**: US1–US4 from spec.md

## Path Conventions

Web app: `backend/app/...`, `backend/tests/...`, `frontend/src/...`, `frontend/e2e/...`

---

## Phase 1: Setup

- [X] T001 Add frontend dependencies `three` (^0.180), `@react-three/fiber` (^9), `@react-three/drei` (^10), `fflate` (^0.8) and `@types/three` (dev) with pnpm, updating `frontend/package.json` and `frontend/pnpm-lock.yaml` (research D5)
- [X] T002 [P] Add small test fixture files to `backend/tests/fixtures/model_files/`: `cube.stl` (20 mm cube), `project_cube.3mf` (mesh-bearing 3MF), `sliced_two_plates.gcode.3mf` (zip with `Metadata/plate_1.gcode`, `Metadata/plate_2.gcode`, `Metadata/slice_info.config`, no mesh), `plain.gcode` (Bambu-style header: `; printer_model = Bambu Lab A1`, `; filament_type = PLA`, `; nozzle_diameter = 0.4`); generate them with a script `backend/tests/fixtures/model_files/make_fixtures.py` so they stay reproducible — done: built in code as `backend/tests/fixtures/model_files.py` (`plain_gcode`, `sliced_3mf`, `block_stl`, `block_3mf`) rather than checked-in binaries
- [X] T003 (after T002) Copy `plain.gcode` and `sliced_two_plates.gcode.3mf` fixtures to `frontend/src/test/fixtures/model-files/` for viewer parser tests — done: built in code as `frontend/src/test/fixtures/modelFiles.ts`

---

## Phase 2: Foundational (blocks every story)

- [X] T004 [P] Create `ModelFileVersion` in `backend/app/models/model_file_version.py` per data-model.md: `tenant_id` NOT NULL; `model_id` FK models ON DELETE CASCADE; `sequence` int NOT NULL "≥ 1", UNIQUE (model_id, sequence); `label` varchar(50) NOT NULL "default = str(sequence), editable, 1–50 chars"; `note` text NULL; `is_active` bool NOT NULL default false with partial UNIQUE (model_id) WHERE is_active; `print_file_id` FK model_files ON DELETE SET NULL (`use_alter=True`); `created_by_user_id` FK users ON DELETE SET NULL
- [X] T005 [P] Create `ModelFileNote` in `backend/app/models/model_file_note.py` per data-model.md: model_id, version_id (CASCADE), model_file_id (SET NULL), `number` int NOT NULL, pos_x/y/z and normal_x/y/z double precision NOT NULL, `layer` int NULL "≥ 0", `text` text NOT NULL "1–2000 chars", `status` varchar(20) CHECK in (`open`, `resolved`, `carried_forward`) default `open`, resolved_in_version_id, carried_to_version_id, carried_from_note_id (all SET NULL), author_user_id (SET NULL), `archived_at` timestamptz NULL
- [X] T006 Add to `backend/app/models/model_file.py`: `version_id` FK model_file_versions ON DELETE CASCADE (indexed), `is_sliced` bool NOT NULL default false, `measurement_reason` varchar(40) NULL; relationships `version`, and `versions`/`file_notes` on `backend/app/models/model.py`; register both new models in `backend/app/models/__init__.py`
- [X] T007 Write migration `backend/alembic/versions/20261103_model_file_versions.py` (down_revision `packaging_advisor_v2`): create both tables; add the three model_files columns; backfill one active version per model with files (sequence 1, label "1", print file = primary sliced else newest sliced) and `is_sliced` from extension / zip content (research D2, D3); then set `version_id` NOT NULL; enable + force RLS with `<table>_tenant_isolation` policies on `model_file_versions` and `model_file_notes` (pattern of `20261025_rls_uncovered_tenant_tables.py`); full downgrade
- [X] T008 Migration test `backend/tests/migrations/test_model_file_versions_migration.py`: models with files get exactly one active version "1" holding all their files; models without files get none; print file chosen per D2; `calculate_model_cost` result for every seeded model identical before and after (SC-004, FR-016); RLS policies exist on both new tables; downgrade then upgrade reaches head — done: `backend/tests/integration/test_migration_model_file_versions.py`
- [X] T009 [P] Model constraint tests `backend/tests/models/test_model_file_version_model.py` and `backend/tests/models/test_model_file_note_model.py`: second active version for a model rejected; duplicate (model_id, sequence) rejected; note status CHECK; cascade on model delete; `model_file_id` nulled on file delete — done: both entities in `backend/tests/unit/test_model_file_version_model.py`
- [X] T010 In `backend/app/services/mesh_bounds.py` give `_Unreadable` a reason code (`no_geometry`, `unreadable`, `too_large`) carried on `Measurement`; in `backend/app/services/model_file_service.py` store it in `measurement_reason` and detect `is_sliced` at upload (`.gcode`, or zip containing `Metadata/plate_<n>.gcode`) (research D3, D11); tests in `backend/tests/services/test_mesh_bounds_reasons.py`
- [X] T011 In `backend/app/services/model_file_service.py` make `upload_file` and `create_local_reference` place every file in a version: explicit `version_id`, or a new version from `new_version_label`/`new_version_note` (created inactive unless the model has none — FR-009, Q3), or else the active version (creating active version 1 if none); write the version label into the legacy `version` column; set the version's `print_file_id` when it has none and the file is sliced; return whether a version was created
- [X] T012 Extend `backend/app/schemas/model_file.py`: `ModelFileResponse` gains `version_id`, `is_sliced`; measurement payload gains `reason`; `ModelFileUploadResponse` gains `version_created: bool`
- [X] T013 Switch `backend/app/api/v1/model_files.py` from `get_db` to `get_tenant_db` (constitution I, research D8) and add optional form fields `version_id`, `new_version_label`, `new_version_note` to `POST /{model_id}/files` (contracts/api.md); the legacy `version` field on `PATCH /{model_id}/files/{file_id}` stays accepted for compatibility but is informational only — grouping follows `version_id`, and a version label change rewrites it
- [X] T014 Compatibility tests `backend/tests/api/test_model_files_api_versions.py`: legacy upload without version fields lands in the active version and still returns 201 with the old fields; list/get include `version_id`, `is_sliced`; cross-tenant file → 404; 401 without token (FR-017, FR-031) — done: `backend/tests/integration/test_model_files_api_versions.py`
- [X] T015 [P] Add `version_id`, `is_sliced`, `measurement.reason`, `version_created` to the `ModelFile` types in `frontend/src/lib/api/models.ts` and create `frontend/src/types/model-file-version.ts` (FileVersion, ActivationPreview, ActivationRow, FileNote) mirroring contracts/api.md

**Checkpoint**: files live in versions; existing behaviour unchanged.

---

## Phase 3: User Story 1 — Attach a measurable source file (P1) 🎯 MVP

**Goal**: an .stl or project .3mf attached on create or edit is kept and measured; a sliced plate gets a plain explanation.

**Independent Test**: create a model with an .stl → dimensions offered; upload a .gcode.3mf → plain message naming the project .3mf or .stl.

### Tests (write first)

- [X] T016 [P] [US1] Backend test `backend/tests/services/test_model_file_measure_on_upload.py`: .stl upload measures and applies dims to a model with none; with operator-entered dims they stay and the measurement is offered (FR-002, FR-003); .gcode.3mf upload is kept with `measurement_status = failed`, `measurement_reason = no_geometry`, `is_sliced = true` (FR-004); applied dims record origin `measured` and the source file id (FR-006) — done: `backend/tests/integration/test_model_files_api_versions.py` (TestMeasuringOnUpload)
- [X] T017 [P] [US1] Frontend test `frontend/src/components/models/FileMeasurementSummary.test.tsx`: `reason = no_geometry` with `is_sliced` renders "This is a sliced plate. It holds the print, not the part's shape, so it can't be measured. Upload the project .3mf (Bambu Studio: File → Save project) or the .stl." and not the raw parser text
- [X] T018 [P] [US1] Frontend test `frontend/src/components/models/ModelForm.test.tsx`: on create and on edit, a chosen source file is uploaded after save; the auto-fill file is uploaded when "Keep this file on the model" is checked (default) and not when unchecked (FR-001, FR-005)

### Implementation

- [X] T019 [US1] Map `measurement.reason` in `frontend/src/components/models/FileMeasurementSummary.tsx` to plain-language messages (`no_geometry` sliced/not sliced, `too_large`, `unreadable`)
- [X] T020 [US1] Let `uploadModelFile` in `frontend/src/lib/api/models.ts` pass `version_id` / `new_version_label` / `new_version_note` and infer `file_type` from the name (`.stl` → source_stl, `.gcode`/`.gcode.3mf` → gcode, other `.3mf` → source_3mf)
- [X] T021 [US1] In `frontend/src/components/models/ModelForm.tsx` add a "Source file (.stl or project .3mf)" picker on create and edit, uploaded after a successful save, with a hint when a `.gcode.3mf` is chosen; turn the existing post-create 3MF attach into a "Keep this file on the model" checkbox (default on) that also works in edit mode

**Checkpoint**: US1 complete and testable alone.

---

## Phase 4: User Story 2 — Versions and the active version (P1)

**Goal**: versions with notes, one active, one print file each; activation reviews figure changes.

**Independent Test**: upload v1 and v2, make v2 active, apply some figures, v1 still downloadable and re-activatable.

### Tests (write first)

- [X] T022 [P] [US2] Service tests `backend/tests/services/test_model_file_version_service.py`: create (inactive unless first); label default and edit; print file must be in version and sliced (422); first sliced file becomes print file; activation preview rows only for differing values, target `model_printer_config` when the planned printer has a config else `model`, weight selectable only with exactly one material, dimensions from newest measured file, notice when none (FR-012, FR-013, D4); a plain `.gcode` print file yields print time from its slicer header, and "not in the file" non-selectable rows when the header lacks it; activate writes only selected fields, records `measured` origin, re-reads values at apply time; print-file switch on the active version goes through preview/activate (FR-012a) — done: through the API in `backend/tests/integration/test_model_file_versions_api.py`
- [X] T023 [P] [US2] Delete-rule tests in `backend/tests/services/test_model_file_delete_rules.py`: last file of active version → refused; active print file with another sliced file → refused; inactive version print file deleted → reassigned to newest remaining sliced; empty inactive version removed (FR-015, D9) — done: `backend/tests/integration/test_model_files_api_versions.py` (TestDeleteRules)
- [X] T024 [P] [US2] History test `backend/tests/services/test_version_switch_history.py`: a price snapshot, an order and a completed production run recorded under v1 keep every figure after activating v2 and applying all fields (FR-014, SC-003) — done: `backend/tests/integration/test_version_switch_history.py`
- [X] T025 [P] [US2] API tests `backend/tests/api/test_model_file_versions_api.py` for every route in contracts/api.md "Versions": 200/201, 401, 403 for viewer role on writes (FR-032), 404 other tenant's model/version, 422 bad label/print file/field, 409 `review_required` and delete 409 codes — done: `backend/tests/integration/test_model_file_versions_api.py`

### Implementation

- [X] T026 [P] [US2] Schemas in `backend/app/schemas/model_file_version.py`: `FileVersionCreate` (label 1–50, note ≤ 2000), `FileVersionUpdate`, `FileVersionResponse`, `ActivationPreview`, `ActivationRow`, `ActivateRequest` per contracts/api.md
- [X] T027 [US2] `ModelFileVersionService` in `backend/app/services/model_file_version_service.py`: list (newest first, with files, uploader, open note count), create, update (label syncs legacy `version` column on its files), set print file (inactive only), `activation_preview` (uses `parse_3mf_metadata`, slicer header for plain .gcode, `item_dimensions` for dims), `activate` (one transaction, partial-unique-safe flip, writes through `ModelPrinterConfigService`, model update + `record_operator_write`, dimension adoption)
- [X] T028 [US2] Delete rules in `ModelFileService.delete_file` in `backend/app/services/model_file_service.py` raising typed errors mapped to 409 codes `last_file_of_active_version` / `active_print_file` in `backend/app/api/v1/model_files.py`
- [X] T029 [US2] Router `backend/app/api/v1/model_file_versions.py` (get_tenant_db, RequireMember on writes) and registration in `backend/app/main.py` with prefix `{api_v1_prefix}/models`, next to `model_files.router`
- [X] T030 [P] [US2] API client `frontend/src/lib/api/modelFileVersions.ts` and hooks `frontend/src/hooks/useModelFileVersions.ts` (list, create, update, preview, activate; invalidate model, cost-profile and files queries on activate)
- [X] T031 [US2] `frontend/src/components/models/VersionActivationDialog.tsx`: rows old → new with checkboxes (non-selectable rows show their reason), the name of the file the dimensions come from (`dimension_file_id`), notices, Apply; used for "Make active" and for changing the active version's print file
- [X] T032 [US2] Rework `frontend/src/components/models/ModelFilesEditor.tsx`: versions newest first with label, note, date, uploader, active badge; files per version with print-file selector; "Make active", download, edit label/note; upload into new or existing version, then the "Make active" offer when `version_created` (FR-009a); on the active version, "No measurable file in the active version" when none of its files is measured (FR-013); 409 messages in plain words; upload, make-active, print-file, edit and delete actions hidden for the viewer role (FR-032)
- [X] T033 [P] [US2] Frontend tests `frontend/src/components/models/VersionActivationDialog.test.tsx` and `frontend/src/components/models/ModelFilesEditor.test.tsx`: only checked rows sent; newest version first; Make-active offer after creating a version; delete refusal message; no-measurable-file notice; viewer role sees no write actions; dimension source file named in the dialog
- [X] T034 [US2] Playwright journey `frontend/e2e/models/file-versions.spec.ts`: upload v1, upload v2 as new version, make active applying only print time, check cost profile badge "Measured" — done: `frontend/e2e/pricing/file-versions.spec.ts`, so it runs in the CI `pricing` project with the seeded owner; not run locally

**Checkpoint**: US1 + US2 deliver the full versioning workflow.

---

## Phase 5: User Story 3 — 3D viewer (P2)

**Goal**: view meshes and toolpaths over the bed; notice for a different slicing target; responsive on large files.

**Independent Test**: open an .stl and a two-plate .gcode.3mf; rotate, layer slider, plate picker, bed outline, mismatch notice.

### Tests (write first)

- [X] T035 [P] [US3] Parser tests `frontend/src/lib/viewer/gcode.test.ts`: absolute/relative moves, extrusion vs travel, G2/G3 flattened, layer detection, header fields (printer_model, filament_type, nozzle_diameter), decimation keeps ≤ 2 000 000 segments and sets `reduced`
- [X] T036 [P] [US3] Worker logic tests `frontend/src/workers/modelParse.test.ts` (test the pure functions the worker calls): plate list from `sliced_two_plates.gcode.3mf`, mesh triangle cap at 1 500 000 with `reduced`, a `.gcode.3mf` with a mesh but no plate G-code falls back to the mesh; "nothing viewable" for a zip without plates or mesh
- [X] T037 [P] [US3] Component tests `frontend/src/components/viewer/ModelViewerDialog.test.tsx` (WebGL mocked): local-reference file shows the explanation (FR-023); no planned printer shows "no planned machine"; mismatch notice text; reduced-preview note

### Implementation

- [X] T038 [P] [US3] Pure G-code parser `frontend/src/lib/viewer/gcode.ts` (research D5): per-layer `Float32Array` segment buffers, header metadata, decimation
- [X] T039 [US3] Worker `frontend/src/workers/modelParse.worker.ts`: receives `ArrayBuffer` + kind, unzips with fflate, lists plates, parses the chosen plate or the mesh (STLLoader/3MFLoader parse functions), applies the 50 MB / caps rule, transfers buffers back (research D6) — done: 3MF meshes are read by `frontend/src/lib/viewer/mesh.ts`, not three's 3MFLoader, which needs `DOMParser` (absent in workers); pure logic in `frontend/src/workers/modelParse.ts`
- [X] T040 [P] [US3] `frontend/src/components/viewer/ViewerCanvas.tsx`: r3f canvas, OrbitControls, bed outline at the planned printer's `bed_size_x_mm` × `bed_size_y_mm` (FR-020)
- [X] T041 [P] [US3] `frontend/src/components/viewer/MeshView.tsx` (solid mesh) and `frontend/src/components/viewer/ToolpathView.tsx` (LineSegments with drawRange layer slider, plate picker) (FR-018, FR-019)
- [X] T042 [US3] `frontend/src/components/viewer/ModelViewerDialog.tsx`: fetches the file via the existing download endpoint, runs the worker, shows loading, the mismatch notice against the model's planned printer and material (FR-021), the reduced-preview note (FR-022) and the local-reference explanation (FR-023)
- [X] T043 [US3] Add a "View" action per file in `frontend/src/components/models/ModelFilesEditor.tsx` opening the dialog through `React.lazy(() => import('@/components/viewer/ModelViewerDialog'))` so three.js is in its own chunk (FR-024)

**Checkpoint**: viewer usable on any uploaded file.

---

## Phase 6: User Story 4 — Pinned notes across versions (P3)

**Goal**: pins on the part or a layer; ghost pins from earlier versions; resolve or carry forward.

**Independent Test**: two notes on v1; open v2: resolve one, carry one; v1 shows "resolved in 2" and "carried forward to 2"; v2 shows one open note.

### Tests (write first)

- [X] T044 [P] [US4] Service tests `backend/tests/services/test_model_file_note_service.py`: create with per-file numbering; normal vector length ≈ 1 enforced; text 1–2000 chars; resolve requires a version of the same model with sequence ≥ note's (422); carry forward creates a new open note on a newer version's file linked by `carried_from_note_id`, original becomes `carried_forward` with unchanged position and text (Q2, FR-029a); carried note cannot be edited (409); ghost query returns open non-archived notes of earlier versions only; deleting a file archives its notes (FR-030) — done: through the API in `backend/tests/integration/test_model_file_notes_api.py`
- [X] T045 [P] [US4] API tests `backend/tests/api/test_model_file_notes_api.py` for every route in contracts/api.md "Notes": 200/201, 401, 403 viewer writes, 404 other tenant, 422, 409 — done: `backend/tests/integration/test_model_file_notes_api.py`

### Implementation

- [X] T046 [P] [US4] Schemas `backend/app/schemas/model_file_note.py` (`NoteCreate`, `NoteUpdate`, `CarryForwardRequest`, `NoteResponse` with `ghost`)
- [X] T047 [US4] `ModelFileNoteService` in `backend/app/services/model_file_note_service.py` (create, list with filters and ghosts, update/resolve/reopen, carry forward, archive_for_file)
- [X] T048 [US4] Call `archive_for_file` from `ModelFileService.delete_file` in `backend/app/services/model_file_service.py` before the file row is removed
- [X] T049 [US4] Router `backend/app/api/v1/model_file_notes.py` (get_tenant_db, RequireMember on writes) and registration in `backend/app/main.py`
- [X] T050 [P] [US4] API client `frontend/src/lib/api/modelFileNotes.ts` and hooks `frontend/src/hooks/useModelFileNotes.ts`
- [X] T051 [US4] `frontend/src/components/viewer/NotePins.tsx`: click-to-place via raycast on mesh or current layer (records layer), numbered pins with drei `Html` tooltips, faded ghost pins with "Resolved in this version" / "Carry forward", drag to reposition a carried note — done: a carried note is repositioned with "Move", then a click on the part
- [X] T052 [P] [US4] `frontend/src/components/viewer/NotesPanel.tsx`: list beside the viewer, status filter, archived toggle, readable at 375 px without the canvas (FR-028)
- [X] T053 [US4] Wire `NotePins` and `NotesPanel` into `frontend/src/components/viewer/ModelViewerDialog.tsx`; hide write actions for viewer role (FR-032)
- [X] T054 [P] [US4] Frontend tests `frontend/src/components/viewer/NotesPanel.test.tsx` and `frontend/src/components/viewer/NotePins.test.tsx`: filter, ghost actions call resolve/carry-forward, viewer role sees no write actions

**Checkpoint**: all four stories work.

---

## Phase 7: Polish & Cross-Cutting

- [X] T055 [P] Operator docs page `docs-site/docs/model-files-and-versions.md`: source vs sliced files, versions, print file, activation review, viewer, notes
- [X] T056 [P] Bundle check test `frontend/src/test/bundle-split.test.ts` (or a script in `frontend/scripts/check-viewer-chunk.mjs` run in CI) asserting `three` is absent from the entry chunk after `npm run build` (SC-007) — done: `frontend/src/test/viewer-chunk-stays-lazy.test.ts` (in `npm test`) and `frontend/scripts/check-viewer-chunk.mjs` (after a build)
- [X] T057 Logging per CLAUDE.md conventions (`logger.info` on version create/activate, note carry-forward; `logger.warning` on refused deletes) in the new services
- [X] T058 Run `cd backend && poetry run pytest && poetry run ruff check && poetry run ruff format --check` and `cd frontend && npm test && npm run lint && npm run typecheck`; fix failures
- [X] T059 Walk `specs/004-model-file-versions/quickstart.md` scenarios 1–13 on the local stack, including the 50 MB responsiveness check (SC-005) and the 375 px notes check

---

## Dependencies & Execution Order

- Phase 1 → Phase 2 → stories. T007 needs T004–T006; T011 needs T006 and T010; T013 needs T011–T012.
- **US1** (Phase 3) needs Phase 2 only.
- **US2** (Phase 4) needs Phase 2; independent of US1 (uploads use the same foundational path).
- **US3** (Phase 5) needs Phase 2 (file response fields) and T001; independent of US1/US2 except T043 edits `ModelFilesEditor.tsx` after T032 when both are built.
- **US4** (Phase 6) needs US3 (viewer) and the version table; T048 edits `model_file_service.py` after T028.
- Polish after the stories it covers.

Same-file sequencing: `model_file_service.py` T010 → T011 → T028 → T048; `ModelFilesEditor.tsx` T032 → T043; `ModelViewerDialog.tsx` T042 → T053; `main.py` T029 → T049.

## Parallel Examples

```text
Phase 2:  T004, T005 together; then T009 and T015 alongside T010–T014
US1:      T016, T017, T018 together (tests), then T019 and T020 together
US2:      T022, T023, T024, T025, T026 together; T030 alongside T027
US3:      T035, T036, T037 together; T038, T040, T041 together
US4:      T044, T045, T046 together; T050, T052 alongside T047
```

## Implementation Strategy

1. **MVP**: Phases 1–3 (US1) — every model can get dimensions from a source file; sliced plates explained.
2. **+ US2**: versions and active version with the review — the core of the request.
3. **+ US3**: viewer.
4. **+ US4**: pinned notes.
Each increment passes the full test suite and ships through the CI/ArgoCD pipeline.

## Phase 8: Convergence

- [X] T060 Upload the files chosen on the model form one after another, not in parallel, in `frontend/src/components/models/ModelForm.tsx` (two concurrent first uploads of a new model both create version 1 and one fails on `uq_model_file_versions_model_sequence`), with a test that the second upload starts only after the first resolves, per FR-001, FR-005 (contradicts)
- [X] T061 Let the model form's file picker in `frontend/src/components/models/ModelForm.tsx` take several files and accept `.stl`, `.3mf`, `.gcode` and `.gcode.3mf`, each uploaded with its inferred type, keeping the sliced-plate hint, with tests in `frontend/src/components/models/ModelForm.test.tsx`, per FR-001 (partial)
- [X] T062 Test the viewer's untested pure parts: `localPick` in `frontend/src/components/viewer/pick.ts`, the layer draw ranges of `ToolpathView` (extract to a pure function) and `parseInWorker`/`fetchModelFile` in `frontend/src/lib/viewer/parseInWorker.ts` with a stubbed Worker and fetch, per Constitution (testing) (partial)

## Phase 9: Convergence

The print figures of a sliced file describe one print run: the chosen plates together. Items per run is what the run produces, read from the objects on those plates, never the number of plates; weight is read per filament.

- [X] T063 Read each plate's objects (excluding `skipped="true"`) and filaments (`type`, `color`, `used_g`) from `Metadata/slice_info.config` into `ThreeMFPlateMetadata.object_count` / `filaments` in `backend/app/services/model_file_service.py` and `backend/app/schemas/model_file.py`, with tests in `backend/tests/unit/test_gcode_metadata.py`, per FR-012, research D4 (partial)
- [X] T064 Make `combined_figures` in `backend/app/services/model_file_version_service.py` count items as the sum of the plates' objects (unknown when a plate does not say) instead of the plate count; propose `prints_per_plate` = items, or a non-selectable row "the file doesn't say how many items this run makes"; divide the per-printer item weight by items, not plates; tests in `backend/tests/integration/test_model_file_versions_api.py`, per FR-012 (contradicts)
- [X] T065 For a model with several materials, propose each bill-of-materials line its own grams by matching the file's filaments on material type and colour; the row is selectable only when every line and every filament match one to one, otherwise it names what did not match; tests, per FR-012 (partial)
- [X] T066 In `frontend/src/components/models/ModelForm.tsx` make the auto-fill ask "How many finished items do these plates make?", defaulting to the chosen plates' object count (never the plate count), show the per-item time and weight, and carry per-filament grams to the bill of materials (`BOMEditor` lists them when there are several); tests in `ModelForm.test.tsx` and `BOMEditor` tests, per FR-005 (contradicts) — helpers in `frontend/src/components/models/threeMfFigures.ts` (+ test); BOMEditor help text corrected to grams per plate run, which is what `costing.py` divides by items
- [X] T067 Show per-line weight proposals in `frontend/src/components/models/VersionActivationDialog.tsx` (`activationText.ts`) with a test, and update `docs-site/docs/model-files-and-versions.md` (items per run, per-filament weight), per FR-012 (partial)

## Phase 10: Convergence

Found in round 3, mostly by the local walkthrough (T059) on a seeded test tenant; each was fixed and tested in the same round.

- [X] T068 For a model with several materials, when the print file gives no weight, show each line's current grams on the non-selectable weight row instead of "not set" (`_labelled_lines` in `backend/app/services/model_file_version_service.py`); regression test `test_a_file_without_weight_shows_each_lines_current_grams` in `backend/tests/integration/test_model_file_versions_api.py`, per FR-012 (partial)
- [X] T069 Label bill-of-materials grams as one plate run, which is how `costing.py` reads them (divided by Items per Plate), in `frontend/src/components/models/BOMEditor.tsx` and `ModelDetail.tsx` (the "Plate Calculation" now divides for the per-item grams instead of multiplying); source tests in `ModelDetail.test.tsx`, per FR-012 and the pricing constitution's one-implementation rule (contradicts)
- [X] T070 Name each material once in the viewer's filament mismatch notice (`frontend/src/lib/viewer/notices.ts`), with `notices.test.ts`, per FR-021 (partial)
- [X] T071 Pass UUIDs, not strings, to `session.get` / UUID comparisons in `backend/tests/integration/test_model_files_api_versions.py` (two delete-rule tests failed depending on test order), per FR-015 / FR-030 (partial)

