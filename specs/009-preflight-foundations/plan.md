# Implementation Plan: Preflight foundations — design brief, typed notes, calibrations and print test results

**Branch**: `claude/009-preflight-f85d55` (spec 009) | **Date**: 2026-11-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/009-preflight-foundations/spec.md`

## Summary

Give the Preflight skill (and the operator) a memory in Batchivo: a design brief per idea/model
(Preflight intent document stored as written and validated like `pf.py validate`, risk, plan,
parameters, 14 step statuses, immutable revisions of intent/risk/plan), typed and dismissible
model file notes, immutable superseding calibrations with a lookup and an `atelier.yaml` export,
print test results with a photo, and printer secrets encrypted at rest with a data migration. All
of it reachable through the REST API and a new MCP tool group. Design decisions: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.9 / React 19 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2 async, Alembic, Pydantic v2, PyYAML (existing),
`cryptography` Fernet via `app/core/encryption.py` (existing), MCP Python SDK (existing, 010);
TanStack Query, shadcn/ui, react-markdown (existing). No new dependency.

**Storage**: PostgreSQL (JSONB, partial unique indexes, RLS, two immutability triggers); images
through `ImageStorage` (local/S3).

**Testing**: pytest (+ MCP tool tests), Vitest, Playwright (targeted). No test runs before the
orchestrator's go-ahead.

**Target Platform**: k3s cluster and single-tenant VPS (same code).

**Project Type**: web application (backend + frontend) + MCP server entry point.

**Performance Goals**: brief, calibration lookup and result list respond like other detail pages
(single indexed queries); no background jobs.

**Constraints**: no breaking change to model file notes or printer connection API; one Alembic
head; tenant isolation by RLS; secrets never logged or returned.

**Scale/Scope**: a workshop: tens of briefs, hundreds of notes, tens of calibrations per printer.

## Constitution Check

| Principle | Status |
|---|---|
| I. Multi-tenant isolation | PASS — 4 new tables with `tenant_id`, RLS forced + policy in migration; routes use `CurrentTenant` + `TenantDB`; every foreign id (idea, model, version, print job, printer, filament type) is checked in the tenant |
| II. Tests ship with the change | PASS (planned) — each endpoint: 200/201, 401, 422, 404; services: success/edge/errors; schema: CRUD, relations, constraints, triggers; migration test; MCP tool tests; frontend component tests; targeted e2e |
| III. One implementation per calculation | PASS — intent validation in `preflight_intent.py` only; calibration precedence in `calibration_service.py` only; secret state in `printer_secrets.py` only; MCP tools forward to the API |
| IV. Money exact | N/A — no money; `value_mm` is `Numeric` and a decimal string anyway |
| V. Derived figures expire | PASS — nothing derived is stored (`validation` and `revision_counts` computed on read) |
| VI. History immutable, provenance visible | PASS — revisions and calibrations immutable (no route + DB trigger); calibrations carry provenance, source print and date; every brief/result change records who and when |
| VII. Deployment through pipeline | PASS — nothing deployed; commit on branch, no push |

Post-design re-check: PASS (no violation, Complexity Tracking empty).

## Project Structure

### Documentation (this feature)

```text
specs/009-preflight-foundations/
├── plan.md, research.md, data-model.md, quickstart.md, tasks.md
├── contracts/api.md, contracts/mcp-tools.md
└── checklists/requirements.md
```

### Source Code

```text
backend/
├── alembic/versions/20261125_preflight.py           # preflight_v1 (down: genai_v1)
├── app/models/design_brief.py                       # DesignBrief, DesignBriefRevision
├── app/models/calibration.py
├── app/models/print_test_result.py
├── app/models/model_file_note.py                    # + type and dismissal columns
├── app/models/printer_connection.py                 # encrypted properties
├── app/models/__init__.py                           # register new models
├── app/schemas/design_brief.py, calibration.py, print_test_result.py
├── app/schemas/model_file_note.py                   # additive fields
├── app/schemas/printer_connection.py                # *_state fields
├── app/services/preflight_intent.py                 # intent validation (pf.py validate mirror)
├── app/services/design_brief_service.py
├── app/services/calibration_service.py
├── app/services/print_test_result_service.py
├── app/services/model_file_note_service.py          # types, filters, dismiss, carry
├── app/services/printer_secrets.py                  # decrypt + secret_state
├── app/services/image_storage.py                    # + "print_tests" owner type (out of zone, asked)
├── app/api/v1/design_briefs.py, calibrations.py, print_test_results.py
├── app/api/v1/model_file_notes.py                   # filters, new fields
├── app/auth/api_token_policy.py                     # rows for new routes (extension point)
├── app/mcp_server/tools/preflight.py + tools/__init__.py
├── app/main.py                                      # 3 include_router lines
└── tests/
    ├── unit/test_preflight_intent.py, unit/test_printer_secrets.py (extend)
    ├── unit/test_calibration_service.py, unit/test_design_brief_service.py
    ├── integration/test_design_briefs_api.py, test_typed_notes_api.py,
    │   test_calibrations_api.py, test_print_test_results_api.py,
    │   test_preflight_models.py, test_preflight_migration.py, test_printer_connection_encryption.py
    └── mcp_server/test_tools_preflight.py

frontend/src/
├── types/preflight.ts, types/model-file-version.ts (note fields)
├── lib/api/designBriefs.ts, calibrations.ts, printTestResults.ts, modelFileNotes.ts (params)
├── hooks/useDesignBrief.ts, useCalibrations.ts, usePrintTestResults.ts
├── components/preflight/   DesignBriefPanel, StepStrip, IntentView, IntentEditor, RiskPlanEditor,
│                           ParamsEditor, BriefRevisionsDialog, TestResultsPanel,
│                           RecordTestResultDialog, CalibrationsDialog, RecordCalibrationForm,
│                           preflightText.ts (+ *.test.tsx)
├── components/viewer/NotesPanel.tsx, NotePins.tsx   # severity/source badges, filters, dismiss
├── components/models/ModelDetail.tsx                # "Design brief" + "Test prints" sections
├── pages/IdeaDetailPage.tsx                         # "Design brief" tab
├── components/printers/PrinterCard.tsx              # "Calibrations" menu item
├── components/printers/PrinterConnectionDialog.tsx  # unreadable secret warning
└── e2e/tests/preflight/design-brief.spec.ts
```

**Structure Decision**: existing web-application layout; three new routers, four new services,
one new MCP tool group, one new frontend component folder.

## Delivery order

1. Migration + models (+ model tests, migration test file).
2. Printer secrets (smallest, independent, security P1).
3. Intent validation + design brief service/API (P1).
4. Typed notes (P1).
5. Calibrations, then print test results (P2).
6. Token policy rows + MCP tools (P2).
7. Frontend: brief panel (idea + model), notes, calibrations, test results, connection warning.
8. Registries, lint/format/typecheck; tests after the go-ahead.

## Preflight skill changes (not made here; to report to the orchestrator)

The skill folder is read-only for this feature. To use what 009 delivers, the skill would need:

1. `SKILL.md`, "Mode Batchivo": name the MCP tools (`get_design_brief`, `start_design_brief`,
   `update_design_brief`, `add_typed_note`, `dismiss_note`, `lookup_calibration`,
   `record_calibration`, `export_atelier_calibrations`, `record_test_result`,
   `upload_test_result_photo`, `list_test_results`) and say each command marks its step with
   `update_design_brief(steps={<command>: ...})`; `risk` stop → `blocked`.
2. `commands/intent.md`, `clarify.md`, `adopt.md`: save `intent.yaml` with
   `update_design_brief(intent_yaml=...)` and use the returned `validation` instead of a local
   `pf.py validate` when in Batchivo mode.
3. `commands/risk.md`: store `risk.md` text, `risk_class` and the `pf.py triage` JSON (`triage`).
4. `commands/plan.md`: store `plan.md` and `params.yaml`; before `pf.py clearance`, either call
   `lookup_calibration` or write `export_atelier_calibrations` into the temporary atelier file
   (the export's item shape is the one `pf.py clearance` reads).
5. `commands/check.md`: severities may be sent as `info`/`attention`/`échec` (accepted); a
   justified ignore = `dismiss_note`.
6. `commands/test.md` / `learn.md`: orientation values must be `vertical` or `horizontal`; record
   results with `record_test_result` (kind `clearance_grid|critical_zone|full_part`) and
   calibrations with `record_calibration` (`provenance: measured`, `source_test_result_id`).
7. `commands/ship.md`: "a passing test" = `list_test_results(model_id, outcome="pass",
   kind∈{critical_zone, full_part})` on the active version.
8. Gaps left to the skill: workshop fields Batchivo does not store (country, seller status, CAD
   licence, safety policy, nozzles, slicer) stay in local `atelier.yaml`; alert confidence stays
   in the note text.
9. Exact numbers: Batchivo returns `value_mm` (atelier export, calibrations) and a typed note's
   `measured_value` / `expected_value` as **decimal strings** (`"0.150"`, `"0.6"`), never JSON
   floats (constitution: no float for an exact figure). `pf.py clearance` passes `value_mm`
   through as `per_side_mm`; anything in the skill that computes with it must parse it
   (`Decimal(str(v))`) rather than assume a number.

## Complexity Tracking

None.
