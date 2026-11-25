# Implementation Plan: Ideas — capture, brainstorm and iterate, then convert to a model or product

**Branch**: `claude/007-ideas-268028` (spec dir `007-ideas`) | **Date**: 2026-11-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-ideas/spec.md`; architecture
`docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §3, §4, §9.

## Summary

A new tenant-scoped **Ideas** module: ideas with status, source, tags, five scores and an
optional report score; a timeline of polymorphic entries grouped by iteration (notes, images,
links, sketches, measurements, decisions; `generation` reserved for 008); image upload through
an owner-keyed generalisation of `ImageStorage`, served to signed-in members only; conversion to a model
or product through creation services extracted (without behaviour change) from the existing
routes, in a single transaction; bulk import from a structured list or from the pain-point
markdown report with a preview. Frontend: board + list (`/ideas`), detail with timeline,
composer, gallery and convert dialog (`/ideas/$ideaId`), "From idea" link on model and product
pages.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript 5.9 / React 19 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, Pillow, boto3
(existing `ImageStorage`); TanStack Router/Query, shadcn/ui, `react-markdown` + `remark-gfm`
(already dependencies), lucide-react

**Storage**: PostgreSQL (2 new tables with RLS, 2 nullable columns); images local/S3 via
`ImageStorage` under `ideas/{idea_id}/`

**Testing**: pytest (+ moto S3 for storage), Vitest + Testing Library, Playwright (targeted
e2e `e2e/tests/ideas/`)

**Target Platform**: Linux server (k3s) and single-tenant VPS bundle; modern browsers

**Project Type**: web application (backend + frontend)

**Performance Goals**: 500 ideas per tenant — first page of board columns / list / filtered
search < 2 s (SC-002); never loads all ideas

**Constraints**: no breaking change to models/products APIs or product image URLs; tenant
isolation by RLS + `tenant_id` filter; 10 MB per image; idea images never public

**Scale/Scope**: hundreds to low thousands of ideas per tenant, tens of entries per idea;
16 endpoints, 2 pages, ~10 components

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | How the design complies | Status |
|---|---|---|
| I. Multi-tenant isolation | `ideas`, `idea_entries` carry `tenant_id` with ENABLE/FORCE RLS + policy in the migration; every endpoint uses `CurrentTenant` + `TenantDB`; services also filter by `tenant_id`; image endpoint resolves the entry through the tenant-scoped idea; import dedupe is per tenant; tests for cross-tenant 404 on every resource | PASS |
| II. Tests ship with the change | Each endpoint: 200/201, 401, 404, 422 (+403 viewer); service tests for score, iteration, cover, import, conversion rollback; migration CRUD/constraints; storage path regression; frontend component + hook tests; targeted e2e | PASS |
| III. One implementation per calculation | Score total = one hybrid property used for sort and response (R4); product/model creation moved into one service each, used by the routes and by conversion (R3); report parsing in one backend parser (R5) | PASS |
| IV. Money exact / settings honoured | No money in this feature. Scores are small integers | N/A |
| V. Derived figures expire | Total score computed on read; nothing derived stored (`report_score` is an input with provenance, not a derivation) | PASS |
| VI. History immutable, provenance visible | `report_score` written once and shown as "report score"; entries record author and `edited_at`; archive instead of delete; conversion links kept when status changes | PASS |
| VII. Pipeline-only deployment | No deploy step; commit on the worktree branch, never pushed | PASS |
| Additional: Alembic, fresh DB reaches head | One new revision on `catalogue_columns_v1`; downgrade drops what it adds; `alembic heads` single head checked before commit | PASS |

No violations → Complexity Tracking empty.

## Project Structure

### Documentation (this feature)

```text
specs/007-ideas/
├── plan.md              # this file
├── research.md          # decisions R1–R11 (incl. deviations from the architecture)
├── data-model.md        # tables, constraints, transitions, storage layout
├── quickstart.md        # validation scenarios
├── contracts/
│   └── ideas-api.md     # REST contract
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code

```text
backend/
├── alembic/versions/20261123_ideas.py                 # new: tables, RLS, source_idea_id
├── app/models/idea.py                                 # new: Idea, IdeaEntry (+ constants)
├── app/models/__init__.py                             # register Idea, IdeaEntry
├── app/models/model.py, app/models/product.py         # + source_idea_id
├── app/schemas/idea.py                                # new
├── app/schemas/model.py, app/schemas/product.py       # + source_idea_id/title on responses (granted)
├── app/services/idea_service.py                       # new: CRUD, timeline, iterations, cover, import, convert
├── app/services/pain_point_report_parser.py           # new: markdown report → ImportItem list
├── app/services/image_storage.py                      # owner_type/owner_id, copy_image
├── app/services/model_creation.py                     # new: extracted from api/v1/models.py (granted)
├── app/services/product_creation.py                   # new: extracted from api/v1/products.py (granted)
├── app/api/v1/ideas.py                                # new router
├── app/api/v1/models.py, app/api/v1/products.py       # create route → service; response + source idea (granted)
├── app/api/v1/modules.py                              # MODULE_NAVIGATION, MODULE_ORDER
├── app/services/tenant_module_service.py              # ALL_MODULES, DEFAULT_MODULES_BY_TYPE
├── app/modules/threed_print/ideas.py, __init__.py     # IdeasModule registration
├── app/main.py                                        # include ideas router (uploads route untouched)
└── tests/
    ├── api/test_ideas_api.py, test_ideas_entries_api.py, test_ideas_convert_api.py, test_ideas_import_api.py
    ├── api/test_modules_ideas_route.py
    ├── services/test_idea_service.py, test_pain_point_report_parser.py
    ├── services/test_image_storage_owner_keyed.py
    ├── services/test_product_creation.py, test_model_creation.py
    ├── fixtures/pain_point_report_sample.md
    └── models/test_idea_models.py

frontend/src/
├── types/idea.ts                                      # new
├── lib/api/ideas.ts                                   # new
├── hooks/useIdeas.ts                                  # new
├── components/ideas/
│   ├── IdeaBoard.tsx, IdeaList.tsx, IdeaCard.tsx, IdeaFilters.tsx
│   ├── IdeaForm.tsx (create/edit header incl. ScoreInput)
│   ├── IdeaHeader.tsx, IdeaTimeline.tsx, IdeaEntryItem.tsx, IdeaComposer.tsx
│   ├── IdeaGallery.tsx, ConvertIdeaDialog.tsx, ImportReportDialog.tsx
│   ├── AuthImage.tsx, Markdown.tsx, ideaText.ts (labels)
│   └── *.test.tsx
├── pages/Ideas.tsx, pages/IdeaDetailPage.tsx           # new
├── App.tsx                                            # + /ideas, /ideas/$ideaId (ModuleGuard)
├── components/layout/AppLayout.tsx                    # ICON_COMPONENTS: lightbulb
├── lib/api/models.ts, lib/api/products.ts             # + source_idea_id/title (granted)
├── components/models/ModelDetail.tsx, components/products/ProductDetail.tsx  # "From idea" link (granted)
└── e2e/tests/ideas/ideas.spec.ts (under frontend/)
```

**Structure Decision**: existing web-app layout (`backend/app`, `frontend/src`); the Ideas
code follows the model-file-notes trio (router → service class → schemas) and the frontend
`lib/api` + `hooks` + `components` pattern.

## Design notes

### Backend

- `IdeaService(db, tenant, user)` holds all business rules. The router stays thin. Methods:
  `list`, `tags`, `create`, `get`, `update`, `archive`, `list_entries`, `add_entry`,
  `add_images`, `update_entry`, `archive_entry`, `open_image`, `start_iteration`, `convert`,
  `import_items`.
- Every write bumps `idea.updated_at` explicitly. A new entry also counts as an update of the
  idea, so the board's "last updated" reflects brainstorming activity.
- Image upload reads each `UploadFile` (≤10 files per request) and calls
  `ImageStorage.save_image(owner_type="ideas", owner_id=idea.id)`. An `ImageStorageError`
  goes into `refused` and the other files continue.
- Conversion and storage compensation are described in research R6. The conversion service
  checks the admin role for a product target through `role_in_tenant`, matching
  `create_product`'s `RequireAdmin`.
- The image endpoint returns `Response(content, media_type, headers={"Cache-Control":
  "private, max-age=3600", "ETag": entry.id+variant})`.

### Frontend

- `/ideas`: `Ideas.tsx` has a Board/List toggle stored in the URL search (`?view=list`) and
  falls back to `useState` if `useSearch` is mocked.
  - `IdeaBoard`: one `useIdeas({status, limit:20, skip})` query per column, with a "Load more"
    button and a count from `total`.
  - `IdeaList`: a table with search (debounced 300 ms), status/tag/source/archived filters,
    sort, and page buttons following the `ModelList` pattern.
  - "New idea" opens `IdeaForm` in a dialog, and "Import report" opens `ImportReportDialog`.
- `/ideas/$ideaId`: `IdeaDetailPage` contains `IdeaHeader` (inline edit, status select
  without "converted", scores, tags, links to the model/product, Convert button) and tabs
  Timeline | Gallery.
  - `IdeaComposer` takes a note, link, measurement or decision, plus a file picker
    (`multiple`). It also handles drop on the page area and `onPaste` (image files go to
    upload, text goes to the note field).
  - "Start next iteration" asks for an optional note.
- `AuthImage` fetches through `apiClient.get(path, {responseType:'blob'})` with a TanStack
  Query key `['idea-image', path]` and `staleTime: Infinity`. It shows the image through an
  object URL that is revoked on unmount, plus a skeleton while loading and a "missing image"
  placeholder on 404.
- `Markdown` wraps `react-markdown` + `remark-gfm` without `rehype-raw`, so raw HTML is not
  rendered (XSS-safe by default). Links open with `rel="noopener noreferrer"`.
- `ConvertIdeaDialog` prefills the name from the title and the SKUs from `useNextSKU('MOD')`
  and `useNextSKU('PROD')`, with an "include images" checkbox. On success it shows links to
  the new model and product.
- `ImportReportDialog` has two steps:
  1. Paste or drop the `.md` file, call `parse-report`, then `import` with `dry_run`, and show
     the preview table (to create, to skip, refused).
  2. Confirm, call `import`, and show the result counts.

## What later features will find (hand-over)

- **008 Generative AI**:
  - `idea_entries.kind` already accepts `generation`, and `generation_job_id UUID NULL` exists
    with no FK. 008 adds the FK in its migration, plus the creation path (the 007 API refuses
    `kind=generation` from clients).
  - `ImageStorage.save_image(..., owner_type="generations", owner_id=job_id)` and
    `copy_image(source_url, owner_type, owner_id)` are ready. Adopting an output into an idea
    copies it under `ideas/{idea_id}/` and creates an entry, so the authenticated image
    endpoint serves it with no change.
  - The idea detail page keeps the composer's action bar open for a "Generate" button.
    `IdeaComposer` takes an `extraActions` slot.
- **009 Preflight**: a design brief references `ideas.id`. To move the brief to the model,
  009 adds one step to `IdeaService.convert`, inside the transaction, after the model id is
  known. A `brief` entry kind was not added (research R10).
- **010 MCP server**: every operation is on the REST API in `contracts/ideas-api.md`. The
  import takes the structured `items[]` list, as an agent would send it, and `parse-report`
  lets an agent hand over the raw report. Idea images need the bearer token, so 010 uses its
  API token on the image endpoint.

## Complexity Tracking

None.
