# Research: Generative AI layer (008)

Decisions R1–R14. Deviations from `docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §5 are marked
**Deviation**, each with its reason.

## R1. Package shape: `services/genai/`, callable without HTTP

- **Decision**: `backend/app/services/genai/` holds these modules.

  | Module | Holds |
  |---|---|
  | `capabilities.py` | `Capability` enum, input models, validation |
  | `catalog.py` | default models and prices; tenant override merge |
  | `base.py` | `GenAIProvider` Protocol: `submit`, `get`, `cancel`, `upload_input`, `account`, `webhook_secret`, `verify_webhook`; plus the `ProviderPrediction` dataclass and the `ProviderError` hierarchy |
  | `replicate.py` | `ReplicateProvider` (httpx) |
  | `costs.py` | `GenAICostService`, the only place a cost is computed |
  | `credentials.py` | token resolution (tenant → authorised platform → none), webhook secret cache |
  | `glb.py` | GLB → binary STL converter |
  | `storage.py` | `GenAIFileStore`: outputs (images at full resolution, meshes) and imported inputs, under `generations/` |
  | `service.py` | `GenAIService(db, tenant, user)`: `list_capabilities`, `estimate`, `create_job`, `list_jobs`, `get_job`, `cancel_job`, `upload_input`, `adopt`, `open_asset` |
  | `runner.py` | `submit_job`, `poll_job`, `complete_job`, `fail_job`, `sweep_stale`; called by the Celery tasks and the webhook |
  | `adoption.py` | adoption into an idea, a product or a model; `carry_idea_drafts` for conversion |
  | `errors.py` | `GenAIError(code, message, http_status)` subclasses |
  | `providers.py` | `get(name) -> GenAIProvider` registry |
  | `webhooks.py` | signature verification and the webhook handler |
  | `logging.py` | token-redaction filter |

- **Why**: the routers stay thin (III). The service raises domain errors and never
  `HTTPException`. Feature 010's MCP tools call the REST API, but a future in-process caller
  (scripts, 009 Preflight) can call `GenAIService` directly with a session and tenant.
- **Alternatives**: one big `genai_service.py` was rejected, because provider, cost and runner
  concerns would mix. The architecture's `models/generation_job.py` holds all three new models,
  because they form one aggregate.

## R2. Provider protocol and the second-provider promise

- **Decision**: the catalog entry names the `provider`. `providers.get(name)` returns a
  `GenAIProvider`. Screens and the API only see capabilities. The job records `provider`, so a
  job finishes on the provider it started on even if the catalog later changes.
- **Why**: FR-004. Adding a provider means a new adapter plus catalog entries, with no route or
  screen change.

## R3. Default models (catalog)

Source: public Replicate pages read on 2026-11-24 (replicate.com/pricing, each model's `/api`
and `llms.txt` pages, docs/reference/http). No API call was made.

| Capability | Model | Kind | Version | Mapping and defaults | Output | Price (USD) |
|---|---|---|---|---|---|---|
| concept_image (no references) | `black-forest-labs/flux-schnell` (Apache-2.0) | official | not pinnable → version actually run is recorded (see below) | prompt→`prompt`, count→`num_outputs` (1–4), seed→`seed`; `aspect_ratio="1:1"`, `output_format="png"`, `go_fast=true` | URI array | per_output 0.003 (confirmed) |
| concept_image (with references) | `google/nano-banana` | official | as above | prompt→`prompt`, references→`image_input[]` (≤4); count fixed at 1; `output_format="png"` | URI | per_output 0.039 (third-party figure; SynthID watermark) |
| image_edit | `black-forest-labs/flux-kontext-pro` | official | as above | instruction→`prompt`, image→`input_image`, seed; `aspect_ratio="match_input_image"`, `output_format="png"`, `safety_tolerance=2` | URI | per_output 0.04 (third-party) |
| product_photo_enhance | same model as image_edit | official | as above | fixed `prompt` = "Clean professional studio product photo: soft even lighting, neutral background, remove clutter and dust. Keep the product exactly identical in shape, colour and details.", with the optional operator instruction appended | URI | per_output 0.04 |
| background_remove | `851-labs/background-remover` | community | `a029dff38972b5fda4ec5d75d7d1cd25aeff621d2cf4946a41055d7db66b80bc` | image→`image`; `format="png"`, `background_type="rgba"` | URI (PNG alpha) | per_second 0.000225 (T4), typical 3 s |
| upscale | `nightmareai/real-esrgan` | community | `f121d640bd286e1fdc67f9799164c1d5be36ff74576ee11c803ae5b665dd46aa` | image→`image`, factor→`scale`; `face_enhance=false` | URI | per_second 0.000225 (assumed T4: hardware not shown), typical 10 s |
| lifestyle_scene | `bria/generate-background` (trained on licensed data) | official | not pinnable | image→`image`, scene→`bg_prompt`, seed; `original_quality=true` | URI array (first taken) | per_output 0.04 (Bria's own figure) |
| image_to_3d | `firtoz/trellis` (MIT) | community | `e8f6c45206993f297372f5436b90350817bd9b4a0d52d2a76df50c1c8afa2b3c` | images→`images[]`, seed→`seed`; `generate_model=true`, `randomize_seed=false`, `texture_size=1024`, `mesh_simplify=0.95`, `generate_color=false` | object, key `model_file` (GLB) | per_second 0.0014 (A100-80GB), typical 30 s |

- **Count limit per model**: the catalog carries `max_count`. It is 4 for flux-schnell and 1
  elsewhere, so lifestyle scenes and concepts with references produce one image per job. The
  capability's validation uses the resolved config's `max_count`.
- **Overrides of concept_image (FR-003)**: a tenant override of `concept_image` replaces only
  the model used without reference images (flux-schnell by default). A concept with reference
  images always runs on the official with-references model (`google/nano-banana`) at its catalog
  price, because an override must accept the inputs of the model it replaces and the two models
  take different inputs (`num_outputs` against `image_input[]`).
- **Output extraction**: the catalog carries an `output_key` (`model_file` for TRELLIS) and
  normalises str, list or object outputs to a URL list.
- **Unverified prices** carry an `assumed` note in the catalog. The settings page labels every
  cost as an estimate unless provenance is `computed` from `predict_time`. Operators can set
  their own price in an override.

**Official models and version pinning (user answer B, 2026-11-24)**: Replicate
does not document version pinning for "official" models. They are kept on the latest version
with a stable interface, and are billed per output. The design follows recommendation B:

- a catalog entry has `pinnable: bool`;
- for an official model, `model_version` holds the literal `"official"`, and the job records
  `model_version_ran`, the version id the provider reports in the prediction. It is written once,
  at submission, and is shown in the job details;
- community models are always pinned to a 64-hex version;
- a tenant override must name a pinned version, unless it targets an official model, which the
  settings form marks explicitly.

FR-002 was amended accordingly (spec Clarifications).

## R4. Cost: estimated before, computed after, one service

- **Decision**: `GenAICostService` (`services/genai/costs.py`).
  - `estimate(capability_config, validated_inputs) -> Decimal`:
    - `per_output`: amount × count;
    - `per_run`: amount;
    - `per_second`: amount × `typical_seconds`.
  - `final(job, prediction) -> (Decimal, provenance)`:
    - `per_output`: amount × outputs actually returned;
    - `per_second`: amount × `metrics.predict_time` → `computed`;
    - no metric: the estimate → `estimated`.
  - `month_to_date(tenant)` sums the final cost of terminal jobs and the estimate of active jobs
    (queued or running) created this UTC month. Failed jobs with no `started_at` cost 0.
  - All values are `Decimal`, quantised to 0.0001 only when stored (IV). They travel as strings.
- **Why**: Replicate does not return a monetary cost on a prediction. It returns
  `metrics.predict_time`, and models are priced per output or per second of hardware. Constitution
  III asks for one place, so the routes and the frontend never multiply.
- **Provenance (VI)**: `price_snapshot` stores the unit price and its source (catalog or override)
  at creation, so a later price change never restates a past job.
- **Deviation**: the architecture's "provider-reported" cost does not exist for Replicate. The
  provenance values are `computed` and `estimated`.

## R5. Budget and concurrency: checked atomically before submission

- **Decision**: `create_job` takes `pg_advisory_xact_lock(hashtextextended(tenant_id::text, 8))`
  (skipped on SQLite tests). Under that lock it:
  1. counts active jobs, and refuses at `GENAI_MAX_CONCURRENT_JOBS` (default 3);
  2. refuses when `month_to_date + estimate > budget`;
  3. inserts the job.
- **Why**: two simultaneous clicks must not both pass the checks (SC-002). The advisory lock is
  per tenant and transaction-scoped, so it needs no new table.

## R6. Execution: short Celery tasks chained by countdown, plus a sweep

- **Decision**: three tasks in `tasks/genai.py`, all run through `run_in_task_loop`.
  - `genai.submit(job_id, tenant_id)`:
    - uploads the input assets to the provider;
    - creates the prediction, with the webhook when `GENAI_WEBHOOK_BASE_URL` is set;
    - stores `external_id`, sets the status to running and `deadline_at`;
    - schedules `genai.poll` with a countdown of 2 s.
    - Transient errors (network, 429, 5xx) retry up to 3 times with backoff; then the job fails.
  - `genai.poll(job_id, tenant_id)`:
    - stops if the job is terminal (the webhook won);
    - when the prediction is terminal, calls `complete_job`;
    - past `deadline_at`, cancels at the provider and fails the job with `timeout`;
    - otherwise reschedules itself with a backoff of min(2·1.5ⁿ, 30) s.
  - `genai.sweep` (beat, every 5 min): re-polls running jobs with no poll for over 2 min, fails
    queued jobs stuck for over 10 min, and enforces deadlines.
- **Why**: a 30-minute image-to-3D job must not hold a worker. Each step is short and idempotent
  (`task_acks_late`). The sweep catches a broken chain, such as a broker restart. Polling needs
  no public URL (FR-010).
- **Dispatch**: `GenAIService.create_job` commits, then calls `dispatch_submit()`. When that
  raises, the job becomes failed (`queue_unavailable`) and the route answers 503. This follows
  `tasks/scenario.py`.
- **Alternative**: a single long task polling in a loop was rejected; it blocks a worker.
- **Inline mode**: `GENAI_RUN_INLINE` is accepted only when `environment` is `development` or
  `test`, or when E2E hooks are on. With it, the dispatch functions run the same runner steps as
  `asyncio` tasks in the API process, in a fresh session. This lets local development and the
  e2e stack work without a Celery worker; production always uses Celery.

## R7. Completion: idempotent, outputs stored before "succeeded"

- **Decision**: `complete_job(db, tenant, job_id, prediction)` runs as follows.
  1. It locks the row (`with_for_update`) and returns if the job is not `running`.
  2. On provider success:
     - it downloads each output URL with the provider's auth header, within the size limits
       (image 10 MB, mesh 200 MB) and with a 60 s timeout;
     - it stores each output through `GenAIFileStore` under `generations/{job_id}/`, an image at
       full resolution with a thumbnail, a mesh as is;
     - it creates the `genai_assets` rows;
     - it computes the final cost and sets `succeeded`.
  3. If any download or store fails, the files already stored are deleted and the job fails
     with `download_failed` (spec edge case).
  4. A provider failure or cancellation fails or cancels the job with a readable reason.
  5. It then deletes the uploaded input files at the provider (best effort).
- **Why**: FR-009, FR-011, SC-003. Downloading happens inside the task or the webhook request.
  A webhook handler that downloads a 50 MB mesh is acceptable: Replicate retries webhooks, and
  the row lock makes a retry a no-op.

## R8. Webhook verification

- **Decision**:
  - URL: `{GENAI_WEBHOOK_BASE_URL}/api/v1/genai/webhooks/replicate/{tenant_id}/{job_id}`, with
    `webhook_events_filter: ["completed"]`.
  - Verification follows the Standard Webhooks scheme Replicate uses: HMAC-SHA256 with the
    base64-decoded secret (after `whsec_`) over `"{webhook-id}.{webhook-timestamp}.{body}"`,
    compared in constant time with each `v1,<sig>` in `webhook-signature`. The timestamp must be
    within 5 minutes.
  - The secret is fetched once per token from `GET /v1/webhooks/default/secret` and cached
    encrypted in tenant settings, keyed by a token fingerprint. The platform token's secret is
    cached in process memory.
  - The tenant is resolved from the path, and the RLS context is set before any query.
  - A body whose `id` ≠ the job's `external_id` gets 404.
- **Why**: a forged or replayed call must not complete a job or cross tenants (FR-010, FR-031).
- **Testing**: respx mocks the secret endpoint. The tests sign bodies with a test secret and
  cover valid, invalid, missing and stale signatures, a wrong tenant and a wrong prediction id.

## R9. Credentials and the platform token (Q2)

- **Decision**: `credentials.resolve(tenant) -> ResolvedToken(token, source)`:
  1. the tenant's `api_token_encrypted`;
  2. else `settings.replicate_api_token`, if (`platform_token_allowed` on the tenant or
     `settings.genai_platform_token_all_tenants`);
  3. else none → `not_connected`.
- `genai_platform_token_all_tenants` (default `false`) is the single-shop VPS switch. The
  instance config sets it, so "the only shop is authorised automatically" holds there without a
  platform-admin screen. The multi-tenant cluster leaves it false.
- The token is only decrypted in `credentials.py` and the provider. Responses carry only the
  last 4 characters.
- A logging filter on the `app.services.genai` loggers redacts `r8_…` patterns and
  `Authorization` values. httpx is configured not to log headers. A test asserts the token is
  absent from captured logs and from error messages (FR-021, SC-006).

## R10. Input images

- **Decision**: every input is a `genai_assets` row of the tenant.
  - Idea entries, product images and model images are copied into a `genai_assets` upload row
    by `GenAIFileStore.save_image`, at full resolution, under `generations/uploads-{tenant_id}/`;
    each job that names one makes its own copy (it is not reused across jobs).
  - At submit, an input of 256 KB or less is sent as a data URI (not stored by the provider);
    a larger one is uploaded through the provider's Files API (`POST /files`, under 100 MB),
    and its `urls.get` is passed in the prediction input, then deleted after completion.
- **Why**: FR-032 forbids arbitrary URLs. Local installs have no public URL for the provider to
  fetch. A job's `inputs` record asset ids, which are immutable, so the exact input stays
  traceable even if the source idea image is later archived.

## R11. GLB to STL for model adoption

- **Decision**: `services/genai/glb.py` holds a pure-Python reader. It parses the glTF binary
  container (JSON chunk, BIN chunk), walks the default scene's nodes with their matrices or TRS,
  reads POSITION accessors (float32 VEC3) and indices (u8, u16 or u32), and writes a binary STL.
  The GLB itself stays as the output asset (download, 3D viewer); the STL is what goes into the
  model file version.
- **Why**: `ModelFileService` accepts STL, 3MF and G-code, and `mesh_bounds` measures STL and
  3MF. Converting keeps the 004 upload path unchanged (one storage implementation, III), and the
  existing 3D viewer shows STL. No numpy or trimesh is needed, so there is no new dependency.
- **Scale**: image-to-3D output has no real units. The draft's measurement is recorded on the
  file for information, and `offer_measurement=False` keeps it off the model's dimensions
  (FR-019, as amended).

## R12. Origin of product images (FR-028)

- **Decision**: `product_images.origin` (`photo` | `render` | `ai`, default `photo`, so existing
  rows are photos).
  - The existing PATCH accepts `photo` or `render`. `ai` is refused through PATCH (422); only
    adoption sets it.
  - The editor shows a badge for `ai` and an origin select for the others.
  - The product warning applies when the source job has `shows_real_item = false`. The job
    decides it once at creation, from its capability (`concept_image` and `image_to_3d` start
    false) and its inputs: a result made from a concept, a 3D draft or a sketch is not the real
    item either (T098, T101). Edits of a real photo (enhance, background, upscale, lifestyle)
    do not warn, but they are badged.
- **Why**: provenance stays visible (VI), and an operator cannot relabel AI output as a photo.

## R13. Frontend shape

- `lib/api/genai.ts`, `types/genai.ts`, and `hooks/useGenAI.ts`, which holds `useCapabilities`,
  `useGenerationJob` (with `refetchInterval` 2 s while queued or running), `useGenerationJobs`,
  `useCreateJob`, `useCancelJob`, `useAdoptAsset`, `useReplicateSettings` and `useEstimate`.
- `components/genai/`:
  - `GenerateDialog`: one reusable dialog per capability, with prompt or instruction fields,
    input asset picker, count, estimated cost (from `/estimate`), progress, a result grid with
    Adopt, and the not-connected state;
  - `GenAIAssetImage` (auth image), `MeshPreview` (GLB in the existing viewer canvas),
    `AIBadge`, `JobStatusBadge`, `AdoptConfirmDialog` (warning), `PlatformGenaiCard`.
- Pages and components:
  - Ideas: a "Generate concept" button in `IdeaComposer`'s `extraActions`. `IdeaEntryItem` gets
    a menu ("Edit with AI", "Variations", "Draft 3D shape") on image entries, and renders
    generation entries (image, or 3D viewer for a mesh).
  - Products: the `ProductImagesEditor` per-image menu (enhance, remove background, upscale,
    lifestyle scene), plus the origin badge and select.
  - Models: a "Draft 3D from image" button in `ModelFilesEditor`, and an "AI draft" badge.
  - Settings: an "AI" tab with `ReplicateSettings`.
- **Why**: one dialog is used everywhere, as the architecture asks. Viewers see the history but
  no generate buttons (FR-033).

## R14. Testing without the real Replicate

- **Decision**: every provider HTTP call goes through one `httpx.AsyncClient` built in
  `replicate.py`, and tests mock `https://api.replicate.com` with `respx`. A pytest fixture
  `replicate_mock` installs routes for account, files, predictions (create, get, cancel), output
  downloads and the webhook secret. A guard fixture (autouse in the genai test modules) fails any
  test that reaches an unmocked Replicate URL (`respx.mock(assert_all_mocked=True)`). Celery
  dispatch is patched (`dispatch_submit`, `dispatch_poll`), and the runner functions are called
  directly. E2E runs against a backend whose provider base URL points at a local fake
  (`GENAI_PROVIDER_BASE_URL`, used only when `E2E_TEST_HOOKS_ENABLED=true`). It is a tiny route
  set in `api/v1/genai_e2e.py`, mounted only with test hooks, that imitates the provider. No
  real token or money is ever involved.
