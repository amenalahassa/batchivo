# Research: Ideas (spec 007)

Decisions taken while planning, with what was rejected. Departures from
`docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` are marked **Deviation** and justified.

## R1. Owner-keyed image storage

- **Decision**: `ImageStorage.save_image(file_content, content_type, owner_id, original_filename=None, owner_type="products")`.
  `owner_type` is validated against `OWNER_TYPES = ("products", "ideas", "generations")`;
  the directory is `{owner_type}/{owner_id}`. The positional/keyword `product_id` argument
  is kept as a deprecated alias for `owner_id` so the four existing call sites
  (product upload, product import-url, onboarding logo, 3MF model thumbnail) keep working
  unchanged and still write to `products/…`. A new helper
  `copy_image(source_url, owner_type, owner_id)` reads an existing stored image
  (`get_image`) and saves it for another owner, so conversion copies files through the
  same validation and thumbnailing.
- **Rationale**: backward compatible (FR-021, SC-007): no product URL changes, and a test
  pins the exact `products/{id}/…` path. `generations` is accepted now so 008 needs no
  change to the storage API.
- **Alternatives**: a second storage class for ideas (duplicates thumbnails, size limits,
  S3 split — rejected, principle III spirit); moving model thumbnails and the tenant logo
  out of `products/` (breaks existing URLs — rejected, out of scope).

## R2. Serving idea images only to signed-in members (clarification Q1)

- **Decision — Deviation from architecture §3**: the architecture had `/uploads/{owner_type}/{owner_id}/{filename}`
  serve every owner type publicly. Clarification Q1 decided that idea images go only to a
  signed-in user of the owning shop. So `main.py` keeps its public route for
  `/uploads/products/...` exactly as it is, and **no public route is added for `ideas`**.
  Idea images are served by an authenticated endpoint
  `GET /api/v1/ideas/{idea_id}/entries/{entry_id}/image?variant=full|thumb`
  (`CurrentTenant` + `TenantDB`, viewer role and above). A missing or invalid token gives 401,
  and an entry of another shop gives 404. The stored `image_url` stays the storage key
  (`/uploads/ideas/{idea_id}/{file}`), which no route serves publicly. API responses give the
  authenticated path in `image_path` / `thumbnail_path`.
- **Frontend**: an `<AuthImage>` component fetches the path with the authenticated axios
  client as a blob, shows it through `URL.createObjectURL`, and revokes it on unmount.
  TanStack Query caches the blobs, keyed by path.
- **Rationale**: an `<img src>` cannot send the bearer token. A blob fetch is the smallest
  change and keeps one auth mechanism. Response headers: `Cache-Control: private, max-age=3600`,
  so no shared cache keeps the image.
- **Alternatives**: signed short-lived URLs (rejected by the user in Q1, option C; also a
  new signing secret); a cookie-based session for images (no such session exists — JWT only).
- **For 008**: generated images stored under `generations/` will need their own access
  decision. The storage API already accepts the owner type. An image adopted into an idea
  is copied under `ideas/` and inherits this route.

## R3. Product and model creation services (out-of-zone access granted, option a)

- **Decision**: move the bodies of `create_product` (`api/v1/products.py`) and
  `create_model` (`api/v1/models.py`) without behaviour change into
  `services/product_creation.py::create_product(db, tenant, user, data) -> Product` and
  `services/model_creation.py::create_model(db, tenant, user, data) -> Model`. They raise
  the same `HTTPException`s, call `refuse_observed_or_409` / `_authorise_model_write` and
  `record_operator_origins` as before, and **flush without committing**. The routes call
  them, then commit and build the response as before. Idea conversion calls them in its
  own transaction and commits once.
- **Rationale**: FR-024/FR-026 (all-or-nothing) and principle III (one implementation of
  "create a product with its BOM lines"). The existing product and model test suites
  guard the "no behaviour change".
- **Alternatives**: calling the route functions (they commit, so not atomic); copying their
  logic (a second implementation — principle III violation).
- **Scope note**: `_authorise_model_write` stays in `models.py`, and the service imports it
  lazily to avoid a cycle. If the import cycle bites, it moves to the service with a
  re-export in `models.py`.

## R4. Total score: one implementation, computed on read (FR-004, FR-004a, clarification Q3)

- **Decision**: a SQLAlchemy `hybrid_property` `Idea.score` has a Python side and a SQL side
  defined together:
  `CASE WHEN all five scores NOT NULL THEN sum ELSE report_score END`. List sorting
  (`ORDER BY score DESC NULLS LAST`) and the response field both use it. The response also
  carries `score_source`: `"scores"`, `"report"` or `null`. `report_score` is written only on
  import or creation and is never recomputed by the system (principle VI).
- **Rationale**: principle III — the total lives in exactly one place, and principle V —
  nothing derived is stored.
- **Alternatives**: a stored `total_score` column (stale-figure risk, principle V); computing
  in the frontend (a second implementation).

## R5. Pain-point report import (clarification Q2)

- **Decision**: `POST /api/v1/ideas/import` takes a structured list (`items[]`), and agents and
  010 call it directly. `dry_run: true` returns the same classification without writing, which
  the screen uses for its preview. `POST /api/v1/ideas/import/parse-report` takes the
  markdown text and returns that `items[]` list plus parse warnings. The parser
  (`services/pain_point_report_parser.py`) reads `### N. <title> — <score>/25` headings
  under any `##` section ("Top 10", "Axe culturel …"), the `- Niche :` / `- Culture :` line
  as tag, the first markdown link of `- Preuves :` as `source_url`, and builds the summary
  from `Idée produit`, `Citation typique`, `Faisabilité impression`, `Etsy` and the evidence
  links. "Signaux faibles" and other sections without `###` problem headings are ignored.
- **Rationale**: a single parser on the backend serves the screen and any client, with no
  second parser in TypeScript. The structured list is the stable contract, and the markdown
  layout can change without breaking agents. The parse is tested against a fixture copied
  from a real report (anonymised to its structure).
- **Dedupe**: for each item, the import skips a source link that matches an existing idea of
  the shop with `source = pain_point_report` (archived and converted ones included). A
  unique partial index `(tenant_id, source_url) WHERE source='pain_point_report' AND
  source_url IS NOT NULL` makes it hold under concurrency. Duplicates inside one payload
  are skipped after the first.
- **Alternatives**: parsing in the browser (two parsers if an agent ever sends markdown);
  JSON-only (rejected in Q2).

## R6. Conversion flow

- **Decision**: `IdeaService.convert(idea, target, payload)` runs inside one transaction:
  1. refuse if the idea is archived, or if it is already converted to a product (409);
  2. model: reuse `converted_model_id` if set and the model still exists, else
     `create_model` with name, description, sku and `source_idea_id`;
  3. product (target product): `create_product` with `models=[{model_id, quantity: 1}]` and
     `source_idea_id`;
  4. images: copy the cover to the model's `image_url` (new model only) and, for a product,
     the cover entry plus the pinned image/sketch entries (cover first, `is_primary`, no duplicate) into `ProductImage` rows through
     `ImageStorage.copy_image(owner_type="products")`;
  5. set `converted_model_id` / `converted_product_id` and `status = converted`, then commit.
  On any exception: roll back, best-effort delete of the files already copied, then re-raise.
  Copy failures of single missing files are collected as `warnings` and do not abort
  (spec edge case "file missing from storage").
- **SKU defaults**: the dialog prefills from the existing `GET /api/v1/sku/next/{entity}`
  (PROD / MOD). A taken SKU makes the creation services raise 400, which conversion passes
  through unchanged and leaves nothing behind.
- **Alternatives**: background job (overkill for 2 inserts + a few image copies).

## R7. Module registration

- **Decision**: module `ideas` (icon `lightbulb`, `MODULE_ORDER` 11 — appended so no other module's value changes in this shared file). It goes in
  `ALL_MODULES` and `DEFAULT_MODULES_BY_TYPE[three_d_print]`, with a `MODULE_NAVIGATION`
  entry `/ideas` and a `MODULE_ORDER` value, and is registered as `IdeasModule` in
  `app/modules/threed_print/ideas.py` and `threed_print/__init__.py`. The registry is the
  source of `/api/v1/modules`; without it the module never shows. Existing 3D-print tenants
  get it automatically: `get_enabled_modules` falls back to the type defaults for a module
  that has no row yet. `tenant_types = [THREE_D_PRINT, GENERIC]` so other shop types can
  enable it (FR-001).
- **Note**: the module registry files (`app/modules/threed_print/ideas.py`, `__init__.py`)
  fall under "module registration" in the zone. They are listed in the hand-over report.

## R8. Roles

- **Decision**: reads need `CurrentUser` + `CurrentTenant` (viewer and above), and writes add
  `RequireMember`, as `model_file_notes` does (FR-002). Conversion also needs `RequireMember`,
  because `create_model` requires member. `create_product` requires admin today; the
  conversion service checks the role `create_product` needs (admin) when the target is a
  product, so conversion grants no more than the products screen.

## R9. Board pagination

- **Decision**: one list endpoint (`GET /ideas`) with `status`, `tag`, `source`, `search`,
  `archived`, `sort`, `skip`, `limit` (≤100) returns `{items, total}`. The board issues one
  query per status column (limit 20, "load more" increments skip) and shows `total` as the
  count. `GET /ideas/tags` returns the shop's distinct tags for the filter. Indexes:
  `(tenant_id, status, updated_at)`, a GIN index on `tags`, and the unique partial
  `source_url` index.
- **Search**: `ILIKE` on title and summary. Hundreds to a few thousand rows per tenant need
  no full-text index (SC-002, 500 ideas < 2 s).

## R10. Entry kinds and the generation link (FR-012, 008 hand-over)

- **Decision**: `idea_entries.kind` has a check constraint over
  `note, image, link, sketch, measurement, decision, generation`.
  `generation_job_id UUID NULL` is created **without a foreign key**: the `generation_jobs`
  table does not exist yet, and 008 adds the FK constraint in its own migration. The API
  refuses `kind = generation` on create (422). 008 creates such entries through its own
  service, which sets `generation_job_id`.
- **Departure from architecture §4 entry kinds**: `brief` is not added. A design brief is
  its own entity in 009 (`DesignBrief.idea_id`), not a timeline entry, so a `brief` kind
  would be an unused value. 009 can add it with a one-line constraint change if it wants a
  timeline marker.

## R11. Tags

- **Decision**: a JSONB array of strings, normalised on write: trimmed, lowercased,
  de-duplicated, ≤ 20 tags of ≤ 40 characters each. A GIN index makes the
  `tags @> '["car"]'` filter fast.
