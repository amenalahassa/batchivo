# Research: Batchivo MCP Server for AI Agents (010)

Architecture reference: `docs/ARCHITECTURE-IDEAS-GENAI-PREFLIGHT.md` §7. Each departure from it is
marked **Deviation**.

## R1 — Token format

- **Decision**: `bvt_<id8>_<secret43>`: the literal prefix `bvt_`, 8 random base32 lowercase
  characters (public id), `_`, then `secrets.token_urlsafe(32)` (43 characters, 256 bits). The
  first 12 characters (`bvt_<id8>`) are stored as `token_prefix` and shown in the list so the
  operator can tell tokens apart; the secret never is.
- **Rationale**: a fixed prefix lets the auth dependency route a bearer value to the token path
  without trying to decode it as a JWT (a JWT always starts with `eyJ`), and lets secret
  scanners recognise a leaked value. 256 bits of entropy makes guessing impossible.
- **Alternatives**: a long-lived JWT (cannot be revoked without a deny list, carries claims that
  go stale when a role changes); opaque UUID (122 bits, no recognisable prefix).

## R2 — Hashing

- **Decision**: store `token_hash = sha256(full_token).hexdigest()` with a unique index; look up
  by hash and compare with `hmac.compare_digest`.
- **Rationale**: the secret is random and 256 bits long, so a slow password hash buys nothing
  (there is no dictionary to resist) and would cost bcrypt time on every API call. A unique hash
  index gives O(1) lookup.
- **Alternatives**: bcrypt (per-request cost, needs the id to find the row); HMAC with
  `SECRET_KEY` (rotating the key would silently kill every token).

## R3 — How a token authenticates without weakening the JWT (high-risk zone: `auth/`)

- **Decision**: one branch at the top of `get_current_user`, after the `Bearer ` check:
  - value starts with `bvt_` → `authenticate_api_token(request, db, value)` (new module
    `app/auth/api_tokens.py`); otherwise the **existing JWT code runs unchanged, line for line**.
  - The token path: hash → lookup (R4) → refuse (401, same `WWW-Authenticate: Bearer` header as
    the JWT path) when unknown, revoked, expired, user missing/inactive, or the user is no longer
    a member of the token's tenant → route policy check (R5, 403) → touch `last_used_at` (R7) →
    put an `ApiTokenContext(id, tenant_id, scopes)` on `request.state.api_token` → `set_rls_context
    (user_id=...)` exactly as the JWT path does → return the `User`.
  - `get_current_tenant`: when `request.state.api_token` is set, the tenant is the token's tenant;
    an `X-Tenant-ID` that names another tenant is refused (403); no auto-created workspace on the
    token path. Without a token context the function is unchanged.
  - `get_current_user` and `get_current_tenant` gain a `request: Request` parameter. Both remain
    the single override point used by the test suite (`dependency_overrides`), so every existing
    test keeps running through the same path. No WebSocket route depends on them
    (`printer_ws.py` authenticates its own query token), so `Request` is safe.
- **What cannot happen**: a JWT is never accepted as a token and a token never as a JWT (disjoint
  prefixes, two code paths); a token cannot reach any route that is not explicitly allowlisted
  (R5); a token cannot widen a role (role dependencies such as `RequireMember` still run after
  `get_current_user` and read the same membership); a token cannot pick another tenant.
- **Regression proof**: the whole existing auth suite (`tests/test_auth_flow.py`,
  `tests/integration/test_auth_authorization.py`) runs unchanged, plus new tests that a JWT still
  works on every allowlisted and non-allowlisted route, that a `bvt_` value is never JWT-decoded,
  and that a JWT-shaped value is never looked up as a token.
- **Alternatives**: a separate `get_current_principal` dependency adopted router by router
  (touches ~45 routers, easy to miss one: deny-by-default would not hold); a middleware
  (runs before routing, cannot see the matched endpoint, and opens its own DB session outside
  RLS).

## R4 — Finding the token under row-level security

- **Decision**: `api_tokens` gets the usual four tenant-isolation policies, and the SELECT and
  UPDATE policies additionally admit `token_hash = current_setting('app.current_api_token_hash',
  true)`. The token path issues `set_config('app.current_api_token_hash', <hash>, true)` on the
  request session before the lookup, so the lookup sees exactly one row: the one whose hash the
  caller proved knowledge of. No privileged (RLS-free) session is used.
- **Rationale**: `privileged_session_maker` has two pinned users and is reserved for work that is
  cross-tenant by nature; authenticating a token is not. The hash is only known to someone who
  holds the secret, so admitting that one row leaks nothing.
- **Alternatives**: privileged session (widens a pinned exception); `SECURITY DEFINER` function
  (harder to test on SQLite, which the suite also runs on).

## R5 — Which routes accept a token, and with which scope (deny by default)

- **Decision**: a central policy table `app/auth/api_token_policy.py`:
  `TOKEN_ROUTE_SCOPES: dict[tuple[str, str], str]` keyed by `(HTTP method, endpoint qualified
  name)` → required scope. The token path reads `request.scope["endpoint"]` and
  `request.method`; a pair absent from the table is refused with 403 "This endpoint does not
  accept API tokens"; a pair whose scope the token lacks is refused with 403 "API token is
  missing the '<scope>' scope".
- **Why the endpoint and not the path**: FastAPI 0.141 includes routers lazily
  (`_IncludedRouter`); inside a dependency, `scope["route"].path` is the router-local template
  (`/{idea_id}`), ambiguous across routers. `scope["endpoint"]` is the handler function, unique.
  Verified with a probe on the installed version.
- **Drift guard**: a test resolves every key to a real route of `app.main.app` (method and
  endpoint) and fails if one disappears; another asserts that the denied families (auth, users,
  tenant members, api-tokens management, settings, payments, platform, shop) have no entry.
- **Extension**: 008 and 009 add their rows to this table (`genai`, `read`, `write`) in their own
  change; nothing else in `auth/` changes.
- **Scope semantics**: scopes are independent (write does not imply read). GET endpoints in the
  table need `read`; creating/changing needs `write`; print send prepare, confirm and consumption
  accept/dismiss need `print`; generation start/adopt need `genai` (rows added by 008). The UI
  pre-ticks `read`.
- **Alternatives**: method-based rule on every route (would open token management, payments and
  platform routes to a `write` token); a per-router dependency (see R3).

## R6 — Token bound to one tenant

- **Decision**: a token stores `tenant_id` = the tenant the user was working in when creating it
  (the request's `CurrentTenant`). Membership is re-checked on every request.
- **Rationale**: an agent works on one shop; binding avoids a token that silently follows the
  user into every shop they belong to.

## R7 — Recording last use

- **Decision**: on the token path, `UPDATE api_tokens SET last_used_at = now() WHERE id = :id AND
  (last_used_at IS NULL OR last_used_at < now() - interval '60 seconds')` on the request session;
  it is committed with the request (`get_db` commits on success).
- **Trade-off**: a request that fails and rolls back does not record its use. Acceptable: FR-009
  asks for minute precision of use, not an audit trail; the update is cheap and needs no second
  session.

## R8 — Expiry rules

- **Decision**: the API takes `expires_at` (timezone-aware ISO datetime), required, `now <
  expires_at ≤ now + 365 days` (422 otherwise). The UI offers 30 / 90 / 365 days (computed client
  side) or a date picker bounded to today+1 … today+364 (end of that day, local time).
- **Status** is derived on read: `revoked` if `revoked_at`, else `expired` if `expires_at ≤ now`,
  else `active` (not stored: Constitution V).

## R9 — Token management API

- **Decision**: `api/v1/api_tokens.py` under `/api/v1/api-tokens`: `GET` (own tokens in the
  current tenant), `POST` (201, secret in the response once), `POST /{id}/revoke` (idempotent,
  200), `GET /current` (the calling token's name, scopes, expiry, tenant; **only** reachable with
  a token, any scope). Management routes are JWT-only (absent from the policy table). Any role may
  manage its own tokens.

## R10 — Secrets never logged

- **Backend**: the token travels only in `Authorization`. No log line in the token path includes
  it (only `token_prefix` and id). Error details never echo it. Sentry runs with
  `send_default_pii=False` outside development, which strips the `Authorization` header; no change
  to `observability/` is needed. A test captures logs (`caplog`) across create/use/revoke/refused
  paths and asserts the secret never appears.
- **MCP server**: reads the token from the environment, never prints it; its error messages and
  logs go to stderr and a masking filter replaces any `bvt_…` sequence with `bvt_****`. httpx
  logging is left at WARNING. A test captures stderr across startup errors and failed calls.

## R11 — MCP server process and location

- **Decision**: `backend/app/mcp_server/` as in §7, run with `python -m app.mcp_server` (stdio),
  built on the official MCP Python SDK (`mcp`, `MCPServer` API (FastMCP renamed in 2.x)) and `httpx`. It imports nothing from
  `app.*` outside `app.mcp_server` (`app` is a namespace package, so no backend module loads); a
  test imports it in a subprocess and asserts `app.database`, `app.models` and `app.config` are
  absent from `sys.modules` (FR-013).
- **Deviation from the brief's wording** ("`mcp/` at the root or under `backend/`"): the brief
  defers to §7, which names `backend/app/mcp_server/`. Kept there so it shares the backend's
  Python toolchain, lint and test gates; it carries no DB driver use.
- **New Python dependency**: `mcp` (official SDK), resolved to **2.3.0**, licence **MIT**,
  constraint `mcp>=2.3.0,<3`. In 2.x `FastMCP` is renamed `mcp.server.mcpserver.MCPServer`;
  tests drive it through `mcp.client.Client` over the in-memory transport. New transitive
  packages: `mcp-types`, `httpx2`, `httpcore2`, `jsonschema`, `jsonschema-specifications`,
  `referencing`, `rpds-py`, `attrs`, `sse-starlette`, `truststore`, `pywin32` (Windows only);
  `idna` 3.11 → 3.20. Starlette, FastAPI, pydantic and httpx unchanged. Flagged to the
  orchestrator.
- **Tool output**: every result is returned as one JSON text block (lists and empty bodies stay
  readable; MCP's unstructured conversion would split a list into one block per item).
- **Middleware**: `TenantContextMiddleware` skips `bvt_` values instead of trying to decode
  them as JWTs (found by the "never decoded as a JWT" test); one guard line in
  `auth/middleware.py`, inside this feature's `auth/` zone.
- **Configuration**: `BATCHIVO_API_URL` (e.g. `http://localhost:8000`), `BATCHIVO_API_TOKEN`.
  Missing or empty → exit 2 with a message naming the variable.
- **Tool groups**: `app/mcp_server/tools/<group>.py`, each exposing `build_tools(client) -> list[ToolSpec]`
  (name, description, scope, read-only/destructive annotations, handler). `tools/__init__.py`
  holds `GROUPS = [ideas, models, printers, spools, production, print_sends, account]`. 008 adds
  `genai`, 009 adds `design` (briefs, calibrations) by adding a module and one line.
- **Scope-aware listing**: at startup the server calls `GET /api/v1/api-tokens/current`; tools
  whose scope the token lacks are not registered. The API still enforces (FR-007); the filter is
  only a convenience. If the call fails with 401 the server exits with "token refused".
- **Annotations**: read tools `readOnlyHint=True`; write tools `readOnlyHint=False,
  destructiveHint=False`; `confirm_print` `destructiveHint=True` (FR-015).
- **Errors**: an API error becomes a tool error result (`isError`) with `"<status>: <detail>"`; a
  connection error becomes "Batchivo could not be reached at <url>"; the server keeps running.
- **Files**: `upload_idea_image` and `prepare_print` (file variant) take a local file path the
  agent can read; `get_idea_entry_image` returns MCP image content.
- **HTTP transport**: deferred (spec Assumptions); `MCPServer` supports it later without changing tools.

## R12 — Frontend

- **Decision**: `components/settings/ApiTokensSettings.tsx` (+ test), `lib/api/apiTokens.ts`,
  `types/apiToken.ts`, `hooks/useApiTokens.ts`; `pages/Settings.tsx` gains one `TabsTrigger`
  ("API tokens", `KeyRound` icon) and one `TabsContent`, other tabs untouched (agreement with 008
  on `Settings.tsx`). The secret dialog shows the value once with a copy button; closing it drops
  the value from state.

## R13 — Documentation

- **Decision**: `docs-site/docs/mcp.md`, plus one entry in `docs-site/sidebars.ts` after `ideas`
  (a one-line addition, same pattern 007 used).

## R14 — Migration

- **Decision**: revision `api_tokens_v1`, `down_revision = "print_sends_v1"` (current head). At
  merge, re-point onto 008's head if it landed first, so `alembic heads` shows one head.

## R15 — Crash reports (convergence)

- **Decision**: `before_send` in `app/observability/sentry.py` masks every `bvt_...` value in a
  Sentry event (headers, breadcrumbs, extra, messages) to `bvt_****`. Outside the reserved zone,
  approved by the orchestrator.
- **Rationale**: in development `send_default_pii=True` sends request headers, the Authorization
  header among them; FR-010 forbids the secret in any crash report. Production already filters
  that header, so nothing else changes.
- **Alternatives considered**: a known-limitation note (left the gap open in development).
