# Data Model: Ideas (spec 007)

One migration, `20261123_ideas.py` (revision `ideas_v1`, `down_revision = "catalogue_columns_v1"`,
the current head of `main`; re-pointed if another feature merges first). Both new tables get
`ENABLE` + `FORCE ROW LEVEL SECURITY` and a `{table}_tenant_isolation` policy using the
same `TENANT_MATCHES` expression as `20261103_model_file_versions.py`.

## Table `ideas`

| Column | Type | Null | Default | Rule |
|---|---|---|---|---|
| id | uuid PK | no | uuid4 | |
| tenant_id | uuid FK tenants ON DELETE CASCADE | no | | RLS key, indexed |
| title | varchar(200) | no | | `length(trim(title)) BETWEEN 1 AND 200` |
| summary | text | yes | | markdown, ≤ 20 000 chars (schema) |
| status | varchar(20) | no | `inbox` | CHECK in (`inbox, exploring, validating, ready, converted, parked, dropped`) |
| source | varchar(30) | no | `manual` | CHECK in (`manual, pain_point_report, customer, other`) |
| source_url | varchar(2048) | yes | | http/https only (schema) |
| tags | jsonb | no | `[]` | normalised list (research R11), GIN index |
| score_frequency | smallint | yes | | CHECK 1–5 |
| score_frustration | smallint | yes | | CHECK 1–5 |
| score_printability | smallint | yes | | CHECK 1–5 |
| score_gap | smallint | yes | | CHECK 1–5 |
| score_willingness_to_pay | smallint | yes | | CHECK 1–5 |
| report_score | smallint | yes | | CHECK 0–25; written on create/import only (FR-004a) |
| current_iteration | integer | no | 1 | CHECK ≥ 1 |
| cover_entry_id | uuid FK idea_entries ON DELETE SET NULL | yes | | must be an image/sketch entry of the same idea (service) |
| converted_model_id | uuid FK models ON DELETE SET NULL | yes | | |
| converted_product_id | uuid FK products ON DELETE SET NULL | yes | | |
| created_by_user_id | uuid FK users ON DELETE SET NULL | yes | | |
| archived_at | timestamptz | yes | | |
| created_at, updated_at | timestamptz | no | now() | `TimestampMixin` |

Indexes: `ix_ideas_tenant_status_updated (tenant_id, status, updated_at)`,
`ix_ideas_tags` GIN(tags), `uq_ideas_report_source (tenant_id, source_url) UNIQUE WHERE
source = 'pain_point_report' AND source_url IS NOT NULL`, plus the FK indexes
(`converted_model_id`, `converted_product_id`).

Derived on read (never stored, research R4):

- `score` (hybrid property): the sum of the five scores when all five are set, else
  `report_score`, else NULL.
- `score_source`: `scores` | `report` | null.
- `model_link_state` / `product_link_state` in responses: `linked`, `gone` (the FK was nulled
  by a deletion while `status = converted` and no link remains), or `none`. To tell "gone"
  apart from "never", two booleans `was_converted_to_model` / `was_converted_to_product` are
  set at conversion and never cleared.

Extra columns for that: `was_converted_to_model boolean NOT NULL DEFAULT false`,
`was_converted_to_product boolean NOT NULL DEFAULT false` (FR-030).

### Status transitions

```
inbox ⇄ exploring ⇄ validating ⇄ ready      (any of these ⇄ parked / dropped)
any non-converted ──convert──▶ converted     (only through POST /convert, FR-007)
converted ──PATCH status──▶ any other        (links kept)
```

PATCH with `status = converted` → 422.

## Table `idea_entries`

| Column | Type | Null | Default | Rule |
|---|---|---|---|---|
| id | uuid PK | no | | |
| tenant_id | uuid FK tenants CASCADE | no | | RLS key |
| idea_id | uuid FK ideas ON DELETE CASCADE | no | | indexed |
| kind | varchar(20) | no | | CHECK in (`note, image, link, sketch, measurement, decision, generation`) |
| iteration | integer | no | | CHECK ≥ 1; = idea.current_iteration at creation |
| body | text | yes | | markdown, ≤ 20 000 chars (schema) |
| image_url | varchar(500) | yes | | storage key `/uploads/ideas/{idea_id}/{file}` |
| thumbnail_url | varchar(500) | yes | | |
| content_type | varchar(50) | yes | | |
| original_filename | varchar(255) | yes | | |
| file_size | integer | yes | | |
| link_url | varchar(2048) | yes | | http/https |
| generation_job_id | uuid | yes | | **no FK in 007**; 008 adds `fk_idea_entries_generation_job_id` |
| pinned | boolean | no | false | |
| author_user_id | uuid FK users SET NULL | yes | | |
| edited_at | timestamptz | yes | | set when body/link change after creation |
| archived_at | timestamptz | yes | | |
| created_at, updated_at | timestamptz | no | now() | |

Constraints:

- `ck_idea_entries_image`: `kind NOT IN ('image','sketch') OR image_url IS NOT NULL`
- `ck_idea_entries_link`: `kind <> 'link' OR link_url IS NOT NULL`
- `ck_idea_entries_text`: `kind NOT IN ('note','measurement','decision') OR (body IS NOT NULL AND length(trim(body)) > 0)`
- `ck_idea_entries_iteration`: `iteration >= 1`

Index: `ix_idea_entries_idea_iteration (idea_id, iteration, created_at)`.

Timeline order (FR-017): `iteration DESC, pinned DESC, created_at DESC`.

## Changes to existing tables

| Table | Column | Type | Rule |
|---|---|---|---|
| models | source_idea_id | uuid FK ideas ON DELETE SET NULL, null, indexed | set only by conversion; exposed read-only |
| products | source_idea_id | uuid FK ideas ON DELETE SET NULL, null, indexed | idem |

`ModelCreate` / `ProductCreate` do **not** accept `source_idea_id` from clients, so their API
contract is unchanged. The creation services take it as a separate keyword argument.
`ModelResponse` / `ProductDetailResponse` gain `source_idea_id`, `source_idea_title` and `source_idea_archived`
(optional, null for every existing record — FR-029).

## Storage layout

| Owner | Path | Served by |
|---|---|---|
| products (unchanged, incl. model thumbnails and tenant logo) | `products/{owner_id}/{uuid}.{ext}`, `…_thumb.{ext}` | public `GET /uploads/products/{id}/{file}` (unchanged) |
| ideas | `ideas/{idea_id}/{uuid}.{ext}`, `…_thumb.{ext}` | authenticated `GET /api/v1/ideas/{idea_id}/entries/{entry_id}/image` |
| generations (reserved for 008) | `generations/{job_id}/…` | decided by 008 |

## Entities for later features

- **008** adds the FK on `idea_entries.generation_job_id` and creates `kind = generation`
  entries through its service, with the image copied under `ideas/{idea_id}/` through
  `ImageStorage.copy_image`.
- **009** adds `design_briefs.idea_id` (FK ideas). On conversion it moves the brief to the
  model by adding one step to `IdeaService.convert`, inside its transaction, after the
  model is known (step 2 of research R6).
- **010** reads and writes through the endpoints in `contracts/ideas-api.md`. No other
  surface is needed.
