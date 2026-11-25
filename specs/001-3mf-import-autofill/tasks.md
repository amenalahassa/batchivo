---

description: "Task list for 3MF Import Auto-Fill"
---

# Tasks: 3MF Import Auto-Fill

**Input**: Design documents from `/specs/001-3mf-import-autofill/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/parse-3mf.md](contracts/parse-3mf.md), [quickstart.md](quickstart.md)

**Tests**: Included and mandatory — per `CLAUDE.md`'s "All code MUST have tests — no exceptions" and the Testing Policy table (new endpoint → success/auth/validation/not-found; bug-fix-shaped edge cases → regression test). This overrides the template's default "tests are optional."

**Organization**: Tasks are grouped by user story (US1, US1a, US2, US3 — see spec.md) to enable independent implementation and testing of each.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to
- File paths are exact and relative to the repo root

---

## Phase 1: Setup

**Purpose**: Shared test fixtures and constants every later phase depends on.

- [X] T001 [P] Create backend test fixture `.3mf` files under `backend/tests/fixtures/3mf/`: `bambu_single_plate.3mf` (one plate, known `prediction`/`weight` values), `bambu_multi_plate.3mf` (3 plates), `prusaslicer_export.3mf`, and `not_a_3mf.txt` (invalid/non-zip content) — real or hand-constructed zips are both acceptable as long as the Bambu/Orca ones contain a genuine `Metadata/slice_info.config` matching research.md §1's structure
- [X] T002 [P] Add the two slicer-metadata path constants to `backend/app/services/model_file_service.py`, placed near the existing `thumbnail_paths` list: `Metadata/slice_info.config` (Bambu/OrcaSlicer) and `Metadata/Slic3r_PE.config` (PrusaSlicer)

**Checkpoint**: Fixtures and constants exist; foundational implementation can begin.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared parsing engine and endpoint every user story's tests exercise. No story-specific work can be verified until this phase is done.

**⚠️ CRITICAL**: No user story task can be completed/tested until this phase is complete.

- [X] T003 Add the parse-result response schema to `backend/app/schemas/model_file.py`: a `ThreeMFParseResponse` model with exactly the fields from data-model.md's "3MF Parse Result" table — `print_time_minutes: Optional[int]`, `filament_weight_grams: Optional[float]`, `plate_count: Optional[int]`, `source_plate_index: Optional[int]`, `slicer_detected: Optional[str]` (one of `"bambu_orca"`, `"prusaslicer"`, or `None`), `thumbnail_available: bool`. Every field except `thumbnail_available` MUST be independently nullable per data-model.md's validation rules.
- [X] T004 Implement `parse_3mf_metadata(file_content: bytes) -> ThreeMFParseResponse` in `backend/app/services/model_file_service.py`: open one `zipfile.ZipFile` (do not re-open if called alongside `extract_3mf_thumbnail()` in the same request — pass the already-read `file_content` through, same as the thumbnail extractor does), try the Bambu/Orca path first (`Metadata/slice_info.config`, XML: read `<plate>` elements' `index`/`prediction`/`weight` metadata keys and `<filament used_g=...>` children per research.md §1), then the PrusaSlicer path (`Metadata/Slic3r_PE.config`) if the first yields nothing, and set `slicer_detected` accordingly (`None` if neither path matched). Depends on: T001, T002.
- [X] T005 In `parse_3mf_metadata()`, apply data-model.md's sanity rule verbatim: "a parsed `0` or negative value is treated as unparseable and nulled out before returning" for both `print_time_minutes` and `filament_weight_grams`. Wrap the whole function body in the same `try/except zipfile.BadZipFile` / broad `except Exception` pattern `extract_3mf_thumbnail()` already uses, logging at `warning`/`debug` level, so it never raises for malformed/missing metadata (FR-007). Depends on: T004.
- [X] T006 Add `POST /api/v1/models/files/parse-3mf` to `backend/app/api/v1/model_files.py`, modeled on the existing `validate-local-path` endpoint in the same file (auth via `CurrentUser`/`CurrentTenant`, no DB query, no `model_id` path param). Validate the upload with the same size/extension checks `ModelFileService._validate_file()` already applies (raise `HTTPException(400)` on failure, per contracts/parse-3mf.md and FR-009), then call `parse_3mf_metadata()` and `extract_3mf_thumbnail()` on the same `file_content` to build the full `ThreeMFParseResponse` including `thumbnail_available`. Depends on: T003, T004, T005.
- [X] T007 [P] Add `parse3mfFile(file: File): Promise<ThreeMFParseResponse>` to `frontend/src/lib/api/models.ts`, mirroring `uploadModelFile()`'s existing multipart-upload pattern in the same file, and add the matching `ThreeMFParseResponse` TypeScript type (mirrors contracts/parse-3mf.md's response shape).

**Checkpoint**: Parser + endpoint + typed client exist and are independently callable — user story work can begin.

---

## Phase 3: User Story 1 - Pre-fill model form from an uploaded 3MF (Priority: P1) 🎯 MVP

**Goal**: Uploading a `.3mf` during model creation pre-fills print time and plate count, editable, without blocking creation.

**Independent Test**: Upload a known-good `.3mf` to the model creation flow and confirm print time/plate count match the slicer's own summary, and that edited values (not parsed ones) are what get saved.

### Tests for User Story 1

- [X] T008 [P] [US1] Unit test in `backend/tests/unit/test_model_file_service.py`: `parse_3mf_metadata()` against `bambu_single_plate.3mf` (T001) returns the fixture's known `print_time_minutes` and `plate_count` (1), with `slicer_detected == "bambu_orca"`.
- [X] T009 [P] [US1] Integration tests in `backend/tests/integration/test_model_files_api.py` for `POST /api/v1/models/files/parse-3mf`: success (200) with `bambu_single_plate.3mf`, and auth failure (401) with no token — per CLAUDE.md's "New endpoint" test matrix.
- [X] T010 [P] [US1] Frontend test in `frontend/src/components/models/ModelForm.test.tsx`: uploading a `.3mf` in `mode="create"` pre-fills `print_time_hours`/`print_time_minutes`/`prints_per_plate`, and editing a pre-filled field before submit results in the edited value being submitted, not the parsed one (Acceptance Scenario 3).

### Implementation for User Story 1

- [X] T011 [US1] Add a `.3mf` upload control to `frontend/src/components/models/ModelForm.tsx` (create mode only) that calls `parse3mfFile()` (T007) on file selection and pre-fills `print_time_hours`/`print_time_minutes` (split from the response's `print_time_minutes`, matching the existing hours/minutes split logic already in this file) and `prints_per_plate` (from `plate_count`) — leaving any field the response returned `null` for untouched (FR-007). Depends on: T006, T007.
- [X] T012 [US1] Confirm/adjust `ModelForm.tsx` form state so pre-filled values are ordinary controlled-field defaults, not read-only — the maker can edit any of them before submit, and `onSubmit` reads current form values, never the original parse response (FR-005). Depends on: T011.

**Checkpoint**: User Story 1 fully functional and independently testable/demoable.

---

## Phase 4: User Story 1a - Carry parsed weight to the material/BOM step (Priority: P1)

**Goal**: The weight parsed from the same `.3mf` upload is offered as a suggestion when the maker records which material was used, without picking a spool for them.

**Independent Test**: Create a model from a `.3mf` with a known weight (US1), open the add-material step for that model, and confirm the weight field is pre-filled while the spool selector starts unselected.

### Tests for User Story 1a

- [X] T013 [P] [US1a] Unit test in `backend/tests/unit/test_model_file_service.py`: `parse_3mf_metadata()` against `bambu_single_plate.3mf` (T001) returns the fixture's known `filament_weight_grams`.
- [X] T014 [P] [US1a] Frontend test in `frontend/src/components/models/BOMEditor.test.tsx`: when a suggested-weight prop is provided, the `weight_grams` field of `materialFormSchema` is pre-filled with it on the first "Add Material" dialog open, while `spool_id` (`SearchableSpoolSelect`) stays unselected (Acceptance Scenario 1); editing the weight field before save results in the edited value being saved (Acceptance Scenario 2).

### Implementation for User Story 1a

- [X] T015 [US1a] In `frontend/src/pages/ModelCreatePage.tsx` and `frontend/src/components/models/ModelForm.tsx`, hold the parsed `filament_weight_grams` from the `.3mf` upload in memory through model creation and forward it to the model detail page's initial render after a successful create (client-side only, per research.md §5 — no new backend persistence). Depends on: T011. (Implemented entirely in `ModelForm.tsx` via a `parsedWeightGrams` state + `sessionStorage` hand-off on `createMutation.onSuccess`; `ModelCreatePage.tsx` needed no change since it's a pure pass-through wrapper.)
- [X] T016 [US1a] In `frontend/src/components/models/BOMEditor.tsx`, accept an optional suggested-weight prop/value and use it as the initial `weight_grams` value in `materialFormSchema`'s default values the first time the "Add Material" dialog opens for a model, without setting `spool_id` (FR-004a). Depends on: T015. (Implemented as a `useEffect` reading+clearing the `model-weight-suggestion:<modelId>` sessionStorage key rather than a prop, since the suggestion originates on a different page/route than `BOMEditor` renders on.)

**Checkpoint**: User Stories 1 and 1a both independently functional.

---

## Phase 5: User Story 2 - Graceful fallback when metadata can't be parsed (Priority: P2)

**Goal**: Malformed, unsupported, or partially-missing `.3mf` metadata never blocks model creation — unparsed fields stay blank for manual entry.

**Independent Test**: Upload a `.3mf` with corrupted/missing/unsupported metadata and confirm model creation still completes, with only the parseable fields pre-filled.

### Tests for User Story 2

- [X] T017 [P] [US2] Unit tests in `backend/tests/unit/test_model_file_service.py`: `parse_3mf_metadata()` against `not_a_3mf.txt` (T001) returns an all-null result with no exception raised; against a crafted fixture with `prediction` present but `weight` missing, returns `print_time_minutes` populated and `filament_weight_grams` null (Edge Cases, FR-007). Also covers the corrupted-`.3mf`-extension and zero/negative-value cases.
- [X] T018 [P] [US2] Integration tests in `backend/tests/integration/test_model_files_api.py` for `POST /api/v1/models/files/parse-3mf`: wrong extension (e.g. `.py`) → 400 (FR-009); `prusaslicer_export.3mf` (valid zip, no recognizable results) → 200 with all parse fields null; `.3mf`-extensioned corrupted content → 200 with all parse fields null (corrected per contracts/parse-3mf.md's amended 400 semantics).
- [X] T019 [P] [US2] Frontend test in `frontend/src/components/models/ModelForm.test.tsx`: when `parse3mfFile()` resolves with all-null fields, every form field remains at its existing blank/manual-entry default and the form can still be submitted (SC-003).

### Implementation for User Story 2

- [X] T020 [US2] Review `ModelForm.tsx`'s upload handler (T011) and confirm a null/partially-null parse response never disables a field or blocks submission — fields simply keep their pre-upload default. Adjust only if T019 finds a gap. Depends on: T011, T019. (T019 found no gap - the implementation already guards every `setValue` call behind a non-null check, so an all-null response is a no-op and submission proceeds normally.)

**Checkpoint**: User Stories 1, 1a, and 2 all independently functional — the feature cannot break manual model creation.

---

## Phase 6: User Story 3 - Multi-plate and multi-object files (Priority: P3)

**Goal**: Multi-plate `.3mf` files report an accurate total plate count, sourcing the pre-filled time/weight from the first plate.

**Independent Test**: Upload a 3-plate `.3mf` and confirm `plate_count == 3` with time/weight taken from plate 1.

### Tests for User Story 3

- [X] T021 [P] [US3] Unit test in `backend/tests/unit/test_model_file_service.py`: `parse_3mf_metadata()` against `bambu_multi_plate.3mf` (T001) returns `plate_count == 3`, `source_plate_index == 1`, and `print_time_minutes`/`filament_weight_grams` matching plate 1's values specifically (FR-008).

### Implementation for User Story 3

- [X] T022 [US3] Extend `parse_3mf_metadata()` in `backend/app/services/model_file_service.py` to iterate every `<plate>` element for `plate_count`, while sourcing `print_time_minutes`/`filament_weight_grams`/`source_plate_index` from the first plate encountered only, per FR-008. Depends on: T004, T005. (Already implemented as part of T004 — `parse_3mf_metadata()` iterates all `<plate>` elements for `plate_count` and sources values from `plates[0]`; T021's test confirms this against a real 3-plate fixture.)

**Checkpoint**: All four user stories independently functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T023 [P] Run `cd backend && poetry run pytest && poetry run ruff check` and `cd frontend && npm test && npm run lint` across all changed files, per CLAUDE.md's pre-commit requirement.
- [ ] T024 [P] Walk through [quickstart.md](quickstart.md) end-to-end against one real Bambu/OrcaSlicer sample and one real PrusaSlicer sample; if PrusaSlicer parsing never succeeds on real files, note that outcome back into research.md §2 rather than silently leaving the fixture-only test (T013/T017) as the sole evidence.
- [X] T025 [P] Update idea #2's status line in the maker's local `notes/feature-ideas.md` (excluded from the repo — see its own header) from "not implemented" to reflect what shipped; this is a personal-notes edit, not part of the PR.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup (needs T001's fixtures to exist before anything can be tested, T002's constants before parsing can be written) — BLOCKS all user stories.
- **User Stories (Phase 3-6)**: All depend on Foundational completion. US1 and US2 also share `ModelForm.tsx`'s upload handler (T011) — US2's task (T020) depends directly on it. US1a depends on US1's upload handler existing (T015 depends on T011). US3 extends the same parser function as Foundational (T022 depends on T004/T005) and has no frontend dependency on US1/US1a/US2.
- **Polish (Phase 7)**: Depends on all four user stories being complete.

### User Story Dependencies

- **US1 (P1)**: No dependency on other stories.
- **US1a (P1)**: Depends on US1's upload handler (T011) existing, since it reuses the same upload moment to capture the weight value — not independently implementable before US1, but independently *testable* once US1 exists.
- **US2 (P2)**: Depends on US1's upload handler (T011) existing to verify against; otherwise no new coupling.
- **US3 (P3)**: No dependency on US1/US1a/US2 — purely a backend parser extension, independently testable via T021 alone.

### Parallel Opportunities

- T001 and T002 (Setup) in parallel.
- T007 (frontend client) in parallel with T003-T006 (backend) since it only needs contracts/parse-3mf.md, not the running endpoint, to be written against — but running its own tests needs T006 done first.
- All `[P]` test tasks within a phase (e.g., T008/T009/T010; T013/T014; T017/T018/T019) in parallel with each other.
- US3 (T021, T022) can proceed in parallel with US1a/US2 once Foundational is done, since it touches no shared frontend file.

---

## Parallel Example: Foundational Phase

```bash
Task: "Create backend test fixture .3mf files under backend/tests/fixtures/3mf/"
Task: "Add slicer-metadata path constants to backend/app/services/model_file_service.py"
```

## Parallel Example: User Story 1 Tests

```bash
Task: "Unit test parse_3mf_metadata() Bambu/Orca happy path in backend/tests/unit/test_model_file_service.py"
Task: "Integration test POST /models/files/parse-3mf success+auth in backend/tests/integration/test_model_files_api.py"
Task: "Frontend test ModelForm pre-fill+edit-override in frontend/src/components/models/ModelForm.test.tsx"
```

---

## Implementation Strategy

### MVP First (User Story 1 + 1a)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (parser + endpoint + client — blocks everything)
3. Complete Phase 3: User Story 1 → **validate independently**
4. Complete Phase 4: User Story 1a → **validate independently**
5. This pair is the MVP: both halves of "don't retype numbers the slicer already computed" from the originating gap report.

### Incremental Delivery

1. Setup + Foundational → shared engine ready.
2. US1 → demo: model form pre-fill works.
3. US1a → demo: BOM weight suggestion works (completes the MVP).
4. US2 → demo: malformed/unsupported files no longer need special-case handling by the maker.
5. US3 → demo: multi-plate files report an accurate plate count.
6. Polish → lint/tests clean, quickstart validated against real files.

---

## Phase 8: Convergence

- [X] T026 Capture the selected `.3mf` `File` in `ModelForm.tsx` component state as soon as it's chosen (not only inside the `parse3mfFile()` try block, so it survives a parse failure per FR-006's "regardless of whether metadata parsing succeeds"), and after `createMutation`'s `createModel` call succeeds, upload that file via `uploadModelFile(data.id, file, 'source_3mf')` so the model gets both a `ModelFile` record and the persisted thumbnail through the existing `_extract_and_save_3mf_thumbnail` path — exactly as the pre-existing post-creation upload flow already does. Add/extend a `ModelForm.test.tsx` case asserting `uploadModelFile` is called with the originally-uploaded file after a successful create. Per FR-006 / US1 Acceptance Scenario 1 (missing): today, models created through the new upload-during-creation flow get pre-filled form fields but end up with no attached file and no thumbnail at all, which regresses "the thumbnail is extracted as before."
