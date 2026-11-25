# Data Model: Generative AI layer (008)

One migration, `genai_v1` (`backend/alembic/versions/20261124_genai.py`). Its `down_revision` is
the head of main when the migration is written: `ideas_v1` today, then `print_sends_v1` once 011
merges. Exactly one head is required (`poetry run alembic heads`).

New tables: `generation_jobs`, `genai_assets`, `genai_adoptions`. Each has `tenant_id`,
ENABLE + FORCE RLS, and the `{table}_tenant_isolation` policy with the same `TENANT_MATCHES`
expression as `20261123_ideas.py`.

Changed tables: these changes are additive, nullable or defaulted, and leave existing rows valid.

- `product_images.origin`
- FK `idea_entries.generation_job_id → generation_jobs.id`

## generation_jobs

One request for a capability. Model: `app/models/generation_job.py` (`GenerationJob`).

| Column | Type | Rules |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID FK tenants ON DELETE CASCADE, index | RLS |
| capability | String(40) | CHECK in `CAPABILITIES` (concept_image, image_edit, product_photo_enhance, background_remove, upscale, lifestyle_scene, image_to_3d) |
| provider | String(30) | `replicate` today |
| model_ref | String(200) | `owner/name` |
| model_version | String(100) | pinned 64-hex version id, or `official` for a non-pinnable official model (research R3) |
| model_version_ran | String(100) NULL | version id the provider reports it ran; written once at submission |
| inputs | JSONB | `{prompt?, instruction?, scene?, style?, count?, factor?, params:{…}, input_assets:[asset_id…]}` after validation and defaults; immutable |
| seed | BigInteger | always set (chosen when absent); immutable |
| target_type | String(10) | CHECK `idea, product, model, none` |
| target_id | UUID NULL | CHECK `(target_type='none') = (target_id IS NULL)` |
| status | String(12), index | CHECK `queued, running, succeeded, failed, canceled` |
| external_id | String(100) NULL, index | provider prediction id |
| error | Text NULL | readable reason (never contains the token) |
| error_code | String(40) NULL | `provider_error, timeout, auth, rate_limited, download_failed, canceled_by_user, budget…` |
| estimated_cost | Numeric(12,4) | USD, computed by `GenAICostService` before submission |
| cost | Numeric(12,4) NULL | USD final; set once at completion |
| cost_provenance | String(12) NULL | `computed`: price × provider metric, or `estimated`: no metric |
| price_snapshot | JSONB | `{unit, amount, source:"catalog"\|"override"}`: the price used. Written once (VI) |
| shows_real_item | Boolean NOT NULL, server default true | whether the results can show the real item (FR-030, SC-005). Decided once at creation, immutable: false when the capability does not show it (`concept_image`, `image_to_3d`) or when any input does not: an output of a job with `shows_real_item=false`, an idea `generation` entry whose job has it false or is unknown, an idea `sketch`, an `ai` product image whose source job has it false (or cannot be traced), or an upload whose own `shows_real_item` is false. Uploads, photos, `photo`/`render` product images and model images count as real. Adopting into a product reads it (`needs_confirmation`) |
| poll_count | Integer default 0 | backoff bookkeeping |
| last_polled_at | timestamptz NULL | when the job was last read at the provider; the sweep (R6) finds stalled polls by it |
| submitted_at, started_at, completed_at | timestamptz NULL | |
| deadline_at | timestamptz NULL | submitted_at + capability time limit |
| provider_files | JSONB NULL | URLs of input files uploaded to the provider's Files API for this job; deleted there, best effort, once the job ends (R7 step 5, R10) |
| requested_by_user_id | UUID FK users SET NULL | |
| created_at, updated_at | timestamptz | |

Indexes (plain B-tree, which PostgreSQL also reads backwards for the newest-first lists):
`(tenant_id, target_type, target_id, created_at)` for a target's history, `(tenant_id, status)`
for the concurrency count, and `(tenant_id, created_at)` for the month's usage.

**Immutability (VI)**: `capability, provider, model_ref, model_version, model_version_ran (once set), inputs, seed,
target_type, target_id, estimated_cost, price_snapshot, requested_by_user_id, shows_real_item` are
written at creation. The service exposes no update path for them, and a test proves that.

**State machine**:

```
queued ──submit ok──▶ running ──provider succeeded + outputs stored──▶ succeeded
  │                     │──provider failed / timeout / download failed──▶ failed
  │                     └──cancel──▶ canceled
  ├──submit error (after bounded retries) / broker unreachable──▶ failed
  └──cancel──▶ canceled
```

Terminal states (`succeeded, failed, canceled`) never change. Completion runs under a row lock
(`SELECT … FOR UPDATE`) and checks that the job is still `running`. That makes polling and the
webhook idempotent (FR-011).

## genai_assets

A stored file used or produced by the genai layer. Model: `GenAIAsset`, in
`app/models/generation_job.py`.

| Column | Type | Rules |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID FK, index | RLS |
| job_id | UUID FK generation_jobs ON DELETE CASCADE NULL, index | set for outputs |
| source | String(10) | CHECK `output, upload` |
| kind | String(10) | CHECK `image, mesh` |
| storage_url | String(500) | `/uploads/generations/{owner}/{uuid}{ext}`: owner is the job id for an output, `uploads-{tenant_id}` for an upload (`uploads_owner` in `services/genai/service.py`); an image's thumbnail sits beside it as `{uuid}_thumb{ext}` |
| thumbnail_url | String(500) NULL | images only |
| content_type | String(80) | |
| file_size | Integer | |
| width, height | Integer NULL | images |
| original_filename | String(255) NULL | |
| position | Integer default 0 | order within the job's outputs |
| ai_generated | Boolean | `source='output'` ⇒ true (CHECK) |
| shows_real_item | Boolean NOT NULL, server default true | for an upload, whether the picture shows the real item: false for an import of a sketch, of a `generation` entry or an `ai` product image that does not. Set once at import, immutable, so reusing the asset by id keeps the answer (FR-030). An output follows its job's flag |
| created_by_user_id | UUID FK users SET NULL | |
| created_at, updated_at | | |

CHECK `(source='output') = (job_id IS NOT NULL)`.

## genai_adoptions

What an output became. More than one per output is allowed: into an idea, then into a product.
Model: `GenAIAdoption`.

| Column | Type | Rules |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID FK, index | RLS |
| asset_id | UUID FK genai_assets ON DELETE CASCADE | |
| owner_type | String(10) | CHECK `idea, product, model` |
| owner_id | UUID | idea / product / model id |
| idea_entry_id | UUID FK idea_entries SET NULL NULL | |
| product_image_id | UUID FK product_images SET NULL NULL | |
| model_file_id | UUID FK model_files SET NULL NULL | |
| warning_confirmed | Boolean default false | the "not the real item" warning was confirmed (FR-030) |
| adopted_by_user_id | UUID FK users SET NULL | |
| created_at, updated_at | | |

UNIQUE `(asset_id, owner_type, owner_id)` refuses a second adoption of the same output into the
same target (FR-020). The service sets exactly one of the three result FKs at insert; CHECK
`ck_genai_adoptions_one_result` lets at most one be set (a result FK becomes NULL when its row
is deleted).

## Changes to existing tables

| Table | Change | Default for existing rows |
|---|---|---|
| `product_images` | `origin String(10) NOT NULL DEFAULT 'photo'`, CHECK `photo, render, ai` | `photo` (FR-028) |
| `idea_entries` | FK `fk_idea_entries_generation_job_id` → `generation_jobs.id` ON DELETE SET NULL (column exists since 007) | NULL |

## Tenant settings (`Tenant.settings["replicate"]`, JSON, no migration)

```json
{
  "api_token_encrypted": "<fernet>",
  "token_last4": "ab12",
  "monthly_budget_usd": "25.00",
  "model_overrides": {
    "image_edit": {"model_ref": "owner/name", "model_version": "…", "price_unit": "per_output", "price_usd": "0.04"}
  },
  "platform_token_allowed": false,
  "webhook_secret_encrypted": "<fernet>",
  "webhook_secret_token_fingerprint": "<sha256 of token, first 16 hex>",
  "updated_at": "…"
}
```

- The platform admin sets `platform_token_allowed` (FR-023). The tenant settings endpoint never
  writes it.
- Money values are decimal strings (IV). A missing `monthly_budget_usd` means no cap.
- The webhook secret is cached per token through the fingerprint, so a changed token fetches a new
  secret.

## Capability catalog (code, `services/genai/catalog.py`)

Per capability: provider, `model_ref`, pinned `model_version`, `input_mapping` (our field → the
model's field), `default_params`, `output_kind`, `max_inputs`, `time_limit_s`, and
`price {unit: per_output | per_second | per_run, amount_usd, typical_seconds}`. The default
models are in research R3. A tenant override replaces `model_ref`, `model_version`, and
optionally the price. When an override gives no price, the default price is used and
`price_snapshot.source = "catalog"`, so the screen says the cost is an estimate.

## Validation rules (`services/genai/capabilities.py`)

| Capability | Required | Limits |
|---|---|---|
| concept_image | prompt (1–2000 chars) | 0–4 reference assets; count 1–`max_count` of the resolved model (4 for flux-schnell, 1 with references); style ≤ 200 chars |
| image_edit | 1 asset (image), instruction 1–2000 | |
| product_photo_enhance | 1 asset (image) | optional instruction ≤ 500 |
| background_remove | 1 asset (image) | |
| upscale | 1 asset (image) | factor ∈ {2, 4} (default 2) |
| lifestyle_scene | 1 asset (image), scene 1–2000 | count 1–`max_count` (1 with the default model) |
| image_to_3d | 1–4 assets (images) | |

Every input asset reference names a tenant-owned source, which the service resolves to a
`genai_assets` row:

- `{"type":"asset","id"}`: an earlier output or an upload;
- `{"type":"idea_entry","id"}`: an image or sketch entry; copied into a `genai_assets` row of
  source `upload`;
- `{"type":"product_image","id"}`;
- `{"type":"model_image","id": model_id}`: only the model's own stored image, under
  `/uploads/products/{model_id}/`. `Model.image_url` is free text a member can set, so any
  other path, a path with `..` and an external URL are refused with 422 (T105).

Only a Batchivo-stored image (`/uploads/{products|ideas|generations}/{id}/{file}`) is ever
copied. An unknown or foreign id gives 422 or 404; it never hints that another tenant's row exists
(FR-031, FR-032). `seed` is optional, in the range 0–2³¹−1.
