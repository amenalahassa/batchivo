# Quickstart: validate Ideas (spec 007)

## Prerequisites

- Test DB (`docker-compose.test.yml`, port 5433) for pytest. Ask the orchestrator before running it.
- Backend on 8000 and Vite on 5173 serving this worktree for e2e. Ask the orchestrator first.
- `cd backend && poetry run alembic upgrade head` on the dev DB. `poetry run alembic heads` shows one head.

## Automated checks

```powershell
cd backend; poetry run pytest tests/api/test_ideas_api.py tests/api/test_ideas_entries_api.py tests/api/test_ideas_convert_api.py tests/api/test_ideas_import_api.py tests/api/test_modules_ideas_route.py tests/unit/test_idea_models.py tests/unit/test_creation_services.py tests/unit/test_pain_point_report_parser.py tests/unit/test_image_storage_owner_keyed.py tests/services/test_pain_point_report_parser.py tests/services/test_image_storage_owner_keyed.py tests/services/test_product_creation.py tests/services/test_model_creation.py tests/models/test_idea_models.py tests/api/test_modules_ideas_route.py
```

```powershell
cd backend; poetry run ruff check; poetry run ruff format --check
```

```powershell
cd frontend; npm run test:run; npm run lint; npm run typecheck
```

```powershell
cd frontend; npm run test:e2e -- e2e/tests/ideas e2e/tests/models e2e/tests/products --project=chromium --reporter=list
```

## Manual scenarios (map to spec stories)

1. **Capture (US1)**: sign in as a 3D-print shop. "Ideas" is in the navigation. Create
   "Sun visor clip" with scores 4/5/3/4/2. It appears in Inbox with 18/25. Move it to Exploring,
   then find it in the list by "visor", by tag, and first when sorted by score.
2. **Timeline (US2)**: on the idea, add a note in markdown. Select two images at once and paste
   a third. Add a link and a decision. Start iteration 2 with a note and add an image. The
   timeline groups entries under Iteration 2 and Iteration 1, the gallery shows 4 images, the
   pinned entry is first, and the cover shows on the board card.
3. **Private images (Q1)**: copy an image path from the network tab and open it in a private
   window. It is refused (401). Signed in as another shop, it is "not found" (404).
4. **Convert (US3)**: pin two images and convert to a product. A model and a product exist,
   the BOM holds 1× the model, the product has 2 images (cover primary), the idea is Converted
   with both links, and the model and product pages show "From idea: Sun visor clip". Convert
   again: refused, with a link to the product instead.
5. **Import (US4)**: open "Import report" and drop a pain-point report `.md`. The preview lists
   each problem with its report score, niche and first evidence link. Confirm to create N
   ideas. Import again: 0 created, N skipped.
6. **No regression**: an existing product image opens at its old `/uploads/products/...`
   address. Creating a model or product from their own screens works as before.
