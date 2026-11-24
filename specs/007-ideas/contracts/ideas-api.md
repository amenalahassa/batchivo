# Contract: Ideas API (`/api/v1/ideas`)

All endpoints: `CurrentUser` + `CurrentTenant` + `TenantDB`. Writes add `RequireMember`
(a viewer gets 403). No token → 401. An idea or entry of another tenant, or an unknown id → 404.
Validation → 422. Every write updates `ideas.updated_at`.

## Schemas (`schemas/idea.py`)

```text
IdeaScores        { frequency?, frustration?, printability?, gap?, willingness_to_pay? : int 1..5 | null }
IdeaBase          { title: str 1..200 (trimmed), summary?: str ≤20000, source: manual|pain_point_report|customer|other,
                    source_url?: http(s) URL ≤2048, tags: list[str] (normalised, ≤20 × ≤40), scores: IdeaScores }
IdeaCreate        IdeaBase + { status?: inbox|exploring|validating|ready|parked|dropped (default inbox),
                    report_score?: int 0..25 }
IdeaUpdate        all IdeaBase fields optional + { status?: (not "converted"), archived?: bool,
                    cover_entry_id?: uuid | null }
IdeaLink          { id: uuid | null, name?: str, sku?: str, state: linked|gone|none }
IdeaSummary       { id, title, status, source, source_url, tags, scores, report_score,
                    score: int|null, score_source: scores|report|null,
                    cover_thumbnail_path: str|null, current_iteration, archived: bool,
                    model: IdeaLink, product: IdeaLink, created_at, updated_at }
IdeaDetail        IdeaSummary + { summary, cover_entry_id, cover_image_path, created_by: {id,name}|null }
IdeaListResponse  { items: list[IdeaSummary], total: int, skip: int, limit: int }

IdeaEntryCreate   { kind: note|link|measurement|decision, body?: str ≤20000, link_url?: http(s) URL }
                  (kind image|sketch → use /entries/images; kind generation → 422)
IdeaEntryUpdate   { body?, link_url?, pinned?: bool, archived?: bool, kind?: image|sketch (only between these two) }
IdeaEntryResponse { id, idea_id, kind, iteration, body, link_url, pinned, archived,
                    image_path: str|null, thumbnail_path: str|null, content_type, original_filename, file_size,
                    generation_job_id: uuid|null, author: {id,name}|null, created_at, edited_at }
IdeaEntryList     { items: list[IdeaEntryResponse], current_iteration: int }
ImageUploadResult { created: list[IdeaEntryResponse], refused: list[{ filename, reason }] }

IterationCreate   { note?: str ≤20000 }

ConvertRequest    { target: model|product, name?: str 1..200 (default idea title),
                    model_sku?: str, product_sku?: str, include_images: bool = true }
ConvertResponse   { idea: IdeaDetail, model_id: uuid, product_id: uuid|null, copied_images: int,
                    warnings: list[str] }

ImportItem        { title, summary?, scores?: IdeaScores, report_score?: 0..25, tags?: list[str],
                    source_url?: http(s) URL }
ImportRequest     { items: list[ImportItem] (1..200), dry_run: bool = false }
ImportResult      { created: list[{ id|null, title }], skipped: list[{ title, source_url, existing_idea_id }],
                    refused: list[{ index, title|null, reason }] }
ParseReportRequest  { text: str 1..500000 }
ParseReportResponse { items: list[ImportItem], warnings: list[str] }
```

`image_path` / `thumbnail_path` / `cover_*_path` are API paths
(`/api/v1/ideas/{idea_id}/entries/{entry_id}/image?variant=full|thumb`), never storage keys.

## Endpoints

| Method | Path | Role | Success | Errors |
|---|---|---|---|---|
| GET | `/ideas` | viewer | 200 `IdeaListResponse` | 401, 422 (bad sort/limit) |
| GET | `/ideas/tags` | viewer | 200 `list[str]` | 401 |
| POST | `/ideas` | member | 201 `IdeaDetail` | 401, 403, 422, 409 (report source_url taken) |
| GET | `/ideas/{id}` | viewer | 200 `IdeaDetail` | 401, 404 |
| PATCH | `/ideas/{id}` | member | 200 `IdeaDetail` | 401, 403, 404, 422 (status converted, bad cover), 409 |
| DELETE | `/ideas/{id}` | member | 200 `IdeaDetail` (archived) | 401, 403, 404 |
| GET | `/ideas/{id}/entries` | viewer | 200 `IdeaEntryList` (`?archived=false`) | 401, 404 |
| POST | `/ideas/{id}/entries` | member | 201 `IdeaEntryResponse` | 401, 403, 404, 422 |
| POST | `/ideas/{id}/entries/images` | member | 201 `ImageUploadResult` (multipart `files[]`, `kind=image|sketch`, ≤10 files) | 401, 403, 404, 422 (no file / all refused → 422 with `refused`) |
| PATCH | `/ideas/{id}/entries/{entry_id}` | member | 200 `IdeaEntryResponse` | 401, 403, 404, 422 |
| DELETE | `/ideas/{id}/entries/{entry_id}` | member | 200 `IdeaEntryResponse` (archived; clears cover) | 401, 403, 404 |
| GET | `/ideas/{id}/entries/{entry_id}/image` | viewer | 200 image bytes (`?variant=full|thumb`, `Cache-Control: private`) | 401, 404 (no image / file missing) |
| POST | `/ideas/{id}/iterations` | member | 201 `IdeaEntryList` (new iteration, note entry if given) | 401, 403, 404, 422 |
| POST | `/ideas/{id}/convert` | member (+admin for product) | 201 `ConvertResponse` | 401, 403, 404, 409 (archived / already converted to product), 400 (SKU taken, from creation service), 422 |
| POST | `/ideas/import` | member | 200 `ImportResult` | 401, 403, 422 (empty / >200 items) |
| POST | `/ideas/import/parse-report` | member | 200 `ParseReportResponse` | 401, 403, 422 |

### `GET /ideas` query

`status` (repeatable), `tag` (repeatable, AND), `source`, `search` (title or summary, ILIKE),
`archived` (`false` default | `true` | `all`), `sort` (`updated` default | `score` | `created`),
`skip` ≥ 0, `limit` 1..100 (default 20).

### Rules

- `POST /ideas` with `report_score` and complete `scores`: both are kept, and `score` uses the scores.
- `PATCH cover_entry_id` must name a non-archived `image`/`sketch` entry of the same idea, else 422.
- `PATCH archived=false` restores, both on ideas (`PATCH /ideas/{id}`) and on entries.
- Image upload: each file is validated and saved separately. Refused files appear in `refused`
  with their reason, and the request still returns 201 if at least one file was saved.
- Import: classifies each item in order as `refused` (invalid), `skipped` (source_url
  already on a `pain_point_report` idea of the tenant, or repeated earlier in the payload)
  or `created`. With `dry_run` it writes nothing and returns `id = null` for `created`.

## Changes to existing endpoints (no breaking change)

| Endpoint | Change |
|---|---|
| `POST /api/v1/models`, `POST /api/v1/products` | none (body and response identical; logic moved to `services/model_creation.py` / `services/product_creation.py`) |
| `GET /api/v1/models/{id}` and list, `GET /api/v1/products/{id}` and list | responses gain optional `source_idea_id`, `source_idea_title`, `source_idea_archived` (null for existing rows) |
| `GET /uploads/products/{product_id}/{filename}` | unchanged |
