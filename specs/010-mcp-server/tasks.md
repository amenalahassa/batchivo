# Tasks: Batchivo MCP Server for AI Agents

**Input**: Design documents from `specs/010-mcp-server/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api-tokens-api.md, contracts/mcp-tools.md, quickstart.md

**Tests**: required (Constitution II, spec SC-002..SC-006). Write each story's tests first and see
them fail before implementing.

## Format: `[ID] [P?] [Story] Description`

---

## Phase 1: Setup

- [X] T001 Add the official MCP Python SDK `mcp` to `[project].dependencies` in `backend/pyproject.toml` and refresh `backend/poetry.lock` with `poetry lock` + `poetry install`; record the resolved version in `specs/010-mcp-server/research.md` R11
- [X] T002 [P] Create package skeleton `backend/app/mcp_server/__init__.py`, `backend/app/mcp_server/tools/__init__.py` and test package `backend/tests/mcp_server/__init__.py` (empty modules with docstrings)

---

## Phase 2: Foundational (blocks all stories)

- [X] T003 [P] Create `ApiToken` model in `backend/app/models/api_token.py` per data-model.md: `tenant_id` UUID FK `tenants.id` ON DELETE CASCADE NOT NULL indexed; `user_id` UUID FK `users.id` ON DELETE CASCADE NOT NULL indexed; `name` VARCHAR(100) NOT NULL with `CHECK (char_length(trim(name)) BETWEEN 1 AND 100)` named `ck_api_tokens_name_length`; `token_prefix` VARCHAR(12) NOT NULL; `token_hash` CHAR(64) NOT NULL UNIQUE; `scopes` JSON NOT NULL; `expires_at` TIMESTAMPTZ NOT NULL; `last_used_at` and `revoked_at` TIMESTAMPTZ NULL; index `ix_api_tokens_tenant_user` on `(tenant_id, user_id, created_at)`; `UUIDMixin`, `TimestampMixin`; relationships `user`, `tenant` without back-references
- [X] T004 Register the model with one added import line in `backend/app/models/__init__.py` (shared file: add only, do not reorder)
- [X] T005 Write migration `backend/alembic/versions/20261124_api_tokens.py`, `revision = "api_tokens_v1"`, `down_revision = "print_sends_v1"`: create the table, constraint and indexes of T003; `ENABLE` + `FORCE ROW LEVEL SECURITY`; policies `tenant_isolation_select` and `tenant_isolation_update` `USING (<tenant> OR token_hash = NULLIF(current_setting('app.current_api_token_hash', true), ''))`, `tenant_isolation_insert` `WITH CHECK (<tenant>)`, `tenant_isolation_delete` `USING (<tenant>)`, with `<tenant>` copied from `20261123_print_sends.py`; downgrade drops policies, indexes, table; verify `poetry run alembic heads` shows one head
- [X] T006 [P] Create schemas in `backend/app/schemas/api_token.py` per contracts/api-tokens-api.md: `ApiTokenScope = Literal["read","write","genai","print"]`; `ApiTokenCreate` (name stripped 1..100; scopes min 1, deduplicated and sorted; `expires_at` timezone-aware with `now < expires_at <= now + 365 days`, else 422); `ApiTokenResponse` (with derived `status`), `ApiTokenCreated` (+ `token`), `ApiTokenListResponse`, `ApiTokenCurrent`
- [X] T007 [P] RLS test `backend/tests/integration/test_rls_api_tokens.py` in the style of `test_rls_enforced.py` (database from migrations, app as `app_user`, skipped without PostgreSQL): a token of tenant A authenticates and reads A's ideas; tenant B's tokens are invisible to A's `GET /api-tokens`; a token row is not readable without its hash or its tenant set; `test_every_tenant_table_has_rls.py` passes with the new table
- [X] T008 [P] Model tests in `backend/tests/unit/test_api_token_model.py`: create/read/update `last_used_at`/`revoked_at`, unique `token_hash`, name check constraint, cascade on user and tenant delete, relationships

**Checkpoint**: table, model, schemas exist; `alembic upgrade head` reaches `api_tokens_v1` on a fresh database.

---

## Phase 3: User Story 1 - Create, see and revoke a personal API token (P1) 🎯 MVP

**Goal**: operator manages tokens in Settings; a token authenticates on allowlisted endpoints only, within its scopes, tenant and its owner's role; JWT unchanged.

**Independent test**: create a read token, its secret is shown once; read endpoint 200, write endpoint 403 (scope), `/users/me` 403 (not accepted), revoke, read endpoint 401.

### Tests (write first)

- [X] T009 [P] [US1] Service tests in `backend/tests/unit/test_api_token_service.py`: generated token matches `^bvt_[a-z2-7]{8}_[A-Za-z0-9_-]{43}$`, prefix = first 12 chars, only sha256 hash stored, `status_of` (active/expired/revoked), revoke idempotent and `revoked_at` never cleared, list returns only the caller's tokens in the caller's tenant, newest first
- [X] T010 [P] [US1] Endpoint tests in `backend/tests/api/test_api_tokens.py`: POST 201 returns `token` once and GET list never contains it (FR-002); two tokens with the same name both created; POST 422 for empty name, name > 100, no scope, unknown scope, missing expiry, past expiry, expiry > 365 days; GET 200 own tokens only (second user of the same tenant sees none of the first's, FR-003); revoke 200 + idempotent, 404 for unknown id and for another user's token, 422 bad UUID; all four routes 401 without auth; management routes 403 when called with a token (FR-008); `GET /api-tokens/current` 200 with a token and 403 with a JWT
- [X] T011 [P] [US1] Auth-path tests in `backend/tests/unit/test_api_token_auth.py` using the real dependencies (no `get_current_user` override; `unauthenticated_client`): valid read token on `GET /api/v1/ideas` 200; unknown, revoked, expired token → 401 with identical detail `Invalid or expired API token` and `WWW-Authenticate: Bearer`; owner deactivated → 401; owner removed from the tenant → 401; endpoint absent from the table (`GET /api/v1/users/me`, `GET /api/v1/users/me` under `/users`, a route of `settings.py`, `DELETE /api/v1/ideas/{id}`) → 403 `This endpoint does not accept API tokens`; read-only token on `POST /api/v1/ideas` → 403 naming `write`; write-only token on `GET /api/v1/ideas` → 403 naming `read` (SC-002, scopes independent); idea entry image of another tenant with a token → 404; token with `write` but viewer role → 403 from the role check (FR-005); `X-Tenant-ID` of another tenant → 403; ideas of another tenant → 404 (US2 scenario 3); `last_used_at` set on first use and not rewritten within 60 s (FR-009); with RLS disabled (the production setting) a token of tenant A never resolves to tenant B: tenant B's data is 404, `X-Tenant-ID: B` is 403, a token whose `token_prefix` matches but whose secret differs is 401 (validation conditions 1 and 2)
- [X] T012 [P] [US1] JWT regression and secrecy tests in `backend/tests/unit/test_api_token_auth.py`: a JWT still authenticates on allowlisted and non-allowlisted routes exactly as before; a `bvt_` value is never passed to `decode_token` (patch and assert not called); a JWT-shaped value never triggers a token lookup; `caplog` + captured stderr over create, use, refused and revoke paths never contain the secret (FR-010, SC-004)
- [X] T013 [P] [US1] Policy drift tests in `backend/tests/unit/test_api_token_policy.py`: every `(method, endpoint)` key of `TOKEN_ROUTE_SCOPES` resolves to a live route of `app.main.app` (walk `app.openapi()` operations and the routers' endpoints); every scope value is one of `read|write|genai|print|any`; no key belongs to the forbidden families of contracts/api-tokens-api.md (auth, users, tenant members, api-tokens management, settings, payments, platform, shop, onboarding, test) and no DELETE

### Implementation

- [X] T014 [US1] Implement `ApiTokenService` in `backend/app/services/api_token_service.py`: `generate_token()`, `hash_token()`, `create(db, tenant, user, data) -> (ApiToken, secret)`, `list_for_user(db, tenant, user)`, `revoke(db, tenant, user, token_id)`, `status_of(token, now)`; logs only id and `token_prefix`
- [X] T015 [US1] Create the policy table in `backend/app/auth/api_token_policy.py`: `TOKEN_ROUTE_SCOPES: dict[tuple[str, str], str]` keyed by `(method, f"{endpoint.__module__}.{endpoint.__qualname__}")` with every row of contracts/api-tokens-api.md §Policy table (find each endpoint's function name in its router), plus `required_scope(method, endpoint) -> str | None`
- [X] T016 [US1] Implement `authenticate_api_token(request, db, raw)` and `ApiTokenContext` in `backend/app/auth/api_tokens.py` per plan §Authentication design step 2: hash, `set_config('app.current_api_token_hash', hash, true)` (no-op when RLS is off), lookup `WHERE token_hash = :hash` exact on the indexed column (never by prefix), then `hmac.compare_digest`, 401 cases, policy 403s from `request.scope["endpoint"]`, throttled `last_used_at` UPDATE, `request.state.api_token`, `set_rls_context(db, user_id=...)`
- [X] T017 [US1] Add the single `bvt_` branch to `get_current_user` and the token-tenant branch to `get_current_tenant` in `backend/app/auth/dependencies.py` (both gain `request: Request`; JWT code below the branch unchanged; plan §Authentication design steps 1 and 3)
- [X] T018 [US1] Implement router `backend/app/api/v1/api_tokens.py` (GET list, POST create 201, POST `/{token_id}/revoke`, GET `/current` token-only) with `CurrentUser`, `CurrentTenant`, `TenantDB`; declare `GET /current` in the policy table with scope `any`
- [X] T019 [US1] Mount the router with one added line in `backend/app/main.py`: prefix `{settings.api_v1_prefix}/api-tokens`, tag `api-tokens` (shared file: add only)
- [X] T020 [P] [US1] Frontend types and client: `frontend/src/types/apiToken.ts` (mirrors the schemas), `frontend/src/lib/api/apiTokens.ts` (`apiTokensApi.list/create/revoke`)
- [X] T021 [P] [US1] Hook `frontend/src/hooks/useApiTokens.ts` returning `{ tokens, isLoading, createToken, revokeToken }` with TanStack Query and list invalidation
- [X] T022 [US1] Component `frontend/src/components/settings/ApiTokensSettings.tsx`: list (name, `token_prefix`, scopes, created, expiry, last used or "Never used", status badge), Create dialog (name 1..100, scope checkboxes with `read` pre-ticked and `print` never pre-ticked, expiry select 30/90/365 days or custom date bounded today+1..today+364), one-time secret dialog with Copy and "will not be shown again" warning that drops the secret from state on close, Revoke with confirmation dialog
- [X] T023 [US1] Component tests `frontend/src/components/settings/ApiTokensSettings.test.tsx`: list rendering incl. statuses, create validation (empty name, no scope), `print` unticked by default, secret shown once then gone after close, revoke confirmation calls the API
- [X] T024 [US1] Add the "API tokens" tab (`KeyRound` icon, value `api-tokens`) to `frontend/src/pages/Settings.tsx`: one `TabsTrigger` and one `TabsContent` rendering `ApiTokensSettings`; other tabs untouched
- [X] T025 [US1] E2E journey `frontend/e2e/tests/settings/api-tokens.spec.ts` (registerAndLogin): open Settings → API tokens, create a read token, secret shown once, list row visible after closing, call `GET /api/v1/ideas` with the token through `request` → 200 and `GET /api/v1/users/me` → 403, revoke, same call → 401

**Checkpoint**: US1 independently testable (T009–T013, T023, T025 green).

---

## Phase 4: User Story 2 - An agent reads Batchivo data through MCP (P1)

**Goal**: the stdio MCP server, built from tool groups, lists only tools within the token's scopes and reads ideas, models/versions/notes, printers/AMS, spools, print jobs and runs through the API.

**Independent test**: against respx, each read tool sends the expected request with the bearer token and returns the API data; revoked token at startup → exit with "token refused"; API down → tool error, server alive.

### Tests (write first)

- [X] T026 [P] [US2] Fixtures in `backend/tests/mcp_server/conftest.py`: `api_url`, `token` (`bvt_…` test value), `mock_api` (respx router on `api_url`, `/api/v1/api-tokens/current` answering configurable scopes), `make_server(scopes)` building the FastMCP instance in-process, `call_tool(server, name, args)` helper
- [X] T027 [P] [US2] Startup/config tests in `backend/tests/mcp_server/test_config_and_startup.py`: missing/empty `BATCHIVO_API_URL` or `BATCHIVO_API_TOKEN` → exit code 2 with a message naming the variable and no token in output; 401 on `/api-tokens/current` → exit 2 "Batchivo refused the API token"; unreachable → exit 2 "could not be reached"; registered tool names equal the union of groups whose scope is held (read-only token: no write/print tool); `python -m app.mcp_server` subprocess import leaves `app.database`, `app.models`, `app.config` out of `sys.modules` (FR-013); masking filter rewrites `bvt_…` to `bvt_****` in stderr (FR-010)
- [X] T028 [P] [US2] Client tests in `backend/tests/mcp_server/test_client.py`: bearer header on every request; base URL join; 4xx/5xx → `"<status>: <detail>"`, 422 body flattened to `field: message` lines; `httpx.ConnectError`/timeout → "Batchivo could not be reached at <url>"; multipart upload from a local file path; image response → bytes + content type
- [X] T029 [P] [US2] Tool tests `backend/tests/mcp_server/test_tools_ideas_read.py` (list_ideas with every query param passed through, list_idea_tags, get_idea, list_idea_entries, get_idea_entry_image returns image content), `test_tools_models_read.py` (list_models, get_model, list_model_files, list_file_versions, list_file_notes with filters passthrough), `test_tools_printers.py`, `test_tools_spools.py`, `test_tools_production.py`, `test_tools_account.py`: request method/path/query, success payload, one API error path (404 → isError with detail) and annotations `readOnlyHint=True`
- [X] T030 [P] [US2] Coverage test `backend/tests/mcp_server/test_tool_coverage.py`: every tool of every group in `GROUPS` has a unique name, a scope in `read|write|genai|print|any`, annotations matching its kind, and appears in at least one test module of `backend/tests/mcp_server/` (SC-005)

### Implementation

- [X] T031 [US2] `backend/app/mcp_server/config.py`: read and validate `BATCHIVO_API_URL`/`BATCHIVO_API_TOKEN` (exit 2 with variable name), stderr logging with `SecretMaskingFilter` (`bvt_[A-Za-z0-9_-]+` → `bvt_****`), httpx logger at WARNING
- [X] T032 [US2] `backend/app/mcp_server/client.py`: `BatchivoClient` (httpx.AsyncClient, `get/post/patch/upload/get_bytes`), `BatchivoApiError(status, detail)` with 422 flattening, `BatchivoUnreachable(url)`
- [X] T033 [US2] `backend/app/mcp_server/tools/base.py`: `ToolSpec(name, description, scope, read_only, destructive, handler)` and helpers to turn results/errors into MCP content (`isError`); image content helper
- [X] T034 [US2] `backend/app/mcp_server/server.py` + `__main__.py`: fetch `/api-tokens/current`, build `FastMCP("batchivo")`, register tools of `GROUPS` whose scope is held (or `any`) with `ToolAnnotations`, run stdio; startup failures exit 2
- [X] T035 [P] [US2] Read tool groups per contracts/mcp-tools.md: `tools/account.py` (get_token_info), read tools of `tools/ideas.py` and `tools/models.py`, `tools/printers.py`, `tools/spools.py`, `tools/production.py`; register all in `tools/__init__.py` `GROUPS`

**Checkpoint**: US2 testable against respx; manual: Claude Code lists read tools with a read token.

---

## Phase 5: User Story 3 - An agent writes ideas, models and notes (P2)

**Goal**: write tools for ideas and notes, refused by the API without the write scope or role.

**Independent test**: respx: each write tool sends the right method and body; read-only token → tool not registered, and a direct API call is refused (T011).

- [X] T036 [P] [US3] Tool tests `backend/tests/mcp_server/test_tools_ideas_write.py` (create_idea, update_idea, add_idea_entry, upload_idea_image multipart from `tmp_path` file incl. missing-file error, update_idea_entry, add_idea_iteration, import_ideas, parse_idea_report, convert_idea) and `test_tools_models_write.py` (add_file_note, update_file_note incl. resolve, carry_forward_note; extra body fields passed through unchanged for 009): request shape, success, 422 surfaced with field messages, 403 scope message surfaced, annotations `readOnlyHint=False, destructiveHint=False`
- [X] T037 [US3] Implement write tools in `backend/app/mcp_server/tools/ideas.py` and `backend/app/mcp_server/tools/models.py` per contracts/mcp-tools.md; note tools accept an optional `extra_fields` dict merged into the body so later note fields (009) pass through

**Checkpoint**: US3 testable.

---

## Phase 6: User Story 5 - Set up the MCP server in Claude Code (P2)

**Goal**: operator documentation and a working `.mcp.json` example.

**Independent test**: follow `docs-site/docs/mcp.md` on a local stack; Claude Code lists the tools.

- [X] T038 [P] [US5] Write `docs-site/docs/mcp.md`: what the server does, creating a token and choosing scopes (print is separate and asks before starting), the `.mcp.json` entry with `${BATCHIVO_API_TOKEN}` from the environment, checking the tools are listed, troubleshooting (exit messages), revoking a lost token, the 1-year expiry
- [X] T039 [US5] Add the `mcp` entry after `ideas` in `docs-site/sidebars.ts` (label "MCP Server for AI Agents", title case like its siblings); `cd docs-site && npm run build` passes

**Checkpoint**: US5 done.

---

## Phase 7: User Story 4 - An agent prepares and starts a print (P3)

**Goal**: print tools on the 011 API, `confirm_print` destructive, warnings never acknowledged by default.

**Independent test**: respx: prepare returns summary + token; confirm sends `acknowledge_warnings: false` unless told; tools absent without `print` scope; API refusal surfaced.

- [X] T040 [P] [US4] Tool tests `backend/tests/mcp_server/test_tools_print_sends.py`: prepare_print with `model_file_id` and with `file_path` (multipart), plate and slot mapping fields; confirm_print default body `{"confirmation_token": …, "acknowledge_warnings": false}` and explicit true; 409/422 from the API surfaced; annotations (`confirm_print` `destructiveHint=True`); list_print_sends/get_print_send read; without `print` scope prepare/confirm not registered
- [X] T041 [US4] Implement `backend/app/mcp_server/tools/print_sends.py` per contracts/mcp-tools.md and add it to `GROUPS`; `prepare_print` description tells the agent to show the summary and warnings to the operator before confirming
- [X] T042 [US4] Auth tests for the print scope in `backend/tests/unit/test_api_token_auth.py`: a read+write token on `POST /printers/{id}/prints/prepare` and `/confirm` and consumption accept/dismiss → 403 naming `print`; a print token passes the scope check (the 011 endpoint then answers on its own terms, e.g. 404 for an unknown printer)

**Checkpoint**: all stories done.

---

## Phase 8: Polish & cross-cutting

- [X] T043 Update the status line of the 010 block in `specs/backlog.md` (own block only)
- [X] T044 [P] Run `cd backend && poetry run ruff check && poetry run ruff format --check` and `poetry run pytest` (full suite on a disposable Postgres of this worktree; SC-006); fix findings — targeted suites only (token, auth, API, RLS, model, MCP) per the orchestrator: the full suite runs on main at merge
- [X] T045 [P] Run `cd frontend && npm run test:run && npm run lint && npm run typecheck`; fix findings
- [X] T046 Run targeted e2e on a disposable stack with `E2E_TEST_HOOKS_ENABLED=true`: `npm run test:e2e -- e2e/tests/settings e2e/tests/auth --project=chromium --reporter=list`; report skips as not passing
- [X] T047 Validate quickstart.md scenarios 1 and 2 manually on the disposable stack (curl + `python -m app.mcp_server` with a real token over stdio listing tools)

---

## Dependencies & Execution Order

- Setup (T001–T002) → Foundational (T003–T008) → US1 (T009–T025).
- US2 needs US1's `/api-tokens/current` (T018) for startup; its tests run against respx, so T026–T035 can be written in parallel with US1 after T001.
- US3 needs US2's server and base (T031–T035). US4 needs US2 and the US1 policy table (T015). US5 needs US2 (docs describe the running server).
- Polish last.

## Parallel Examples

- After T006: T009, T010, T011, T012, T013 (separate test files) in parallel.
- US2 tests T026–T030 in parallel; read groups (T035) in parallel per file.
- Frontend T020, T021 in parallel with backend US1 work.

## Implementation Strategy

MVP = US1 (tokens usable by any script). Then US2 (agent reads) → US3 (agent writes) → US5 (docs) → US4 (print). Genai tools: only if 008 merges before convergence (then add `tools/genai.py` + tests + policy rows following contracts/mcp-tools.md §Extension pattern); otherwise left to 008.

## Phase 9: Convergence

- [X] T048 Add a test that runs every MCP tool from `GROUPS` against the real app (BatchivoClient over `httpx.ASGITransport`, a token holding read+write+print) and asserts no call is refused as "does not accept API tokens" or for a missing scope, so each tool's API route is reachable by a token, in `backend/tests/integration/test_mcp_tools_reach_api.py` per FR-007, FR-012 (partial)
- [X] T049 Add a test derived from `GROUPS` that calls every MCP tool against a mocked API answering with an error and asserts the agent gets the API's status and message, in `backend/tests/mcp_server/test_tool_error_paths.py` per SC-005 (partial)
- [X] T050 Keep the token secret out of Sentry events in development, where `send_default_pii` sends request headers: mask `bvt_` values in `before_send` (`backend/app/observability/sentry.py`, outside the reserved zone, orchestrator approval needed) or record it as a known limitation in research.md per FR-010 (partial) — option (a), approved by the orchestrator: `mask_api_tokens` in `before_send`, test `tests/unit/test_sentry_masks_api_tokens.py`
