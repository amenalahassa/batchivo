# Implementation Plan: 3MF Import Auto-Fill

**Branch**: `001-3mf-import-autofill` | **Date**: 2026-10-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-3mf-import-autofill/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Parse print time, filament weight, and plate count out of a `.3mf` file's
embedded slicer metadata (Bambu Studio/OrcaSlicer reliably, PrusaSlicer
best-effort) and use the result to pre-fill the model creation form and the
BOM/material weight field — replacing manual re-entry of numbers the
slicer already computed, with the maker always able to review/edit before
saving (see [research.md](research.md) for the technical approach and the
PrusaSlicer reliability caveat discovered during planning).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.9 / React 19 (frontend) — no new language/runtime.

**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 async (backend, unchanged); stdlib `zipfile` + `xml.etree.ElementTree` + `configparser` for parsing (no new dependency — mirrors the existing `extract_3mf_thumbnail()` approach in `backend/app/services/model_file_service.py`); React Hook Form + Zod (frontend form, unchanged); TanStack Query for the new parse call.

**Storage**: N/A — no new table/column; parse result is a transient response shape (see [data-model.md](data-model.md)). Existing PostgreSQL tables (`models`, `model_materials`) are read/written exactly as today.

**Testing**: pytest + pytest-asyncio (backend unit + integration, per repo convention) and Vitest + Testing Library (frontend), per [CLAUDE.md](../../CLAUDE.md) Testing Policy.

**Target Platform**: Existing FastAPI backend + React SPA, deployed via the existing k3s/ArgoCD pipeline — no deployment changes.

**Project Type**: Web application (existing `backend/` + `frontend/` structure) — Option 2 below.

**Performance Goals**: Parsing must not noticeably slow the existing synchronous upload path; `slice_info.config`/`Slic3r_PE.config` are small XML/INI files well under the file's own `MAX_FILE_SIZE` (500MB) ceiling, so parsing cost is dominated by the zip-open already performed for thumbnail extraction, not by this feature.

**Constraints**: No new migration (per project's "Migration Safety" constraint — 90 existing migrations); must not regress existing thumbnail-only behavior for any `.3mf` that was previously supported (FR-010); must not require the model to exist yet (rules out reusing the existing `/{model_id}/files` upload endpoint — see research.md §4).

**Scale/Scope**: One new backend endpoint + one new service function + two frontend integration points (model-creation form, BOM weight field). No change to existing endpoints' contracts.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

`.specify/memory/constitution.md` is still the unfilled template (no
project-specific constitution has been ratified for this repo). In its
absence, this plan is governed by the operative rules already in
[CLAUDE.md](../../CLAUDE.md):

| Gate | Status | Evidence |
|---|---|---|
| Multi-tenant security — every table has `tenant_id`, no unscoped queries | **N/A, pass** | No new table/column (data-model.md); the one new endpoint does no DB query at all (research.md §4), but still gates on `CurrentUser`/`CurrentTenant` for auth consistency (contracts/parse-3mf.md), matching the existing `validate-local-path` precedent. |
| No framework changes | **Pass** | Stdlib-only parsing, no new dependency. |
| Migration safety (~90 existing migrations, must preserve data) | **Pass** | Zero migrations in this feature. |
| No breaking changes to existing routes | **Pass** | Existing `/{model_id}/files` upload and `/materials` endpoints are untouched; the new endpoint is additive. |
| Tests mandatory for every endpoint/bug fix | **Carried into tasks** | quickstart.md enumerates the required success/auth/validation test cases; `/speckit-tasks` will generate them as discrete tasks. |

No violations; Complexity Tracking table below is empty.

**Post-Phase-1 re-check**: data-model.md confirms zero new persisted
fields, contracts/parse-3mf.md confirms the new endpoint is additive and
auth-gated, and quickstart.md's test list satisfies the "tests mandatory"
gate. No gate regressed after design — re-check passes.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── services/
│   │   └── model_file_service.py     # add parse_3mf_metadata() + per-slicer helpers
│   ├── schemas/
│   │   └── model_file.py             # add ThreeMFParseResponse (+ plate sub-shape)
│   └── api/v1/
│       └── model_files.py            # add POST /models/files/parse-3mf
└── tests/
    ├── unit/
    │   └── test_model_file_service.py    # add parse_3mf_metadata() cases
    └── integration/
        └── test_model_files_api.py       # add parse-3mf endpoint cases

frontend/
├── src/
│   ├── lib/api/
│   │   └── models.ts                 # add parse3mfFile()
│   ├── components/models/
│   │   ├── ModelForm.tsx             # accept upload-before-save, pre-fill fields
│   │   └── ModelForm.test.tsx
│   └── components/models/
│       ├── BOMEditor.tsx             # accept + pre-fill a carried-over weight suggestion
│       └── BOMEditor.test.tsx
```

**Structure Decision**: Existing web application layout (`backend/` +
`frontend/`, Option 2). No new top-level directories — every change is an
addition inside already-existing service/schema/route/component files, per
the "no breaking changes, no framework changes" constraint.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations — table intentionally empty.
