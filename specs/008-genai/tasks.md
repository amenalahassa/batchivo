---
description: "Task list for 008 Generative AI layer (Replicate first)"
---

# Tasks: Generative AI layer, Replicate first

**Input**: `specs/008-genai/` (plan.md, spec.md, research.md R1–R14, data-model.md,
contracts/genai-api.md, quickstart.md)

**Tests**: required by the constitution (II) and the spec. Every task that adds code adds its
tests in the named test file. The Replicate HTTP API is **always** mocked (respx); no test may
reach `api.replicate.com`.

**Format**: `- [ ] [ID] [P?] [Story?] Description with file path`

---

## Phase 1: Setup


> **Test locations (as built):** backend tests for this feature live in `backend/tests/genai/`
> (`test_units.py`, `test_replicate_provider.py`, `test_service_runner.py`, `test_api.py`,
> `test_product_image_origin.py`) with fixtures in `backend/tests/utils/genai.py`; they cover what
> the per-task paths below name (`tests/services/genai/…`, `tests/api/test_genai_*`).

- [X] T001 Add the settings to `backend/app/config.py`:
  - `replicate_api_token: Optional[SecretStr] = None` (no token value anywhere in the repo, manifests or logs)
  - `genai_platform_token_all_tenants: bool = False`
  - `genai_max_concurrent_jobs: int = 3`
  - `genai_webhook_base_url: str = ""`
  - `genai_provider_base_url: str = "https://api.replicate.com/v1"`
  - `genai_run_inline: bool = False`

  A validator refuses a non-default `genai_provider_base_url` or `genai_run_inline=True` when
  `is_production`, and otherwise only allows them when `environment in ("development","test")` or
  `e2e_test_hooks_enabled`; tested the same way as `test_onboarding_e2e_hooks.py`. Test in
  `backend/tests/services/genai/test_genai_config.py`.
- [X] T002 [P] Create the package skeleton `backend/app/services/genai/__init__.py` and
  `backend/app/services/genai/errors.py`. `GenAIError(code, message, http_status)` has these
  subclasses:

  | Subclass | HTTP status |
  |---|---|
  | `NotConnected` | 409 |
  | `BudgetExceeded` | 409 |
  | `ConcurrencyLimit` | 409 |
  | `NotCancellable` | 409 |
  | `AlreadyAdopted` | 409 |
  | `NeedsConfirmation` | 409 |
  | `NotSucceeded` | 409 |
  | `WrongKind` | 422 |
  | `InputInvalid` | 422 |
  | `NotFound` | 404 |
  | `QueueUnavailable` | 503 |

- [X] T003 [P] Add the token-redaction logging filter `backend/app/services/genai/logging.py`.
  It redacts `r8_[A-Za-z0-9]+` and `Bearer …` in messages and args, and is attached to the
  `app.services.genai`, `app.tasks.genai` and `httpx` loggers on import. Test in
  `backend/tests/services/genai/test_token_never_logged.py`.
- [X] T004 [P] Create the test helpers in `backend/tests/services/genai/conftest.py`:
  - a `replicate_mock` fixture (respx router on `settings.genai_provider_base_url`, with
    `assert_all_mocked=True`) with routes for account, files, predictions (create, get, cancel),
    output download hosts and the webhook secret;
  - `sign_webhook(secret, body, id, ts)`;
  - factories `make_job`, `make_asset`, `fake_png()` and `fake_glb()`, the last being a valid
    tiny GLB with one triangle.

  Also an `api` conftest re-export for `backend/tests/api/`.

---

## Phase 2: Foundational (blocks every story)

- [X] T005 Create the models in `backend/app/models/generation_job.py` (columns incl. `model_version_ran`).
  - `GenerationJob`, with the columns and CHECKs of data-model.md:
    - capability in the 7 values;
    - `target_type IN ('idea','product','model','none')`;
    - `(target_type='none') = (target_id IS NULL)`;
    - `status IN ('queued','running','succeeded','failed','canceled')`;
    - `estimated_cost`/`cost` as `Numeric(12,4)`;
    - `seed` as BigInteger NOT NULL;
    - `inputs`, `price_snapshot` as JSONB/JSON.
  - `GenAIAsset`, with `source IN ('output','upload')`, `kind IN ('image','mesh')`,
    `(source='output') = (job_id IS NOT NULL)` and `source <> 'output' OR ai_generated`.
  - `GenAIAdoption`, with `owner_type IN ('idea','product','model')`, UNIQUE
    `(asset_id, owner_type, owner_id)`, and exactly one result FK set.
  - Register the three in `backend/app/models/__init__.py`.
- [X] T006 Add `origin` to `backend/app/models/product_image.py`: `String(10)`, NOT NULL,
  default and server_default `'photo'`, CHECK `origin IN ('photo','render','ai')`. Add
  `ForeignKey("generation_jobs.id", ondelete="SET NULL")` to `IdeaEntry.generation_job_id` in
  `backend/app/models/idea.py`.
- [X] T007 Write the migration `backend/alembic/versions/20261124_genai.py`.
  - `revision="genai_v1"`, `down_revision` = the current main head (`ideas_v1`; re-point to
    `print_sends_v1` once 011 has merged).
  - It creates the 3 tables, their indexes, ENABLE + FORCE RLS and the `{table}_tenant_isolation`
    policies (same `TENANT_MATCHES` as `20261123_ideas.py`).
  - It adds `product_images.origin`, and the FK `fk_idea_entries_generation_job_id`.
  - Its downgrade reverses everything.
  - Model and migration tests in `backend/tests/models/test_generation_job_models.py`: CRUD,
    every CHECK, the unique adoption, cascade from job to asset, SET NULL on the idea entry FK,
    and `product_images.origin` defaults to photo.
- [X] T008 [P] Write `backend/app/services/genai/capabilities.py`:
  - a `Capability` str-Enum with the 7 values;
  - an input Pydantic model per capability with the limits of the data-model "Validation rules"
    table (prompt 1–2000; references 0–4; count 1–`max_count` of the resolved config, default 1; style ≤200; factor ∈ {2,4};
    image_to_3d 1–4 assets; seed 0–2³¹−1);
  - an `AssetRef` union (`asset`, `idea_entry`, `product_image`, `model_image`);
  - `validate_inputs(capability, raw) -> model`.

  Test in `backend/tests/services/genai/test_capabilities.py`: every bound, missing required
  fields, unknown fields refused.
- [X] T009 [P] Write `backend/app/services/genai/catalog.py`:
  - a `CapabilityConfig` dataclass: provider, model_ref, model_version, input_mapping,
    default_params, output_kind, max_inputs, time_limit_s, price(unit, amount `Decimal`,
    typical_seconds), shows_real_item, label;
  - `DEFAULTS` from research R3 (community models pinned to a 64-hex version; official models `pinnable=False`, `model_version="official"`; `max_count`, `output_key`, `price_assumed`);
  - `resolve(capability, tenant_settings) -> CapabilityConfig`, which merges the tenant override
    and keeps the catalog price when the override has none.

  Test in `backend/tests/services/genai/test_catalog.py`.
- [X] T010 [P] Write `backend/app/services/genai/base.py`: the `GenAIProvider` Protocol
  (`submit`, `get`, `cancel`, `upload_input`, `delete_input`, `account`, `webhook_secret`,
  `download`); a `ProviderPrediction` dataclass (id, status, output_urls, error, predict_time);
  `ProviderError` with subclasses `ProviderAuthError`, `ProviderRateLimited`,
  `ProviderTransient`, `ProviderRejected`; and `providers.get(name)` in
  `backend/app/services/genai/providers.py`.
- [X] T011 Write `backend/app/services/genai/replicate.py`, `ReplicateProvider(token,
  base_url)`, with one `httpx.AsyncClient` (timeouts 10 s connect / 60 s read).
  - `POST /predictions` takes `{version, input, webhook?, webhook_events_filter:["completed"]}`.
  - `version` is `"{model_ref}:{model_version}"` for a pinned model and `"{model_ref}"` for an official one. Inputs ≤256 KB are sent as a data URI, larger ones through `POST /files`.
  - Status mapping: `starting`/`processing` → running; `aborted` → failed. The prediction's `version` is recorded once as `model_version_ran`.
  - The output is normalised to a URL list.
  - Errors map as: 401/403 → auth, 429 → rate limited, 5xx or network → transient, 422/404 →
    rejected.
  - The token is never put in an exception message.
  - `upload_input` goes through `POST /files` (multipart) → `urls.get`.
  - `webhook_secret` goes through `GET /webhooks/default/secret`.
  - `download(url, max_bytes)` streams with the auth header and stops past `max_bytes`.

  Test with respx in `backend/tests/services/genai/test_replicate_provider.py`.
- [X] T012 [P] Write `backend/app/services/genai/costs.py`, `GenAICostService`, the **only**
  cost computation.
  - `estimate(config, inputs) -> Decimal`: per_output × count | per_run | per_second ×
    typical_seconds.
  - `final(job, prediction) -> (Decimal, "computed"|"estimated")`.
  - `month_to_date(db, tenant, now) -> (Decimal, int)`: terminal final costs plus active
    estimates for the current UTC month; a failed job that never started costs 0.
  - `quantize` to 4 dp only at storage.

  Test in `backend/tests/services/genai/test_costs.py`: Decimal-exact cases, the month boundary
  in UTC, other tenants excluded.
- [X] T013 [P] Write `backend/app/services/genai/credentials.py`.
  - `resolve(tenant, settings) -> ResolvedToken(token, source)`, with source `tenant`,
    `platform` or `none`: tenant token, else the platform token if
    (`replicate.platform_token_allowed` or `genai_platform_token_all_tenants`), else none.
  - `webhook_secret(db, tenant, provider)` caches the secret encrypted in
    `tenant.settings["replicate"]`, keyed by a token fingerprint; the platform token's secret is
    cached in memory.

  Test in `backend/tests/services/genai/test_credentials.py`.
- [X] T014 [P] Write `backend/app/services/genai/storage.py`, `GenAIFileStore`: `save(bytes,
  content_type, job_id, ext)`, `get(url)` and `delete(url)` for meshes under
  `generations/{job_id}/`. It uses the same `storage_type`, `storage_path` and S3 settings as
  `ImageStorage`, and refuses path tricks. Test in
  `backend/tests/services/genai/test_genai_storage.py`, local and with moto S3.
- [X] T015 Write `backend/app/services/genai/service.py`, `GenAIService(db, tenant, user)`.
  - `list_capabilities()`.
  - `estimate(req)`.
  - `create_job(req)`:
    1. resolve the token (`NotConnected`);
    2. validate;
    3. resolve each `AssetRef` within the tenant (an idea entry, product image or model image is
       copied once into a `GenAIAsset` upload through `ImageStorage.copy_image(…,
       "generations", "uploads-"+tenant)`); a foreign or unknown id gives `NotFound`;
    4. check that the target exists in the tenant;
    5. take the seed, or choose one with `secrets.randbelow(2**31)`;
    6. estimate the cost;
    7. under `pg_advisory_xact_lock` (Postgres only): refuse at the concurrency limit, and refuse
       when month-to-date + estimate > budget;
    8. insert `queued` with `price_snapshot`, and commit;
    9. `dispatch_submit`; on an exception, set failed/`queue_unavailable` and raise
       `QueueUnavailable`.
  - `get_job`, `list_jobs(filters, skip, limit)` and `upload_input(file)`.
  - It raises `GenAIError` only, never `HTTPException`.

  Test in `backend/tests/services/genai/test_service_create.py`:
  - each validation path;
  - budget refusal and concurrency refusal, with the respx call count 0;
  - a foreign target or asset → NotFound;
  - a seed is recorded;
  - immutability: no method changes the inputs, version or seed after creation.
- [X] T016 Write `backend/app/services/genai/runner.py`.
  - `submit_job`:
    - uploads the inputs and submits, with the webhook URL when `genai_webhook_base_url` is set;
    - stores `external_id` and `submitted_at`/`started_at`, sets running and
      `deadline_at = now + time_limit_s`;
    - retries transient errors up to 3 times, then fails with the code.
  - `poll_job` returns `"done"` or the next delay `min(2*1.5**n, 30)`:
    - when the job is terminal → done;
    - past the deadline → provider cancel and fail `timeout`;
    - when the prediction is terminal → `complete_job`.
  - `complete_job(db, tenant, job_id, prediction)`:
    - locks the row `with_for_update`, and returns unless the job is running;
    - on success, downloads every output (image ≤10 MB through
      `ImageStorage.save_image(owner_type="generations", owner_id=job_id)`, mesh ≤200 MB through
      `GenAIFileStore`) and creates the assets with `ai_generated=True`;
    - when a download fails, deletes the stored files and fails with `download_failed`;
    - computes the final cost through `GenAICostService`;
    - handles failed and canceled predictions;
    - deletes the provider input files (best effort).
  - `sweep_stale(db, now)`.

  Test in `backend/tests/services/genai/test_runner.py`:
  - the polling path to succeeded, with stored outputs readable afterwards;
  - provider failure;
  - timeout → cancel called and failed `timeout`;
  - download failure → no orphan file;
  - a duplicate completion is a no-op;
  - transient retry then failure;
  - auth error.
- [X] T017 Write the Celery tasks in `backend/app/tasks/genai.py`: `genai.submit`, `genai.poll`
  (re-schedules itself with `apply_async(countdown=…)`) and `genai.sweep`, all through
  `run_in_task_loop`, plus `dispatch_submit(job_id, tenant_id)` and `dispatch_poll(job_id,
  tenant_id, delay)`. When `genai_run_inline` is on, dispatch schedules the runner steps with
  `asyncio.create_task` in a fresh session instead. Register `"app.tasks.genai"` in the
  `include` list and add the beat entry `"genai-sweep": crontab(minute="*/5")` in
  `backend/app/tasks/celery_app.py`. Test in `backend/tests/tasks/test_genai_tasks.py`, with the
  task bodies called directly and `apply_async` patched.
- [X] T018 Write the webhook verification `verify_webhook(secret, headers, body, now)` in
  `backend/app/services/genai/webhooks.py`: Standard Webhooks HMAC-SHA256 over
  `"{id}.{ts}.{body}"`, the `whsec_` base64 secret, constant-time comparison against each
  `v1,…`, and a 300 s tolerance. Also `handle_replicate_webhook(db, tenant_id, job_id, headers,
  body)`, which sets the RLS context, loads the job, checks body.id == `external_id`, verifies,
  and then calls `complete_job`. Test in `backend/tests/services/genai/test_webhook_verify.py`.
- [X] T019 Write the schemas in `backend/app/schemas/genai.py`: `GenerationJobCreate`,
  `GenerationJobResponse` (money as strings through a Decimal serializer), `GenerationJobList`,
  `GenAIAssetResponse` (with `file_path`, `thumbnail_path` and `adoptions`), `AdoptRequest`,
  `AdoptResponse`, `CapabilityInfo`, `CapabilitiesResponse`, `EstimateResponse`,
  `PlatformGenaiSettings`.
- [X] T020 Write the core router `backend/app/api/v1/genai.py`:
  - `GET /capabilities`;
  - `POST /estimate`;
  - `POST /jobs` (RequireMember);
  - `GET /jobs/{id}`;
  - `GET /assets/{id}/file?variant=`;
  - `POST /webhooks/replicate/{tenant_id}/{job_id}`: no auth, raw body, 204, 401 or 404.

  `GenAIError` maps to `HTTPException(status, {"code","message"})`. Mount it in
  `backend/app/main.py` with prefix `{api_v1_prefix}/genai` (added lines only). Tests in
  `backend/tests/api/test_genai_jobs_api.py`:
  - create 201, 401, 403 for a viewer, 404 for a foreign target, 422, 409 not_connected, 409
    budget, 409 concurrency, 503 with the broker down;
  - get 200 and 404;
  - capabilities 200;
  - estimate 200.

  Tests in `backend/tests/api/test_genai_webhook_api.py`:
  - valid signature completes the job;
  - invalid, missing or stale signature → 401, unchanged;
  - wrong tenant or job → 404;
  - duplicate → 204, no change.
- [X] T021 Write the fake provider `backend/app/api/v1/genai_e2e.py`, mounted in
  `backend/app/main.py` only when `settings.e2e_test_hooks_enabled`, at
  `{api_v1_prefix}/genai/e2e-fake`. It imitates `/account`, `/files`, `/predictions` (succeeds
  after the 2nd GET, with PNG outputs or a tiny GLB for image_to_3d), `/predictions/{id}/cancel`,
  `/webhooks/default/secret`, and serves its output files. Test in
  `backend/tests/api/test_genai_e2e_fake.py`: it is absent when hooks are off.

**Checkpoint**: a job can be created, run, completed and read through the API, with the provider
mocked.

---

## Phase 3: User Story 1, connect Replicate and control spending (P1) 🎯 MVP

**Goal**: an owner or admin saves a token (encrypted, masked), tests it, sets a USD budget,
sees month-to-date usage and overrides models. Platform admins authorise the platform token per
tenant.

**Independent test**: PUT a token, test the connection (mocked), set a budget, and GET back a
masked token, `month_to_date` "0.0000" and `token_source` "tenant".

- [X] T022 [P] [US1] Add `ReplicateSettingsResponse`, `ReplicateSettingsUpdate` and
  `ReplicateConnectionTest`, `ReplicateUsageResponse`, `ModelOverride` to
  `backend/app/schemas/tenant_settings.py`. `ReplicateSettingsUpdate` takes `api_token`
  (str|None; "" removes), `monthly_budget` (Decimal ≥0, 2 dp, or null) and `model_overrides`
  (per known capability; version non-empty and ≠ "latest"; `price_unit` in
  per_output/per_run/per_second; `price_usd` ≥0).
- [X] T023 [US1] Add `get_replicate_settings`, `update_replicate_settings`,
  `test_replicate_connection` and `replicate_usage` to
  `backend/app/services/tenant_settings.py`.
  - The token is encrypted through `encrypt_value`, with only `token_last4` kept in the clear.
  - Updates never touch `platform_token_allowed`.
  - Usage comes from `GenAICostService`.
  - The test goes through `ReplicateProvider.account`.
  - Messages never contain the token.

  Test in `backend/tests/services/genai/test_replicate_settings_service.py`.
- [X] T024 [US1] Write the router `backend/app/api/v1/genai_settings.py` (`GET/PUT
  /settings/replicate`, `POST /settings/replicate/test`, `GET /settings/replicate/usage`), all
  RequireAdmin + TenantDB, and mount it in `backend/app/main.py` at
  `{api_v1_prefix}/settings/replicate`. Test in `backend/tests/api/test_genai_settings_api.py`:
  - 200, 401, 403 for a member, 422 (negative budget, "latest" version, unknown capability);
  - the token is never in any response body;
  - a test with an invalid token reports failure without the token in the message.
- [X] T025 [US1] Write the router `backend/app/api/v1/genai_platform.py` (`GET/PUT
  /platform/tenants/{tenant_id}/genai`, PlatformAdmin). It writes
  `tenant.settings["replicate"]["platform_token_allowed"]` and an audit log through
  `AuditService`. Mount it in `backend/app/main.py`. Test in
  `backend/tests/api/test_genai_platform_api.py`: 200, 403 for a non platform admin, 404,
  422; the resolution then uses the platform token.
- [X] T026 [P] [US1] Write the frontend types and API: `frontend/src/types/genai.ts` (every
  contract shape; money as `string`) and `frontend/src/lib/api/genai.ts` (`genaiApi` with
  capabilities, estimate, createJob, listJobs, getJob, cancelJob, upload, adopt, assetFilePath,
  getSettings, updateSettings, testConnection, usage, getPlatform, setPlatform).
- [X] T027 [US1] Write the hooks in `frontend/src/hooks/useGenAI.ts`: `useCapabilities`,
  `useReplicateSettings`, `useUpdateReplicateSettings`, `useTestReplicate`, `useReplicateUsage`,
  `usePlatformGenai`, `useSetPlatformGenai` (the job hooks come in T034). Tests in
  `frontend/src/hooks/useGenAI.test.ts`.
- [X] T028 [US1] Write `frontend/src/components/settings/ReplicateSettings.tsx`:
  - a token field (shows the masked value, with replace and remove), and Test connection with
    the result;
  - the budget in USD as a decimal string input, and month-to-date with the job count;
  - which token is in use: own, platform or none;
  - a model overrides table per capability (model ref, version, price unit, price), clearable.

  Add the "AI" tab in `frontend/src/pages/Settings.tsx` (added lines only). Tests in
  `frontend/src/components/settings/ReplicateSettings.test.tsx`.
- [X] T029 [US1] Write `frontend/src/components/genai/PlatformGenaiCard.tsx`, a switch "Allow
  the platform Replicate token" with the platform token availability, mounted in
  `frontend/src/pages/platform/TenantDetailPage.tsx` (added lines only). Tests in
  `frontend/src/components/genai/PlatformGenaiCard.test.tsx`.

**Checkpoint**: US1 is usable and testable alone.

---

## Phase 4: User Story 2, concept image from an idea (P1)

**Goal**: "Generate concept" on an idea, with progress, results, Adopt → a generation entry.
Also edit or variations, and "Draft 3D shape" on idea images; mesh entries show in the 3D
viewer; conversion carries 3D drafts.

**Independent test**: with the provider mocked, start a concept job on an idea, complete it,
adopt one output, and see a generation entry linked to the job.

- [X] T030 [US2] Additive kwargs and tests (edit `model_file_service.py` only after 011 has merged into main and this branch is synced; add on top of 011's version).
  - `ModelFileService.upload_file(…, commit: bool = True, offer_measurement: bool = True)` in
    `backend/app/services/model_file_service.py`. When `offer_measurement` is False, the file is
    measured and recorded, but `apply_measurement` is skipped and a queued measurement is
    recorded `skipped`.
  - A public `delete_stored_file(file_url)`.
  - `ModelFileVersionService.create_version(…, activate_if_first: bool = True)` in
    `backend/app/services/model_file_version_service.py`.
  - Defaults keep today's behaviour.
  - Tests in `backend/tests/services/test_model_file_service_genai_kwargs.py`: defaults are
    unchanged; `commit=False` leaves the transaction open; `offer_measurement=False` leaves the
    model's dimensions unchanged; `activate_if_first=False` on a model with no version → inactive.
- [X] T031 [US2] Write `backend/app/services/genai/adoption.py`, `adopt(asset_id, AdoptRequest)`.
  - Shared checks: the asset belongs to the tenant, its job has succeeded (`NotSucceeded`), and
    the target exists in the tenant (`NotFound`). The unique index → `AlreadyAdopted`.
  - Idea target:
    - an image: `ImageStorage.copy_image(…, "ideas", idea_id)`, then an `IdeaEntry(kind=
      "generation", iteration=idea.current_iteration, image_url, thumbnail_url, content_type,
      generation_job_id=job.id, body="<capability label>: <prompt or instruction>",
      author_user_id)`;
    - a mesh: an entry with no image, the body "AI 3D draft (image to 3D)" and
      `generation_job_id`;
    - both bump `idea.updated_at`, as `IdeaService._touch` does;
    - writes the `GenAIAdoption(idea_entry_id=…)`.
  - `AdoptResponse`.

  Test in `backend/tests/services/genai/test_adoption.py` (idea part): image and mesh entries,
  `already_adopted`, a non-succeeded job, a foreign idea.
- [X] T032 [US2] Add `carry_idea_drafts(db, tenant, user, idea, model, cleanup: list)` to
  `backend/app/services/genai/adoption.py`.
  - It handles every mesh asset adopted into a non-archived generation entry of the idea:
    `glb.to_stl` → `ModelFileVersionService.create_version(model, label="AI draft",
    note=<job ref>, activate_if_first=False)` → `ModelFileService.upload_file(…, version_id=…,
    file_type=SOURCE_STL, commit=False, offer_measurement=False)` → a `GenAIAdoption(model)`.
  - Each stored file URL is appended to `cleanup`, and a failure for one draft is returned as a
    warning string.
  - Call it from `IdeaService.convert` in `backend/app/services/idea_service.py`, only when a new
    model was created, inside the savepoint. On rollback, delete the `cleanup` files through
    `ModelFileService.delete_stored_file`.

  Test in `backend/tests/services/genai/test_idea_convert_drafts.py`:
  - each draft becomes an inactive "AI draft" version, and no active version is created;
  - the model's dimensions stay unchanged;
  - a conversion with none is unchanged;
  - a failure rolls back and leaves no files.
- [X] T033 [P] [US2] Write `backend/app/services/genai/glb.py`, `to_stl(glb_bytes) -> bytes`
  (binary STL).
  - It parses the header (magic `glTF`, version 2), the JSON and BIN chunks, the default scene's
    node tree (matrix or TRS) and the mesh primitives in mode 4 (triangles), with float32 VEC3
    POSITION and indices u8, u16 or u32 (or none).
  - It honours `byteStride`.
  - It raises `InputInvalid` on a malformed file, Draco compression, or more than 5 M triangles.

  Test in `backend/tests/services/genai/test_glb.py`: a tiny GLB → STL measurable by
  `mesh_bounds.measure`, node transforms, an indexed mesh, a malformed file.
- [X] T034 [US2] Add `POST /assets/{asset_id}/adopt` (RequireMember), `GET /jobs` (filters,
  pagination) and `POST /uploads` (RequireMember, multipart image) to
  `backend/app/api/v1/genai.py`. Tests in `backend/tests/api/test_genai_assets_api.py`: adopt
  into an idea 201, 401, 403 for a viewer, 404, 409 already adopted, 409 not succeeded, 422
  wrong kind; upload 201 and 422; list filters by target.
- [X] T035 [P] [US2] Write `frontend/src/components/genai/useGenAIRoles.ts`, which returns `{canGenerate: canEditOperationalFigures(user), canManageSettings: canEditMonetaryPolicy(user)}` like `components/ideas/useIdeaRoles.ts`. Every generate, adopt and cancel control (T039, T042, T044, T046) is shown only when `canGenerate`. Test in `useGenAIRoles.test.ts`.
- [X] T036 [US2] Write the job hooks in `frontend/src/hooks/useGenAI.ts`: `useGenerationJob(id)`
  (with `refetchInterval` 2000 while queued or running, else false), `useGenerationJobs(filters)`,
  `useCreateJob`, `useCancelJob`, `useAdoptAsset`, `useEstimate(req)` (debounced) and
  `useUploadInput`. Adopt invalidates `['ideas', id]`, `['idea-entries', id]`,
  `['product-images', id]` and `['model-files', id]` as relevant. Tests in
  `frontend/src/hooks/useGenAI.test.ts`.
- [X] T037 [P] [US2] Write the small components in `frontend/src/components/genai/`:
  - `GenAIAssetImage.tsx`: an auth blob image, following `components/ideas/AuthImage.tsx`;
  - `MeshPreview.tsx`: loads the GLB through the `three` GLTFLoader into the existing viewer
    canvas (`components/viewer/ViewerCanvas.tsx`), with a download button;
  - `AIBadge.tsx`;
  - `JobStatusBadge.tsx`;
  - `genaiText.ts`: capability labels and refusal-code messages.

  Tests in each `*.test.tsx`.
- [X] T038 [US2] Write `frontend/src/components/genai/GenerateDialog.tsx`, with props
  `{capability, target, defaultInputs, inputAssets, adoptTarget, onAdopted, trigger}`.
  - Not connected: a message and a link to Settings → AI.
  - The form fields depend on the capability (prompt, instruction, scene, style, count, factor,
    reference picker over `inputAssets` plus an upload).
  - An estimated cost from `useEstimate`, in "USD".
  - Start → progress (`JobStatusBadge`) → result grid (`GenAIAssetImage` or `MeshPreview`) with
    Adopt per result, plus Cancel.
  - Refusal codes are shown readably: budget names the budget and month-to-date.

  Tests in `frontend/src/components/genai/GenerateDialog.test.tsx`.
- [X] T039 [US2] Ideas integration.
  - `frontend/src/pages/IdeaDetailPage.tsx`: pass a "Generate concept" `GenerateDialog`
    (prompt prefilled with the title and summary; references = the idea's image entries) through
    `IdeaComposer`'s `extraActions`. Hidden for viewers.
  - `frontend/src/components/ideas/IdeaEntryItem.tsx`:
    - image and sketch entries get a menu: Edit with AI (image_edit), Variations (image_edit
      with an instruction preset) and Draft 3D shape (image_to_3d), each opening
      `GenerateDialog` with `adoptTarget` = the idea;
    - generation entries render the image with `AIBadge`, or `MeshPreview` for a mesh (looked up
      through `generation_job_id` → job outputs → the adoption with this entry id), plus a link
      to "how it was made" (job details).

  Tests in `frontend/src/components/ideas/IdeaEntryItem.test.tsx` and
  `frontend/src/pages/IdeaDetailPage.test.tsx`.

**Checkpoint**: US1 and US2 make a working MVP.

---

## Phase 5: User Story 3, product photos and sales images (P2)

**Goal**: enhance, remove background, upscale and lifestyle scene from the product image editor;
adopt as a new product image with origin AI and a badge; origin shown and editable
(photo/render); a warning on adopting a concept image or 3D draft.

**Independent test**: remove the background of a product photo (mocked), adopt it, and see a new
image with origin ai and the badge, with the original unchanged.

- [X] T040 [US3] Add `origin` to `backend/app/schemas/product_image.py`:
  `ProductImageResponse.origin: Literal["photo","render","ai"]`, and
  `ProductImageUpdate.origin: Optional[Literal["photo","render"]]`. "ai" in PATCH → 422. Test in
  `backend/tests/api/test_product_image_origin.py`: existing images read as photo; PATCH
  photo→render 200; PATCH ai 422.
- [X] T041 [US3] Add the product target to `adopt` in
  `backend/app/services/genai/adoption.py`.
  - An image only (a mesh → `WrongKind`).
  - When the source job's capability has `shows_real_item=False` and `confirm_not_real_item` is
    false → `NeedsConfirmation`.
  - `ImageStorage.copy_image(…, "products", product_id)` → a new `ProductImage(origin="ai",
    is_primary=False, display_order=max+1, alt_text=req.alt_text or the product name[:255])`.
  - The adoption records `warning_confirmed`.
  - The source image is never changed.

  Tests in `backend/tests/services/genai/test_adoption.py` (product part) and in
  `test_genai_assets_api.py`: 409 needs_confirmation, then 201 with the confirmation.
- [X] T042 [US3] Write `frontend/src/components/products/ProductImagesEditor.tsx`.
  - Each image shows `AIBadge` when the origin is ai, else an origin select (Photo/Render) that
    PATCHes.
  - A per-image "AI" menu (members and up) opens `GenerateDialog`: enhance
    (product_photo_enhance), remove background, upscale (factor), lifestyle scene (scene prompt,
    count), with the input = that product image and `adoptTarget` = the product.
  - Adopt shows `AdoptConfirmDialog` when the server answers `needs_confirmation`.
  - `frontend/src/components/genai/AdoptConfirmDialog.tsx` reads "Listings must show the real
    item…".
  - Add the `origin` field to the ProductImage type in `frontend/src/lib/api/products.ts` (or its
    types file).

  Tests in `frontend/src/components/products/ProductImagesEditor.test.tsx` and
  `frontend/src/components/genai/AdoptConfirmDialog.test.tsx`.

---

## Phase 6: User Story 4, draft a 3D model file from an image (P3)

**Goal**: "Draft 3D from image" on a model; adopting the mesh adds an inactive "AI draft"
version; the dimensions stay unchanged.

**Independent test**: run a mocked image_to_3d job on a model, adopt it, and see a new inactive
version "AI draft" with the active version unchanged.

- [X] T043 [US4] Add the model target to `adopt` in
  `backend/app/services/genai/adoption.py`: a mesh only (an image → `WrongKind`); `glb.to_stl` →
  `create_version(label="AI draft", note=f"Generated by job {job.id} ({model_ref}:{version})",
  activate_if_first=False)` → `upload_file(original_filename="ai-draft-<job8>.stl",
  file_type=SOURCE_STL, version_id=…, offer_measurement=False)`; the adoption records
  `model_file_id`. Tests in `test_adoption.py` (model part) and API tests in
  `test_genai_assets_api.py`.
- [X] T044 [US4] Update `frontend/src/components/models/ModelFilesEditor.tsx`:
  - a "Draft 3D from image" button (members and up) opens `GenerateDialog(image_to_3d,
    target=model)`, with inputs from the model image, the images of products using the model, or
    an upload;
  - adopt targets the model and invalidates the model files and versions;
  - versions labelled "AI draft" show `AIBadge`.

  Tests in `frontend/src/components/models/ModelFilesEditor.test.tsx`.

---

## Phase 7: User Story 5, follow, cancel and audit jobs (P3)

**Goal**: list jobs by target, read how a job was made, cancel queued or running jobs, see
failures.

**Independent test**: jobs in several states (mocked) are listed by target; a running one is
canceled; a failed one shows its reason.

- [X] T045 [US5] Add `cancel_job` to `GenAIService` in `backend/app/services/genai/service.py`:
  - a queued or running job → provider cancel when `external_id` is set (a failure is logged,
    the cancel still proceeds) → `canceled`, `error_code="canceled_by_user"`, `completed_at`,
    cost = final or 0 when it never started;
  - a terminal job → `NotCancellable`.

  Add the route `POST /jobs/{id}/cancel` (RequireMember) to `backend/app/api/v1/genai.py`. Tests
  in `backend/tests/services/genai/test_service_cancel.py` and `test_genai_jobs_api.py`: 200,
  401, 403, 404, 409; a webhook after the cancel is ignored.
- [X] T046 [US5] Write `frontend/src/components/genai/JobHistory.tsx`, a list of jobs for a target
  (status, capability, cost with provenance, who, when), with a details drawer: capability,
  model and version, prompt, params, seed, inputs, timings, error. Cancel is available for
  members. Mount it on the idea page (tab "AI"), in the product image editor (a collapsible
  section) and in the model files editor (a collapsible section). Tests in
  `frontend/src/components/genai/JobHistory.test.tsx`.

---

## Phase 8: Polish and cross-cutting

- [X] T047 Run a tenant-isolation sweep: one test module
  `backend/tests/api/test_genai_tenant_isolation.py` where tenant B gets 404 on every job, asset,
  adopt, cancel and file route of tenant A, and the webhook with tenant B's path for A's job is
  404.
- [X] T048 [P] Prove the token never leaks in `backend/tests/services/genai/test_token_never_logged.py`
  (extended): run create, submit, poll, failure, connection test and settings GET with `caplog`
  at DEBUG, and assert the token string is absent from every record and every response body.
- [X] T049 [P] Write the e2e spec `frontend/e2e/tests/genai/genai.spec.ts`
  (`registerAndLogin`, fake provider via test hooks):
  - Settings → AI: save the token, test it, set a budget;
  - an idea → Generate concept → adopt → a generation entry;
  - a product → remove background → adopt → the AI badge;
  - the budget at 0 → refusal message.
- [X] T050 [P] Update the docs: the `backend/.env.example` (or equivalent) lines for the new
  settings, and the `specs/backlog.md` 008 status line.
- [X] T051 Run the gates:
  - `cd backend && poetry run alembic heads` (one head) `&& poetry run pytest && poetry run ruff
    check && poetry run ruff format --check`;
  - `cd frontend && npm run test:run && npm run lint && npm run typecheck`;
  - the targeted e2e: `npm run test:e2e -- e2e/tests/genai e2e/tests/ideas e2e/tests/models
    e2e/tests/products --project=chromium --reporter=list`, on a private stack with
    `E2E_TEST_HOOKS_ENABLED=true` and `GENAI_RUN_INLINE=true`.

---

## Dependencies

- Setup (T001–T004) → Foundational (T005–T021) → user stories.
- US1 (T022–T029) needs T013 and T026 only for its frontend. US2 needs T005–T021 and
  T026/T027. US3 and US4 need US2's T031, T034, T036 and T038 (adoption base, dialog). US5 needs
  T020 and T036.
- T006 and T007 must precede every DB test. T030 precedes T032 and T043. T033 precedes T032 and
  T043.
- Inside a story: backend service → route → frontend hooks → components → page integration.

## Parallel opportunities

- Phase 1: T002, T003 and T004 run together.
- Phase 2: T008, T009, T010, T012, T013 and T014 run together after T005–T007; T011 after T010.
- US1: T022 and T026 run in parallel; T028 and T029 run in parallel after T027.
- US2: T033 and T037 run in parallel with T031.
- Polish: T047, T048, T049 and T050 run in parallel.

## Implementation strategy

1. MVP = Phases 1–3 plus Phase 4: a configured provider, and concept images on ideas,
   end to end.
2. Then US3 (sales images, the most frequent use), US4 (3D drafts on models) and US5 (history
   and cancel).
3. Each phase ends with its tests green before the next one starts. The gates (T051) run before
   converge.

## Phase 9: Convergence

- [X] T052 [US2] Make reference images selectable for a concept (finding F1, contradicts US2, FR-001, R3, R13): `/capabilities` reports `max_inputs` for concept_image with references (4) in `backend/app/services/genai/catalog.py`, and `frontend/src/components/genai/GenerateDialog.tsx` lets the operator pick up to that many reference images; test in `GenerateDialog.test.tsx` and `tests/genai/test_units.py`
- [X] T053 [US3] Offer "Add to product…" for an idea or model result (finding F2, partial US3 AS4, FR-030): `GenerateDialog.tsx` and `JobHistory.tsx` let a concept image or 3D draft be adopted into a chosen product, going through `AdoptConfirmDialog` on `needs_confirmation`; tests in `JobHistory.test.tsx`
- [X] T054 Redact every genai log line (finding F3, partial FR-021, SC-006, R9): the token filter in `backend/app/services/genai/logging.py` covers records emitted by child loggers (`app.services.genai.*`, `app.api.v1.genai*`, `httpx`, `httpcore.*`); test emitting through a child logger in `tests/genai/test_units.py`
- [X] T055 Enforce that no test reaches Replicate (finding F4, R14): an autouse guard in `backend/tests/genai/conftest.py` points the provider at a fake base URL unless `replicate_mock` is used, with a test proving an unmocked call fails
- [X] T056 Expose each capability's input rules on `GET /capabilities` (finding F5, FR-005, contract `inputs{}`): `backend/app/schemas/genai.py`, `catalog.py`; the frontend reads them in `GenerateDialog.tsx`; tests in `tests/genai/test_api.py` and `GenerateDialog.test.tsx`
- [X] T057 Test the task wrappers (finding F6, R6): `backend/tests/genai/test_tasks.py` covers `run_submit`, `run_poll`, `run_sweep` and the inline dispatch path in `backend/app/tasks/genai.py`
- [X] T058 Delete provider-side input files after a job ends (finding F7, R7 step 5, R10): `backend/app/services/genai/runner.py` calls `delete_input` best effort; test in `tests/genai/test_service_runner.py`
- [X] T059 Add the adoption result CHECK (finding F8, data-model `genai_adoptions`): at most one result FK set, in `backend/app/models/generation_job.py` and `backend/alembic/versions/20261124_genai.py`; test in `tests/integration/test_genai_migration.py`
- [X] T060 [US1] Open the AI tab from `/settings?tab=ai` (finding F9, US1 AS5): `frontend/src/pages/Settings.tsx` reads the tab from the URL; test
- [X] T061 Refuse unsupported upload types (finding F10, edge case, contract uploads): `backend/app/services/genai/storage.py` accepts only jpeg, png and webp; test in `tests/genai/test_api.py`
- [X] T062 Add the missing behaviour tests (finding F11): job immutability after a final state, status filter on `GET /jobs`, viewer 403 on cancel and upload, webhook for another tenant, adopt into a deleted target, drafts carried on product-path conversion, archived drafts excluded, no orphan files after a download failure, in `backend/tests/genai/`
- [X] T063 Say the time limit in the timeout reason (finding F12, FR-013): `backend/app/services/genai/runner.py`; test
- [X] T064 Fix the migration docstring on orphan `generation_job_id` values (finding F13): `backend/alembic/versions/20261124_genai.py`
- [X] T065 Fix the test paths in `specs/008-genai/quickstart.md` §1 (finding F14)
- [X] T066 [US5] Show input image thumbnails in "How it was made" (finding F15, US5 AS4): `frontend/src/components/genai/JobHistory.tsx`; test
- [X] T067 Make a concept_image override apply to one model only, the one without references, and document it (finding F16, FR-003): `backend/app/services/genai/catalog.py`, `research.md`; test in `tests/genai/test_units.py`

## Phase 10: Convergence

- [X] T068 Redact Replicate secrets from Sentry events (finding F1, FR-021, SC-006, R9): `before_send` in `backend/app/observability/sentry.py` runs the event through the genai redaction and blanks `api_token`, `api_token_encrypted` and `webhook_secret_encrypted`; test that a crafted event loses the token
- [X] T069 [US5] Cancel at the provider when a submission won the race (finding F2, FR-012, US5 AS2): `backend/app/services/genai/runner.py` `cancel_job` re-checks `external_id` after the row lock; test in `tests/genai/test_service_runner.py`
- [X] T070 [US1] Document `clear_budget` on `PUT /settings/replicate` (finding F3): `specs/008-genai/contracts/genai-api.md`
- [X] T071 Make the genai e2e refuse to run unless the provider is the fake (finding F4, R14): the fake's `account` answer says it is the fake and the backend's provider URL points at it; `frontend/e2e/tests/genai/genai.spec.ts` skips otherwise; document `GENAI_PROVIDER_BASE_URL` and `GENAI_RUN_INLINE` in `frontend/e2e/README.md`
- [X] T072 [US1] Show the budget currency once (finding F5, FR-025): `frontend/src/components/settings/ReplicateSettings.tsx`; test. No defect on inspection (the panel's own `usd()` adds no suffix); a test now pins "Current budget: $25.00 USD"
- [X] T073 [US2] Offer the AI actions on generation entries that carry an image (finding F6, US2 AS5/AS6): `frontend/src/components/ideas/IdeaEntryItem.tsx`; test
- [X] T074 Align the index description in `specs/008-genai/data-model.md` with the migration (finding F8)
- [X] T075 Scope `_check_not_adopted` by tenant (finding F9): `backend/app/services/genai/adoption.py`

## Phase 11: Convergence

- [X] T076 [US1] Give a per-second price override a run time (finding F1, FR-024, SC-002, R4): `ReplicateModelOverride.typical_seconds` (optional, 1–3600) in `backend/app/schemas/tenant_settings.py`; `catalog.resolve` uses it, else the default's typical duration, else the capability's time limit marked assumed, so an estimate is never 0; the override form in `frontend/src/components/settings/ReplicateSettings.tsx` asks for it when the unit is per second; tests in `tests/genai/test_units.py`, `tests/genai/test_api.py` and `ReplicateSettings.test.tsx`
- [X] T077 Never echo a submitted token in a 422 (finding F2, FR-021, SC-006): the validation errors of `PUT /settings/replicate` leave out the submitted values; test in `tests/genai/test_api.py`
- [X] T078 Let `costs.final` price a job the queue never took (finding F3, constitution "one implementation"): `backend/app/services/genai/service.py`

## Phase 12: Convergence

- [X] T079 Fetch outputs only from the provider's own hosts (finding G1, FR-021, SC-006, FR-023, R7): `ReplicateProvider.download` in `backend/app/services/genai/replicate.py` accepts the configured API and https `replicate.delivery` (and its subdomains) only, so a lookalike host never receives the token and a model cannot make the backend fetch an arbitrary or internal address; tests in `tests/genai/test_replicate_provider.py`
- [X] T080 Check the role before the body on `PUT /settings/replicate` (finding G2, contract 401/403): `backend/app/api/v1/genai_settings.py`; tests in `tests/genai/test_api.py`

## Phase 13: MCP tools (spec 010 merged first, decision (c))

- [X] T081 Add the genai MCP tool group: `backend/app/mcp_server/tools/genai.py` (`list_generation_capabilities`, `estimate_generation`, `list_generation_jobs`, `get_generation_job`, `get_generation_output` with scope `read`; `start_generation`, `cancel_generation`, `upload_generation_input`, `adopt_generation_output` with scope `genai`), registered in `tools/GROUPS`; the matching routes in `TOKEN_ROUTE_SCOPES` (`backend/app/auth/api_token_policy.py`); the genai routers classified in `tests/unit/pricing/test_pricing_write_guards_derived.py`; tests in `backend/tests/mcp_server/test_tools_genai.py`

## Phase 14: Convergence

- [X] T082 Refuse a 3D draft in `get_generation_output` instead of returning it as an image (finding M1, T081, FR-015): `backend/app/mcp_server/tools/genai.py`; test in `backend/tests/mcp_server/test_tools_genai.py`
- [X] T083 Say what the AI generation scope allows in `docs-site/docs/mcp.md` (finding M2)
- [X] T084 Mock refusals with the API's real `{code, message}` detail in `backend/tests/mcp_server/test_tools_genai.py` (finding M3)

## Phase 15: Convergence

- [X] T085 Test 401 on every authenticated genai route, and 422 on the platform switch (finding F1, CLAUDE.md testing policy): `backend/tests/genai/test_api.py`
- [X] T086 List `last_polled_at` in `specs/008-genai/data-model.md` (finding F2)
- [X] T087 Decide a 3D draft from its job before downloading it in `get_generation_output` (finding F3, T082): `backend/app/mcp_server/tools/genai.py` takes the job id and refuses a mesh with no download; tests in `backend/tests/mcp_server/test_tools_genai.py`

## Phase 16: Convergence

- [X] T088 Test every database rule of the three genai tables (finding F1, T007, CLAUDE.md schema policy): each CHECK on `generation_jobs`, `genai_assets` and `genai_adoptions`, the cascade from a job to its assets and adoptions, and `idea_entries.generation_job_id` set to NULL when its job is deleted; `backend/tests/genai/test_models.py`
- [X] T089 Test the month-to-date spend and monthly usage queries (finding F2, T012, R4, R5, SC-002): other tenants excluded, the UTC month boundary, active jobs counted at their estimate, a job that never started costs 0, job counts; `backend/tests/genai/test_costs.py`
- [X] T090 Test the generated-file store (finding F3, T014): a moto S3 round trip, and path tricks refused; `backend/tests/genai/test_storage.py`
- [X] T091 Add the missing endpoint cases (finding F4): 422 on `POST /genai/estimate`, 422 and 403 on `GET /settings/replicate/usage`, 403 on `POST /settings/replicate/test`; `backend/tests/genai/test_api.py`
- [X] T092 [US5] Show the provider, target and submission time in "How it was made" (finding F5, US5 AS4): `frontend/src/components/genai/JobHistory.tsx`; test
- [X] T093 [US4] Offer the images of the products using a model as 3D inputs, or record why not (finding F6, T044): `frontend/src/components/models/ModelFilesEditor.tsx`. No existing API lists the products using a model; US4 AS1 (pick or upload) is met by the model image and uploads.
- [X] T094 Fix where uploads are stored in `specs/008-genai/data-model.md` (finding F7)

## Phase 17: Convergence

- [X] T095 Refuse a blank model version on an override (finding F1, FR-002, FR-003): `_pinned` in `backend/app/schemas/tenant_settings.py` rejects an empty value after stripping, so a community model never runs unpinned; tests in `backend/tests/genai/test_api.py`
- [X] T096 Test the job list order, paging and filters, and the 10 MB upload limit (finding F2, FR-014, US5 AS1, contract): `backend/tests/genai/test_api.py`
- [X] T097 Store and charge no more outputs than were requested (finding F3, R3, R4, SC-002): `backend/app/services/genai/runner.py` keeps the first `count` output URLs; test in `backend/tests/genai/test_service_runner.py`

## Phase 18: Convergence

- [X] T098 [US3] Keep the "does not show the real item" warning through edits (finding F1, SC-005, FR-030, US3 AS4): a job whose inputs include a concept or 3D-draft output, a generation entry from such a job, or a sketch is itself not the real item, decided once at job creation (`generation_jobs.shows_real_item`, migration `20261124_genai.py` edited in place); `adoption.py` and the job response use it; tests in `backend/tests/genai/` (adopting an edited concept into a product: 409 then 201) and the frontend where the flag is shown
- [X] T099 Test the `POST /genai/jobs` refusals at the API: 409 `concurrency_limit` and 503 `queue_unavailable` with the job recorded as failed (finding F2, T020, contract): `backend/tests/genai/test_api.py`
- [X] T100 Test every branch of `backend/app/services/genai/glb.py` (finding F3, T033): Draco/meshopt refusal, triangle cap, byteStride, TRS transforms, u8/u32 and non-indexed primitives, non-triangle modes, sparse accessors and external buffers, too-deep trees, out-of-range indices, each raising `InputInvalid` where it refuses; `backend/tests/genai/test_glb.py`

## Phase 19: Convergence

- [X] T101 [US3] Record on the imported asset whether it shows the real item (finding F1, FR-030, SC-005, contract "or a sketch"): set it once when `_import_image` copies an idea entry or product image (new `genai_assets.shows_real_item`, migration `20261124_genai.py` edited in place, data-model updated), and read it in `_asset_shows_real_item` in `backend/app/services/genai/service.py` instead of scanning earlier single-input jobs, so a sketch, a not-real generation entry or an `ai` product image first used as a concept reference or 3D input stays not real when reused by id; test in `backend/tests/genai/test_shows_real_item.py` (sketch → concept reference → `image_edit` on that asset → 409 `needs_confirmation`)
- [X] T102 Test that a job's write-once fields never change (finding F2, FR-007, data-model Immutability, T015): snapshot capability, provider, model_ref, model_version, inputs, seed, target_type/target_id, estimated_cost, price_snapshot, requested_by_user_id and shows_real_item at creation and assert them equal after submit, poll to success, cancel and timeout, model_version_ran unchanged once set, and a job submitted after the tenant's override changed still runs its recorded model (`runner.job_config`); `backend/tests/genai/test_service_runner.py`
- [X] T103 Describe the product confirmation by the job's own flag in the `adopt_generation_output` tool (finding F3, FR-015, FR-030): an output whose job has `shows_real_item=false` (a concept image, a 3D draft, or a result made from one or from a sketch) needs `confirm_not_real_item=true`; mention the flag in `get_generation_job`'s description; `backend/app/mcp_server/tools/genai.py`, test in `backend/tests/mcp_server/test_tools_genai.py`
- [X] T104 Align the docs with T098 (finding F4): R12 in `specs/008-genai/research.md` says the warning follows the job's `shows_real_item` (capability and inputs); `specs/008-genai/contracts/genai-api.md` says the capability flag is the default a job starts from, not the only trigger; add `shows_real_item` to the Immutability (VI) list in `specs/008-genai/data-model.md`

## Phase 20: Convergence

- [X] T105 [US4] Import a model image only when it is this tenant's own stored file (finding F1 of round 11, CRITICAL, FR-032, FR-031, Constitution I): `Model.image_url` is free text a member can set, so `resolve_input` in `backend/app/services/genai/service.py` accepts a `model_image` only under `/uploads/products/{model.id}/`, and `_import_image` refuses any URL that is not `/uploads/{owner}/{id}/{file}` (no `..`, no backslash); regression tests in `backend/tests/genai/test_service_runner.py`: a foreign product-image path and `/uploads/../x.png` are both refused with no asset row, and the model's own image imports and counts as real
- [X] T106 [US4] Test every input-reference branch of `GenAIService.resolve_input` and the clean-up in `create_job` (finding F2, FR-032, data-model input references, Constitution II): `model_image` success, foreign model, model without an image, external `https://` image; another tenant's `idea_entry` or `product_image` → 404; an idea entry without an image or of a non-image kind refused; a mesh `asset` → 422; a source image missing from storage → 404; when the second input fails, the first imported input's files are deleted and no job is recorded; `backend/tests/genai/test_service_runner.py`
- [X] T107 Test that `genai_assets.shows_real_item` is NOT NULL and defaults to true for a row inserted without it (finding F3, T101): `backend/tests/integration/test_genai_migration.py`

## Phase 21: Convergence

- [X] T108 [US3] Keep an adopted output's resolution so an upscale is not undone (finding F1 of round 12, FR-001, US3 AS1–AS2): adopting an image into a product or an idea in `backend/app/services/genai/adoption.py` keeps the full-resolution file plus a thumbnail (still within the 10 MB rule) instead of `ImageStorage.copy_image`'s 800 px display resize; test in `backend/tests/genai/` that a 1600-px upscale output adopted into a product keeps 1600 px
- [X] T109 [US4] Test the model page's AI input (finding F2, US4 AS1, FR-032): in `frontend/src/components/models/ModelFilesEditor.test.tsx`, a model with `image_url` offers its image in "Draft 3D from image" and Generate sends `input_assets: [{type: 'model_image', id}]`; a model without an image offers none; a 422 `input_invalid` refusal shows the server's message in the dialog
- [X] T110 Test `model_image` tenancy with a real foreign row (finding F3, FR-031, FR-032, T106): in `backend/tests/genai/test_service_runner.py`, a model of another tenant whose `image_url` is its own stored `/uploads/products/{its id}/…` file gives `NotFound`, no asset row and no copied file
- [X] T111 Align the storage docs with the code (finding F4): `specs/008-genai/research.md` R1 (`storage.py` row), R7 step 2 and R10, plus `specs/008-genai/plan.md` "Storage", say that outputs and imported inputs are stored by `GenAIFileStore.save_image` at full resolution under `generations/{job_id}` and `generations/uploads-{tenant_id}`, with an input copied once per job (not on first use)
