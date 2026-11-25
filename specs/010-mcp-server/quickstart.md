# Quickstart / validation: Batchivo MCP Server (010)

## Prerequisites

- A disposable stack of this worktree (not the orchestrator's 5433/8000/5173): its own Postgres
  container, backend and Vite on free ports, backend started with `E2E_TEST_HOOKS_ENABLED=true`.
- `cd backend && poetry install` (pulls the `mcp` SDK).

## Gates

```text
cd backend && poetry run pytest tests/api/test_api_tokens.py tests/unit/test_api_token_auth.py tests/mcp_server
cd backend && poetry run pytest            # full suite: existing auth tests unchanged (SC-006)
cd backend && poetry run ruff check && poetry run ruff format --check
cd frontend && npm run test:run && npm run lint && npm run typecheck
cd frontend && npm run test:e2e -- e2e/tests/settings --project=chromium --reporter=list
cd backend && poetry run alembic heads     # one head: api_tokens_v1 (or re-pointed on 008's)
```

## Scenario 1 — token lifecycle (US1)

1. Sign in, Settings → API tokens → Create: name "Agent", read + write, 90 days.
2. The secret `bvt_…` shows once with Copy; close: the list shows `bvt_xxxxxxxx`, read · write,
   expiry, "Never used", Active. Reload: no secret anywhere.
3. `curl -H "Authorization: Bearer <secret>" <api>/api/v1/ideas` → 200; list now shows a last use.
4. `curl -X POST … /api/v1/ideas -d '{"title":""}'` → 422 (same message as the web form).
5. `curl … /api/v1/users/me` → 403 "This endpoint does not accept API tokens".
6. Revoke → the same GET → 401; list shows Revoked.

## Scenario 2 — Claude Code (US2, US5)

`.mcp.json` in the modelling workspace (see `docs-site/docs/mcp.md`):

```json
{
  "mcpServers": {
    "batchivo": {
      "command": "poetry",
      "args": ["-C", "/path/to/batchivo/backend", "run", "python", "-m", "app.mcp_server"],
      "env": {
        "BATCHIVO_API_URL": "http://localhost:8000",
        "BATCHIVO_API_TOKEN": "${BATCHIVO_API_TOKEN}"
      }
    }
  }
}
```

Expected: Claude Code lists `list_ideas`, `get_idea`, …; with a read-only token no write or
print tool is listed; "list my ideas tagged kitchen" returns the same ideas as the web list.

## Scenario 3 — print (US4)

With a token having `print`: `prepare_print` returns the summary and warnings; Claude Code asks
before `confirm_print` (destructive); confirming without `acknowledge_warnings` on a summary with
warnings → error from the API, no print.

## Expected failures

- Token missing from env → server exits 2 naming `BATCHIVO_API_TOKEN`, prints no token.
- API down → each tool returns "Batchivo could not be reached at …"; the server keeps running.
