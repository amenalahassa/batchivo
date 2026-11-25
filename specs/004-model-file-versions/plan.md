# Implementation Plan: Model File Versions, Measurable Source File, 3D Viewer and Pinned Notes

**Branch**: `004-model-file-versions` | **Date**: 2026-11-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-model-file-versions/spec.md`

## Summary

A model's files are grouped into **versions**; one version per model is active, and each version
marks one sliced file as its **print file**. Making a version active (or changing its print file)
shows a review of the print-time, plate-count, filament-weight and dimension figures that would
change, and writes only the ones the operator picks, through the existing provenance and
dimension-adoption paths. The create and edit model screens can keep a measurable source file, and
a sliced plate's "no geometry" result becomes a plain explanation. A lazy-loaded in-browser viewer
renders meshes and G-code toolpaths (parsed in a Web Worker) over the planned printer's bed, and
operators pin notes on the part; carrying a note to a newer version creates a linked new note.

Technical approach (research.md): a new `model_file_versions` table groups existing `model_files`
rows (a `version_id` FK; the free-text `version` column is kept in step with the version label for
API compatibility); a new `model_file_notes` table; one migration that backfills every existing
model into an active version "1" without touching any cost figure; three.js + react-three-fiber +
fflate on the frontend, with a hand-rolled G-code toolpath parser in a worker.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.9 / React 19 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2 (existing);
frontend adds `three`, `@react-three/fiber` v9, `@react-three/drei` v10, `fflate` (research D5)

**Storage**: PostgreSQL 16 (two new tenant tables under RLS); files stay in the existing storage
backend (local or S3/MinIO) — no new storage

**Testing**: pytest + pytest-asyncio (backend), Vitest + Testing Library (frontend), one Playwright
spec for the version-switch journey

**Target Platform**: Linux server (k3s); evergreen desktop and mobile browsers with WebGL2

**Project Type**: Web application (FastAPI backend + React SPA)

**Performance Goals**: a 50 MB sliced file opens without a main-thread block > 1 s (SC-005); pages
not using the viewer load no slower (SC-007)

**Constraints**: viewer chunk lazy-loaded; worker parsing; full preview ≤ 50 MB, reduced preview
above; existing 500 MB upload cap unchanged; existing model-files API stays compatible (FR-017)

**Scale/Scope**: tens to low hundreds of files per tenant, a handful of versions per model,
tens of notes per file

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan complies |
|-----------|--------|------------------------|
| I. Multi-tenant isolation | PASS (with a fix) | Both new tables carry `tenant_id`, RLS enabled + forced with the `<table>_tenant_isolation` policy (pattern of `20261025_rls_uncovered_tenant_tables.py`). New endpoints use `get_tenant_db`. The existing `model_files` router uses `get_db` today; this change moves it to `get_tenant_db` (research D8). |
| II. Tests are part of the change | PASS | Every new endpoint gets 200/201, 401, 404, 422 tests; migration, version switch, delete rules, note carry-over, no-geometry and oversized-preview cases are listed in tasks. |
| III. One implementation per calculation | PASS | Print figures come from the existing `parse_3mf_metadata`; dimensions from `mesh_bounds` + `item_dimensions` (adopt path). The activation preview calls these; it does not re-derive cost. Cost stays computed by `costing.py`. |
| IV. Money exact, settings honoured | PASS | No money is computed here. Applied figures go through the same model / printer-config writers that the cost profile uses. |
| V. Derived figures expire with inputs | PASS | Nothing derived is stored except `model_files.is_sliced`, a property of immutable file content (a file is never edited in place), set once at upload. |
| VI. History immutable, provenance visible | PASS | Activation never rewrites price snapshots, orders or production runs (FR-014); applied figures are recorded as `measured` via `record_operator_write`; dimensions keep their `measured` origin and source file id. Carried notes create new rows, the original keeps its position (clarification Q2). |
| VII. Deployment via pipeline | PASS | Ships as an Alembic migration + code through CI/ArgoCD. |

No unjustified violation. One deliberate structural choice is recorded in Complexity Tracking.

**Post-design re-check (after Phase 1)**: unchanged — PASS. The data model adds no stored cost
figure, and the activation endpoint writes through existing provenance-aware services.

## Project Structure

### Documentation (this feature)

```text
specs/004-model-file-versions/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── api.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
backend/
├── alembic/versions/20261103_model_file_versions.py      # new tables, version_id, backfill, RLS
├── app/models/model_file_version.py                       # new
├── app/models/model_file_note.py                          # new
├── app/models/model_file.py                               # + version_id, is_sliced
├── app/schemas/model_file_version.py                      # new
├── app/schemas/model_file_note.py                         # new
├── app/schemas/model_file.py                              # + version_id, is_sliced, measurement reason
├── app/services/model_file_version_service.py             # new: versions, print file, activation preview/apply
├── app/services/model_file_note_service.py                # new: notes, resolve, carry forward, archive
├── app/services/model_file_service.py                     # upload into a version, is_sliced, delete rules
├── app/services/mesh_bounds.py                            # reason code for "no geometry"
├── app/api/v1/model_file_versions.py                      # new router
├── app/api/v1/model_file_notes.py                         # new router
├── app/api/v1/model_files.py                              # get_tenant_db, version_id form field, 409s
└── tests/
    ├── models/test_model_file_version_model.py
    ├── services/test_model_file_version_service.py
    ├── services/test_model_file_note_service.py
    ├── api/test_model_file_versions_api.py
    ├── api/test_model_file_notes_api.py
    ├── api/test_model_files_api_versions.py               # compat + delete rules
    └── migrations/test_model_file_versions_migration.py

frontend/
├── src/types/model-file-version.ts                        # new
├── src/lib/api/modelFileVersions.ts                       # new
├── src/lib/api/modelFileNotes.ts                          # new
├── src/hooks/useModelFileVersions.ts                      # new
├── src/hooks/useModelFileNotes.ts                         # new
├── src/components/models/ModelFilesEditor.tsx             # versions list, print file, make active
├── src/components/models/VersionActivationDialog.tsx      # figure review
├── src/components/models/FileMeasurementSummary.tsx       # plain no-geometry message
├── src/components/models/ModelForm.tsx                    # source file + keep-parsed-file on create and edit
├── src/components/viewer/ModelViewerDialog.tsx            # lazy entry (React.lazy)
├── src/components/viewer/ViewerCanvas.tsx                 # r3f scene, bed outline, controls
├── src/components/viewer/MeshView.tsx
├── src/components/viewer/ToolpathView.tsx                 # layer slider, plate picker
├── src/components/viewer/NotePins.tsx                     # pins, ghost pins, tooltips
├── src/components/viewer/NotesPanel.tsx                   # list + filter, phone-readable
├── src/workers/modelParse.worker.ts                       # unzip, G-code parse, mesh decode, decimation
└── src/lib/viewer/gcode.ts                                # pure G-code parser (unit-tested)
```

**Structure Decision**: existing web-app layout (`backend/app/...`, `frontend/src/...`); the viewer
gets its own `components/viewer/` folder so it forms one lazy chunk.

## Complexity Tracking

| Choice | Why Needed | Simpler Alternative Rejected Because |
|--------|------------|-------------------------------------|
| New `model_file_versions` table rather than only the `version` text column and `is_primary` | A version needs its own label, note, active flag, print file and uploader, and "one active per model" must be a database constraint | Reusing `is_primary` (unique per model **and file type**) cannot express "one active version" or "one print file per version"; the free-text `version` column cannot carry a note or an active flag without duplicating them on every file row. ModelFile is reused for files — this table groups them, it is not a parallel file table. |
