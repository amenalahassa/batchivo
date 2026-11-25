# REST contract: Generative AI (008)

The routers are `api/v1/genai.py`, `api/v1/genai_settings.py` and `api/v1/genai_platform.py`.

Every authenticated route takes `CurrentUser`, `CurrentTenant` and `TenantDB`. Money is a decimal
string in US dollars. Errors use FastAPI's `{"detail": …}`. For a domain refusal, `detail` is an
object `{"code": "...", "message": "..."}` so that screens and MCP tools (010) can branch on
`code`.

Roles (Q3):

| Who | May |
|---|---|
| viewer | read |
| member and up | start, cancel, adopt, upload |
| admin and up | change Replicate settings |
| platform admin | the platform switch |

## Capabilities

### GET `/api/v1/genai/capabilities`, any role

Returns `200`:

```json
{
  "connected": true,
  "token_source": "tenant",
  "capabilities": [
    {
      "capability": "concept_image",
      "label": "Concept image",
      "output_kind": "image",
      "inputs": {"seed": {"required": false, "min": 0, "max": 2147483647}, "prompt": {"required": true, "max_length": 2000}, "style": {"required": false, "max_length": 200}, "count": {"required": false, "min": 1, "max": 4, "default": 1, "max_with_inputs": 1}, "input_assets": {"required": false, "min": 0, "max": 4}},
      "max_count": 4,
      "max_inputs": 4,
      "model_ref": "owner/name",
      "model_version": "…",
      "overridden": false,
      "price": {"unit": "per_output", "amount_usd": "0.003", "source": "catalog"},
      "time_limit_s": 600,
      "shows_real_item": false
    }
  ]
}
```

`inputs` is keyed by the input field a job takes and is derived from the same validation the
service applies: `required`; `min_length`/`max_length` for text; `min`/`max` for numbers and for
`input_assets` (number of images); `values` for a choice (upscale `factor`); `default`.
`count.max_with_inputs` is the count limit once reference images are added (concept_image).
`max_inputs` is how many input images the operator may pick.

`token_source` is one of `tenant`, `platform` or `none`. `shows_real_item: false` marks the
capabilities whose results never show the real item: `concept_image` and `image_to_3d`. It is the
value a job starts from, not the only trigger of the product warning: a job's inputs can make it
false too (see `shows_real_item` on the job).

### POST `/api/v1/genai/estimate`, any role

The body is the same as for job creation. Returns `200`:

```json
{"estimated_cost": "0.0120", "month_to_date": "3.4100", "budget": "25.00", "would_exceed_budget": false}
```

Returns `422` on invalid inputs.

## Jobs

### POST `/api/v1/genai/jobs`, member and up

Request:

```json
{
  "capability": "concept_image",
  "inputs": {"prompt": "…", "count": 2, "style": "studio", "seed": 42,
             "input_assets": [{"type": "idea_entry", "id": "…"}]},
  "target": {"type": "idea", "id": "…"}
}
```

`201` returns a `GenerationJob`:

```json
{
  "id": "…", "capability": "concept_image", "provider": "replicate",
  "model_ref": "owner/name", "model_version": "…",
  "inputs": {…}, "seed": 42,
  "target": {"type": "idea", "id": "…"},
  "status": "queued", "error": null, "error_code": null,
  "estimated_cost": "0.0060", "cost": null, "cost_provenance": null,
  "price": {"unit": "per_output", "amount_usd": "0.003", "source": "catalog"},
  "shows_real_item": false,
  "requested_by": {"id": "…", "name": "…"},
  "created_at": "…", "submitted_at": null, "started_at": null, "completed_at": null,
  "outputs": [],
  "can_cancel": true
}
```

`shows_real_item` is decided once at creation: `false` for a capability that does not show the
real item, and for any job whose inputs include a result of such a job (an output, an idea
`generation` entry, an `ai` product image) or a sketch. It is what the product adoption checks.

Refusals:

| Status | When |
|---|---|
| `401` | not signed in |
| `403` | viewer |
| `404` | target or input asset not found in this tenant |
| `409` | `{code: "not_connected"}`: no usable token |
| `409` | `{code: "budget_exceeded", message names budget and month-to-date}` |
| `409` | `{code: "concurrency_limit"}` |
| `422` | capability or input validation |
| `503` | `{code: "queue_unavailable"}`: the broker is unreachable; the job is recorded as failed with that reason |

### GET `/api/v1/genai/jobs`, any role

Query parameters: `target_type`, `target_id`, `status`, `capability`, `skip` (default 0),
`limit` (default 20, max 100). Returns `200` with `{"items": [GenerationJob], "total": n}`,
newest first. Returns `422` on a bad filter.

### GET `/api/v1/genai/jobs/{job_id}`, any role

Returns `200` with a `GenerationJob` whose `outputs` hold `GenAIAsset`:

```json
{"id": "…", "kind": "image", "content_type": "image/png", "file_size": 12345,
 "width": 1024, "height": 1024, "position": 0, "ai_generated": true,
 "file_path": "/api/v1/genai/assets/{id}/file", "thumbnail_path": "/api/v1/genai/assets/{id}/file?variant=thumb",
 "adoptions": [{"owner_type": "idea", "owner_id": "…", "idea_entry_id": "…", "product_image_id": null, "model_file_id": null, "created_at": "…"}]}
```

Returns `404` when the job is not in this tenant.

### POST `/api/v1/genai/jobs/{job_id}/cancel`, member and up

Returns `200` with the job (status `canceled`), and `404` when not found. Returns `409`
`{code: "not_cancellable"}` when the job is already terminal. A provider cancel failure is
logged; the job is still canceled locally, and any later webhook for it is ignored.

## Assets

### POST `/api/v1/genai/uploads`, member and up

Multipart `file` field (an image of 10 MB or less: jpeg, png or webp). Returns `201` with a
`GenAIAsset` of source `upload`, which can be used as `{"type": "asset", "id"}`. Returns `422`
for an invalid file.

### GET `/api/v1/genai/assets/{asset_id}/file?variant=thumb|full`, any role

Returns `200` with the bytes and `Cache-Control: private`. A mesh is served as
`model/gltf-binary`. Returns `404` when not found.

### POST `/api/v1/genai/assets/{asset_id}/adopt`, member and up

Request:

```json
{"target": {"type": "idea" | "product" | "model", "id": "…"}, "confirm_not_real_item": false,
 "alt_text": "…", "version_note": "…"}
```

Returns `201`:

```json
{"adoption": {…}, "idea_entry_id": "…" | null, "product_image_id": "…" | null, "model_file_id": "…" | null, "model_file_version_id": "…" | null}
```

Effects:

| Target | Effect |
|---|---|
| idea | a `generation` entry in the current iteration, `generation_job_id` set; the image is copied under `ideas/{id}/`, a mesh is referenced |
| product | an image is copied under `products/{id}/` as a new `ProductImage` with `origin='ai'`, last in order and never primary. A mesh gives `422 {code: "wrong_kind"}` |
| model | a mesh is converted from GLB to STL and added as a new inactive version labelled "AI draft". Measurement is recorded and not applied. An image gives `422` |

Refusals:

| Status | When |
|---|---|
| `403` | viewer |
| `404` | asset or target not found |
| `409` | `{code: "already_adopted"}` |
| `409` | `{code: "needs_confirmation"}`: product target, the asset's job has `shows_real_item=false`, and `confirm_not_real_item` is false |
| `409` | `{code: "not_succeeded"}`: the asset's job has not succeeded |
| `422` | wrong kind |

## Provider webhook (unauthenticated, signature-verified)

### POST `/api/v1/genai/webhooks/replicate/{tenant_id}/{job_id}`

- Headers: `webhook-id`, `webhook-timestamp`, `webhook-signature`.
- The handler sets the RLS context to `tenant_id`, loads the job and resolves that tenant's
  signing secret.
- It verifies HMAC-SHA256 over `"{id}.{timestamp}.{raw body}"`, with a timestamp tolerance of
  5 minutes.

| Response | When |
|---|---|
| `204` | valid; the job completed, or already terminal (idempotent) |
| `401` | missing or invalid signature, or stale timestamp; nothing changes |
| `404` | unknown tenant or job, or the body's prediction id ≠ the job's `external_id`; nothing changes |

The webhook URL is only sent to the provider when `GENAI_WEBHOOK_BASE_URL` is configured.

## Replicate settings (tenant)

### GET `/api/v1/settings/replicate`, admin and up

Returns `200`:

```json
{
  "is_configured": true, "token_masked": "…ab12", "token_source": "tenant",
  "platform_token_available": true, "platform_token_allowed": false,
  "monthly_budget": "25.00", "currency": "USD",
  "month_to_date": "3.4100", "jobs_this_month": 12, "active_jobs": 1, "concurrency_limit": 3,
  "model_overrides": {"image_edit": {"model_ref": "…", "model_version": "…", "price_unit": "per_output", "price_usd": "0.04"}},
  "updated_at": "…"
}
```

Returns `403` for a member or viewer, and `401` when not signed in.

### PUT `/api/v1/settings/replicate`, admin and up

```json
{"api_token": "r8_…" | "" (remove) | null (keep), "monthly_budget": "25.00" | null (keep),
 "clear_budget": false, "model_overrides": {"image_edit": {…} | null (clear)}}
```

Every field is optional; one left out or `null` keeps its stored value. `clear_budget: true`
removes the budget (no cap), and wins over `monthly_budget`.

An override may carry `typical_seconds` (1–3600): how long a run usually takes, used to
estimate a `per_second` price. Without it the estimate uses the default model's run time,
or else the capability's time limit, marked assumed, so a per-second estimate is never 0.

Validation errors on this route never repeat the submitted values (no `input` in the 422
detail), so a refused token is not sent back.

Returns `200` with the response above, and `422` for:

- a negative budget, or one with more than 2 decimals;
- an unknown capability;
- a version that is empty or `latest`;
- an invalid price.

### POST `/api/v1/settings/replicate/test`, admin and up

Returns `200` with `{"success": bool, "message": "…", "account": "username" | null, "token_source": "…"}`.
`message` never contains the token.

### GET `/api/v1/settings/replicate/usage?months=6`, admin and up

Returns `200` with `{"months": [{"month": "2026-11", "cost": "3.4100", "jobs": 12}]}`.

## Platform switch (Q2)

### GET and PUT `/api/v1/platform/tenants/{tenant_id}/genai`, platform admin

PUT body: `{"platform_token_allowed": true}`. `200` returns
`{"tenant_id": "…", "platform_token_allowed": true, "platform_token_available": true}`. Other
responses:

- `403`: not a platform admin;
- `404`: unknown tenant;
- `422`: bad body.

Each PUT writes an audit log entry.

## Ideas conversion (007, extended)

`POST /api/v1/ideas/{id}/convert`: the request and the response schema are unchanged. When a
new model is created, it gets one inactive "AI draft" version per adopted, non-archived mesh entry
of the idea (FR-017a). A draft that cannot be copied becomes a `warnings[]` line, as an image that
cannot be copied already does. Any other failure rolls the conversion back, and the copied files
are deleted.
