# Implementation Plan: Generative AI layer, Replicate first

**Branch**: `claude/elastic-clarke-98bb9f` (spec dir `008-genai`) | **Date**: 2026-11-24 | **Spec**: [spec.md](spec.md)

**Input**: `specs/008-genai/spec.md` (clarified Q1–Q4). Architecture: `docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §5.

## Summary

A provider-agnostic generative-AI layer, `backend/app/services/genai/`, with a Replicate adapter.

- **Callers**: screens and agents ask for a *capability*. A code catalog maps each capability to
  a pinned model version and a price, and tenants may override it.
- **Jobs**: every request is an immutable job (inputs, version, seed, price snapshot). Short
  chained Celery tasks submit and poll it; an optional signed webhook finishes it sooner.
  Outputs are copied into Batchivo storage before the job is marked succeeded.
- **Cost**: estimated before submission and computed after, by one service (USD, `Decimal`). A
  per-tenant monthly budget and a concurrency limit are checked atomically before submission.
- **Adoption** is always explicit:
  - into an idea: a `generation` timeline entry; an image, or a 3D viewer for a mesh;
  - into a product: a new image with origin `ai`, an AI badge, and a warning for concept images
    and 3D drafts;
  - into a model: the GLB is converted to STL and added as an inactive "AI draft" version, never
    applied to the model's dimensions.
- **Idea conversion** carries adopted 3D drafts to the new model (Q4).
- **Settings → AI**: token (encrypted, masked, tested), budget, usage and model overrides.
- **Platform token** (Q2): used only for shops a platform admin authorises.
- **Roles** (Q3): member and up generate; viewers read.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.9 / React 19 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, httpx (already a
dependency), Celery + Redis (existing, with `run_in_task_loop`), Pillow, the existing
`ImageStorage` and `ModelFileService`. Frontend: TanStack Query, shadcn/ui, three (existing
viewer). **No new dependency.**

**Storage**: PostgreSQL, with 3 new tables under RLS, 1 new column and 1 new FK. Images are kept
in local or S3 storage by `GenAIFileStore` (same root and S3 settings as `ImageStorage`): outputs
under `generations/{job_id}/` at full resolution, meshes as is, and imported inputs under
`generations/uploads-{tenant_id}/`, one copy per job.

**Testing**: pytest + respx (Replicate is always mocked), Vitest + Testing Library, and targeted
Playwright against a local fake provider.

**Target Platform**: k3s cluster (multi-tenant) and the single-shop VPS bundle.

**Project Type**: web application (backend + frontend).

**Performance Goals**:

- creating a job answers in under 500 ms (validation, lock, insert, enqueue);
- the screen sees the status within 2 s (polling);
- outputs are stored within 60 s of provider completion.

**Constraints**:

- the token never reaches the frontend or the logs;
- inputs are tenant-owned assets only;
- money is a `Decimal` in USD, sent as strings;
- no breaking change to the 004 or 007 APIs.

**Scale/Scope**: tens of jobs per tenant per day, at most 3 concurrent per tenant by default;
18 endpoints, 1 reusable dialog, and integrations on 4 pages.

## Constitution Check

*GATE: checked before Phase 0 and re-checked after Phase 1.*

| Principle | How the design complies | Status |
|---|---|---|
| I. Multi-tenant isolation | (3 justified route exceptions, see Complexity Tracking) 3 new tables with `tenant_id` and ENABLE/FORCE RLS policies; endpoints use `CurrentTenant` + `TenantDB`; services also filter by `tenant_id`; the webhook sets the RLS context from the path's tenant before any query, and checks the job and prediction id; input assets resolve only within the tenant; cross-tenant 404 tests on every resource | PASS |
| II. Tests ship with the change | Endpoint tests (200/201, 401, 403, 404, 422); service tests for validation, budget, concurrency, polling, webhook (valid and invalid), download/store, failure, timeout and adoption; migration CRUD and constraints; GLB converter; frontend component and hook tests; targeted e2e | PASS |
| III. One implementation per calculation | Cost only in `GenAICostService`; product, model and idea writes reuse `ImageStorage.copy_image`, `ModelFileService.upload_file` and the idea entry creation in `IdeaService`; GLB → STL in one module; the frontend shows the API's estimate and never multiplies | PASS |
| IV. Money exact, settings honoured | `Numeric(12,4)` and `Decimal`, quantised at storage, strings on the wire; the budget and model overrides configured by the tenant are what the checks and submission use, and a code default never shadows them | PASS |
| V. Derived figures expire | Month-to-date is computed on read and never stored | PASS |
| VI. History immutable, provenance visible | Job inputs, version, seed and price snapshot are written once; cost carries `cost_provenance`; product images carry `origin`; adoptions record who and when | PASS |
| VII. Pipeline-only deployment | No deploy; a commit on the worktree branch, never pushed. A new Celery beat entry and env vars are documented; manifests are untouched (see "Deployment notes") | PASS |
| Additional: Alembic, single head | One revision `genai_v1`, re-pointed onto the main head after 011 merges; the downgrade drops what it adds | PASS |

Three routes cannot take `get_current_tenant`. Each is justified below.

## Complexity Tracking

| Deviation | Why needed | Compensating control / simpler alternative rejected |
|---|---|---|
| `POST /genai/webhooks/replicate/{tenant_id}/{job_id}` has no `get_current_tenant` (the provider is not a signed-in user) | The provider calls back without a Batchivo session (FR-010) | The handler sets the RLS context to the path's tenant before any query (`app.core.rls.set_rls_context`). Only that tenant's job is loaded, and the body's prediction id must equal the job's `external_id`. The HMAC is checked with that tenant's own signing secret before anything is written. Tests cover a cross-tenant path → 404. Same pattern as the existing Square and Shopify webhooks. Polling only would be simpler, but it gives up the faster completion the spec asks for when the instance is reachable. |
| `GET/PUT /platform/tenants/{id}/genai` uses `PlatformAdmin`, not `CurrentTenant` | A platform admin acts on another tenant (Q2), like the existing `api/v1/platform.py` routes | `get_platform_admin` dependency, an audit log entry per change, and the change limited to the single `platform_token_allowed` key |
| `/genai/e2e-fake/*` has no tenant | It imitates the external provider for local e2e only | Mounted only when `e2e_test_hooks_enabled` (refused in production by config); it touches no table |

## Project Structure

### Documentation

```text
specs/008-genai/
├── plan.md, research.md (R1–R14), data-model.md, quickstart.md
├── contracts/genai-api.md
├── checklists/requirements.md
└── tasks.md
```

### Source code: files this feature touches

```text
backend/
├── alembic/versions/20261124_genai.py                  # new (zone)
├── app/config.py                                       # + replicate_api_token, genai_* settings (additive lines)
├── app/models/generation_job.py                        # new: GenerationJob, GenAIAsset, GenAIAdoption (zone)
├── app/models/__init__.py                              # register the 3 models (one line each)
├── app/models/product_image.py                         # + origin            [granted? see "Boundary requests"]
├── app/models/idea.py                                  # FK on generation_job_id [granted? see below]
├── app/schemas/genai.py                                # new (zone)
├── app/schemas/product_image.py                        # + origin            [granted? see below]
├── app/schemas/tenant_settings.py                      # + Replicate settings schemas (zone)
├── app/services/tenant_settings.py                     # + get/update/test Replicate settings (zone)
├── app/services/genai/__init__.py, capabilities.py, catalog.py, base.py, replicate.py,
│   costs.py, credentials.py, glb.py, storage.py, service.py, runner.py, adoption.py, errors.py,
│   logging.py                                          # new (zone)
├── app/services/idea_service.py                        # convert(): one call to carry_idea_drafts (granted, Q4)
├── app/services/model_file_service.py                  # upload_file(commit=, offer_measurement=), delete_stored_file() [request]
├── app/services/model_file_version_service.py          # create_version(activate_if_first=) [request]
├── app/tasks/genai.py                                  # new: submit, poll, sweep (zone)
├── app/tasks/celery_app.py                             # + include "app.tasks.genai", + beat "genai-sweep" (additive lines)
├── app/api/v1/genai.py                                 # new: capabilities, estimate, jobs, uploads, assets, adopt, webhook (zone)
├── app/api/v1/genai_settings.py                        # new: /settings/replicate (zone)
├── app/api/v1/genai_platform.py                        # new: /platform/tenants/{id}/genai (zone)
├── app/api/v1/genai_e2e.py                             # new: fake provider, mounted only with E2E hooks (zone)
├── app/main.py                                         # include the 4 routers (added lines only)
├── app/api/v1/products.py                              # PATCH image: an AI image keeps its label (3 added lines, standing approval)
└── tests/
    ├── utils/genai.py                                   # fixtures: replicate_mock (respx, assert_all_mocked), dispatch recorder, builders
    └── genai/                                           # conftest + test_units.py (config levers, capabilities, catalog,
        │                                                #   costs, credentials, redaction, webhook signatures, GLB),
        │                                                #   test_replicate_provider.py, test_service_runner.py, test_api.py
        │                                                #   (jobs, files, adoption, settings, platform, webhook, isolation,
        │                                                #   token never logged), test_product_image_origin.py,
        └──                                              #   test_adoption_model.py, test_idea_convert_drafts.py (after 011)

frontend/src/
├── types/genai.ts, lib/api/genai.ts, hooks/useGenAI.ts                       # new (zone)
├── components/viewer/GlbView.tsx, glb.ts (+ test)                                      # new: GLB preview, lazy-loaded (three.js stays in the viewer chunk)
├── components/genai/GenerateDialog.tsx, GenAIAssetImage.tsx, MeshPreview.tsx, AIBadge.tsx,
│   JobStatusBadge.tsx, AdoptConfirmDialog.tsx, JobHistory.tsx, PlatformGenaiCard.tsx, genaiText.ts (+ tests)  # new (zone)
├── components/settings/ReplicateSettings.tsx (+ test)                          # new (zone)
├── components/products/ProductImagesEditor.tsx (+ test)                        # zone: AI actions, origin badge/select
├── components/ideas/IdeaEntryItem.tsx, pages/IdeaDetailPage.tsx (+ tests)     # zone: idea AI actions, generation entry render
├── components/models/ModelFilesEditor.tsx (+ test)                            # zone (model AI actions) [confirm]
├── pages/Settings.tsx                                                         # + "AI" tab [request]
├── pages/platform/TenantDetailPage.tsx                                        # + PlatformGenaiCard [request]
├── lib/api/products.ts / types for ProductImage                               # + origin field
└── e2e/tests/genai/genai.spec.ts (under frontend/)                            # new directory [request]
```

**Structure Decision**: the existing web-app layout. The backend follows the router → service →
schemas trio, with a service package for the multi-module domain. The frontend uses `lib/api` +
`hooks` + `components/genai`.

## Design notes

### Backend flow

1. `POST /genai/jobs` → `GenAIService.create_job`:
   - resolves the token (409 `not_connected`);
   - validates the inputs against the capability, and resolves and copies the input assets;
   - checks that the target exists in the tenant;
   - chooses a seed when none is given;
   - estimates the cost;
   - takes the advisory lock, checks concurrency and budget, inserts the job (`queued`) and
     commits;
   - calls `dispatch_submit`; when the broker fails, the job becomes `failed/queue_unavailable`
     and the route answers 503.
2. `tasks/genai.submit` → `runner.submit_job`, then `poll` chained by countdown; see research R6
   and R7.
3. The webhook → `runner.verify_and_complete` → `complete_job` (the same function as polling).
4. `adopt` → `adoption.py`. It uses `ImageStorage.copy_image(display_size=None)` (idea or
   product; full resolution, so an upscale keeps its size, T108) or
   `glb.to_stl` + `ModelFileService.upload_file(commit=False, offer_measurement=False)` after
   `ModelFileVersionService.create_version(label="AI draft", activate_if_first=False)`. It then
   writes the `GenAIAdoption` row.

### Webhook URL and secret

`GENAI_WEBHOOK_BASE_URL` is unset by default, which means polling only. When it is set, the
prediction carries `webhook=<base>/api/v1/genai/webhooks/replicate/{tenant}/{job}` and
`webhook_events_filter=["completed"]`.

### Config (`app/config.py`, additive)

| Setting | Default |
|---|---|
| `replicate_api_token` | `""` (platform token) |
| `genai_platform_token_all_tenants` | `False` |
| `genai_max_concurrent_jobs` | `3` |
| `genai_webhook_base_url` | `""` |
| `genai_provider_base_url` | `"https://api.replicate.com/v1"`; a non-default value is refused unless E2E hooks or the test environment are on |
| `genai_run_inline` | `False`; same guard |

### Frontend

- `GenerateDialog` props: `{capability, target, defaultInputs, inputAssets?, onAdopted?,
  adoptTarget}`.
- Its states: not connected (a link to Settings → AI) → form with an estimate (debounced
  `/estimate`) → job progress (`useGenerationJob` polling) → result grid (Adopt per result) →
  done.
- Viewers never see generate buttons, using `useCurrentRole()` if it exists, else the role from
  the auth context.

## Deployment notes (no deploy here)

- Celery worker: the `app.tasks.genai` module and the beat entry `genai-sweep`
  (`*/5 * * * *`). The worker manifest already runs beat.
- Secrets to add later in the cluster: `REPLICATE_API_TOKEN`, optional
  `GENAI_WEBHOOK_BASE_URL=https://api.batchivo.com`.
- On a VPS: `GENAI_PLATFORM_TOKEN_ALL_TENANTS=true`, if the provider supplies a token. Documented
  in research R9; the 005 install template is not edited.

## Boundary requests (sent to the orchestrator; answers recorded here)

| File (outside zone) | Change | Status |
|---|---|---|
| `services/idea_service.py` | `convert()` calls `adoption.carry_idea_drafts` inside its savepoint and cleans up on rollback | granted (Q4 answer) |
| `pages/platform/TenantDetailPage.tsx` (+ test) | mounts `PlatformGenaiCard` | granted (additions only) |
| `models/product_image.py`, `schemas/product_image.py` | `origin` column and field | granted |
| `services/model_file_service.py`, `model_file_version_service.py` | optional kwargs `commit`, `offer_measurement`, `activate_if_first`; public `delete_stored_file` | granted — `model_file_service.py` only after 011 merges (011 also edits it); sync first |
| `models/idea.py` | `ForeignKey` on `generation_job_id` | granted |
| `pages/Settings.tsx` | "AI" tab | granted |
| `components/models/ModelFilesEditor.tsx` | "Draft 3D from image" and the "AI draft" badge | granted |
| `api/v1/products.py` | PATCH image refuses relabelling an AI image (FR-018) | standing approval for additive out-of-zone lines |
| `frontend/e2e/tests/genai/` | new spec directory (no edit to existing specs; never reaches api.replicate.com) | granted |
| `config.py`, `tasks/celery_app.py`, `models/__init__.py`, `lib/api/products.ts` | additive lines | granted. Conditions: `replicate_api_token` has no default token value and never appears in a manifest, log or the repo; `genai_provider_base_url`/`genai_run_inline` refused when `is_production` (tested like `test_onboarding_e2e_hooks.py`) |

## What later features will find (hand-over)

- **010 MCP server**:
  - every capability is listed by `GET /genai/capabilities`, with its input rules and limits;
  - jobs: `POST/GET /genai/jobs`, `GET /genai/jobs/{id}`, `POST …/cancel`;
  - adoption: `POST /genai/assets/{id}/adopt`; uploads: `POST /genai/uploads`;
  - refusals carry `detail.code` (`not_connected`, `budget_exceeded`, `concurrency_limit`,
    `needs_confirmation`, `already_adopted`…), so tools can branch on it.
  - 010 adds the `genai` token scope in its auth dependency and does not change these routes.
  - In-process callers can use `GenAIService(db, tenant, user)` directly; it raises
    `GenAIError`, never `HTTPException`.
- **009 Preflight**: a design brief's intent can call `GenAIService.create_job(capability=
  "concept_image", target={"type": "idea", …})`. No change is needed in 008.
- **Text capabilities later** (alt text, SEO): add a `Capability` member, a catalog entry with
  `output_kind="text"`, and a `genai_assets.kind` value `text` (a CHECK change in a new
  migration). The job model and cost service are unchanged.
- **Another provider**: implement `GenAIProvider` in `services/genai/<name>.py`, register it in
  `providers.py` and point catalog entries at it.
