# Quickstart: validating 008 Generative AI

The real Replicate API is never called. Tests mock it with respx, and the local/e2e stack points
the provider at the built-in fake (`GENAI_PROVIDER_BASE_URL`, test hooks only). No real token is
used and nothing is spent.

## 1. Backend gates

```bash
cd backend
poetry run alembic upgrade head && poetry run alembic heads   # exactly one head: genai_v1
poetry run pytest tests/genai tests/integration/test_genai_migration.py -q   # backend/tests/genai/, backend/tests/integration/test_genai_migration.py
poetry run pytest -q                                          # full suite
poetry run ruff check && poetry run ruff format --check
```

The genai tests must show:

- validation per capability;
- budget refusal and concurrency refusal, with no provider call made (respx call count 0);
- the polling path: queued → running → succeeded, with outputs stored and cost `computed`;
- the webhook path: a valid signature completes the job; invalid, stale or missing signatures
  give 401 and change nothing; a duplicate webhook is a no-op;
- provider failure, timeout (deadline passed → canceled at the provider, failed `timeout`) and
  download failure (job failed, no orphan file);
- adoption into an idea, a product (AI badge; warning `needs_confirmation` for a concept image)
  and a model (an inactive "AI draft" version whose dimensions stay unchanged);
- idea conversion carrying adopted 3D drafts;
- endpoints: 200/201, 401, 403 (viewer), 404, 422;
- the token never appears in a response or in a log record.

## 2. Frontend gates

```bash
cd frontend
npm run test:run && npm run lint && npm run typecheck
```

## 3. Manual walkthrough (own disposable stack, never ports 8000/5173/5433)

1. Start Postgres in a throwaway container on another port, and run the backend on port 8008
   with `E2E_TEST_HOOKS_ENABLED=true GENAI_RUN_INLINE=true GENAI_PROVIDER_BASE_URL=http://localhost:8008/api/v1/genai/e2e-fake`.
   Run Vite on port 5178, proxied to 8008.
2. Register a test account (`registerAndLogin` flow).
3. Settings → AI: save the token `r8_fake_e2e_token`.
   - The page shows `…oken` masked, and Test connection reports the fake account.
   - Set the budget to `1.00`.
4. Ideas → new idea → Generate concept.
   - The prompt is prefilled and an estimated cost is shown.
   - Start the job: it shows queued, running, then a result grid.
   - Adopt one image: a generation entry appears on the timeline.
5. On an image entry, choose Draft 3D shape and adopt the mesh: the entry shows the 3D viewer
   and a download button.
   - Convert the idea to a model: the model has an inactive "AI draft" version.
6. Product → Images: remove the background of a photo and adopt the result.
   - The new image has the AI badge and the original is unchanged.
   - Adopting a concept image shows the warning first.
7. Set the budget to `0.00` and start a job: it is refused, naming the budget and the spend.

## 4. Targeted e2e

From `frontend/`:

```bash
npm run test:e2e -- e2e/tests/genai e2e/tests/ideas e2e/tests/models e2e/tests/products --project=chromium --reporter=list
```

The backend must run with `E2E_TEST_HOOKS_ENABLED=true`; a skipped test is not a pass.
