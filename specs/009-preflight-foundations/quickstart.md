# Quickstart: validate Preflight foundations (spec 009)

Run only after the orchestrator's go-ahead for tests, on a disposable stack (own Postgres/Redis
container, backend and Vite on free ports other than 5433, 8000, 5173).

## 1. Migration

```powershell
cd backend; poetry run alembic upgrade head; poetry run alembic heads   # one head: preflight_v1
```

Expected: tables `design_briefs`, `design_brief_revisions`, `calibrations`, `print_test_results`
with RLS; new note columns; printer secrets encrypted (`tests/integration/test_preflight_migration.py`
checks a clear access code becomes a Fernet token, re-run is a no-op, downgrade restores it).

## 2. Backend suites (targeted)

```powershell
cd backend
poetry run pytest tests/unit/test_preflight_intent.py tests/unit/test_printer_secrets.py tests/integration/test_design_briefs_api.py tests/integration/test_typed_notes_api.py tests/integration/test_calibrations_api.py tests/integration/test_print_test_results_api.py tests/integration/test_preflight_migration.py tests/integration/test_preflight_rls.py tests/integration/test_preflight_models.py tests/integration/test_printer_connection_encryption.py tests/mcp_server -q
poetry run pytest tests/unit/pricing tests/unit/test_write_route_role_guards.py tests/unit/test_sentry_masks_api_tokens.py tests/integration/test_rls_enforced.py tests/integration/test_rls_tenant_isolation.py tests/integration/test_rls_api_tokens.py tests/integration/test_rls_pricing.py tests/integration/test_every_tenant_table_has_rls.py -q
```

Plus the existing note and print-send suites (regression for SC-002 and SC-004):
`tests/integration/test_model_file_notes*.py`, `tests/integration/test_print_send*.py`,
`tests/unit/test_print_send*.py`.

## 3. Round trip with the Preflight template (SC-001)

1. Start a brief on an idea: `POST /api/v1/ideas/{id}/design-brief` with `intent_yaml` = the
   content of `~/.claude/skills/preflight/templates/intent.yaml`.
2. `GET` it back: `intent` equals `yaml.safe_load(template)` key for key.
3. Convert the idea to a model (`POST /ideas/{id}/convert`), then `GET
   /models/{model_id}/design-brief` returns the same brief id.

## 4. Calibrations (SC-003)

`POST /printers/{p}/calibrations` 0.200 then 0.150 for (PLA, vertical, slide); `GET
/calibrations/lookup?...&material=PLA` → 0.150 measured; history lists both, the first
`superseded_by_id` = second; `PATCH /calibrations/{id}` → 405.

## 5. Agent path (SC-006)

With a `read,write` token, over stdio MCP: `start_design_brief` → `update_design_brief` (risk) →
`add_typed_note` (severity `échec`) → `record_calibration` → `record_test_result`. With a read
token, write tools are absent.

## 6. Frontend

```powershell
cd frontend; npm run test:run -- src/components/preflight src/components/viewer src/components/printers; npm run lint; npm run typecheck
npm run test:e2e -- e2e/tests/preflight --project=chromium --reporter=list
```

E2E `e2e/tests/preflight/design-brief.spec.ts`: start a brief on an idea, edit function and a
load in the editor, set step `risk` done, see a revision; record a calibration from the printers
page; record a test result on a model.
