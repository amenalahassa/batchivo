# Implementation Plan: Batchivo MCP Server for AI Agents

**Branch**: `claude/mystifying-bardeen-acb21d` | **Date**: 2026-11-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/010-mcp-server/spec.md`

## Summary

Personal API tokens (new `api_tokens` table, hashed, scoped, bound to one tenant, mandatory
expiry ≤ 1 year) are accepted by the existing auth dependency as an alternative to the JWT, only
on an explicit allowlist of endpoints, each mapped to the scope it needs. A separate stdio MCP
process (`backend/app/mcp_server/`, official MCP SDK + httpx) exposes tool groups that call the
REST API with the token and never touch the database. Settings gains an "API tokens" tab;
operator docs explain the Claude Code `.mcp.json` setup. Genai tools come from 008 (or from here
if 008 merges first), briefs and calibrations from 009, through the documented extension pattern.

## Technical Context

**Language/Version**: Python 3.12 (backend + MCP process), TypeScript 5.9 (frontend)

**Primary Dependencies**: FastAPI 0.141, SQLAlchemy 2.0 async, Alembic, Pydantic v2; **new**:
`mcp` 2.3 (official MCP Python SDK, `MCPServer`); httpx (present); respx (present, tests). Frontend:
React 19, TanStack Query, shadcn/ui (all present).

**Storage**: PostgreSQL, one new table `api_tokens` with RLS (migration `api_tokens_v1`).

**Testing**: pytest (+ respx for the MCP server against a mocked API), Vitest, Playwright
(chromium, settings journey).

**Target Platform**: backend in k3s; MCP process on the operator's workstation (stdio, launched
by Claude Code).

**Project Type**: web application (backend + frontend) + a CLI-style stdio process.

**Performance Goals**: token auth adds one indexed lookup and at most one UPDATE per minute per
token; no measurable change to request latency.

**Constraints**: no change to JWT behaviour (SC-006); deny-by-default for tokens; no secret in
any log; MCP process imports nothing from the backend outside `app.mcp_server`.

**Scale/Scope**: a handful of tokens per user; ~45 MCP tools in 7 groups.

## Constitution Check

| Principle | Status | How |
|---|---|---|
| I. Multi-tenant isolation | PASS | `api_tokens.tenant_id` + RLS (4 policies, `FORCE`); lookup admitted only by proven hash (research R4), no privileged session; token bound to one tenant, `X-Tenant-ID` cannot escape it (R6); management endpoints use `CurrentTenant` + `TenantDB`; the MCP server goes through the API, so RLS and validation apply unchanged. |
| II. Tests are part of the change | PASS | Endpoint tests 200/201, 401, 404, 422; auth-path unit tests (every refusal reason, scope, allowlist drift, JWT regression); MCP tool tests per tool against respx; Vitest for the tab; e2e for the settings journey. |
| III. One implementation | PASS | Token status derived in one function (`ApiTokenService.status_of`); scope check in one place (`api_token_policy`); the MCP layer re-derives nothing — it forwards. |
| IV. Money exact | N/A | No money handled. |
| V. Derived figures expire | PASS | `status` derived on read, not stored. |
| VI. History immutable | PASS | `revoked_at` written once; a revoked token cannot be re-activated. |
| VII. Deployment via pipeline | PASS | No deploy step; nothing pushed; commit style `type: description`. |

Post-design re-check: PASS (no violation, Complexity Tracking empty).

## Authentication design (high-risk zone `auth/`, sent to the orchestrator for validation)

How a personal token authenticates **without weakening the JWT** (research R3–R7):

1. `get_current_user(request, db, authorization)`: after the existing `Bearer ` check, **one**
   branch: `if token.startswith("bvt_"): return await authenticate_api_token(request, db, token)`.
   Everything below that line is the current JWT code, unchanged. A JWT never starts with `bvt_`
   (it starts with `eyJ`), so no JWT can enter the token path and no token is ever JWT-decoded.
2. `authenticate_api_token` (`app/auth/api_tokens.py`): sha256 the value → `set_config(
   'app.current_api_token_hash', hash, true)` → select by hash (RLS admits only that row) →
   401 `Invalid or expired API token` if missing, revoked, expired, user inactive, or the user is
   no longer a member of the token's tenant → endpoint policy: `(request.method,
   endpoint qualname)` must be in `TOKEN_ROUTE_SCOPES` (else 403 "does not accept API tokens")
   and its scope must be in the token's scopes (else 403 naming the scope) → touch
   `last_used_at` (≤ once a minute) → `request.state.api_token = ApiTokenContext(...)` →
   `set_rls_context(db, user_id=...)` as for a JWT → return the user.
3. `get_current_tenant(request, ...)`: if `request.state.api_token` is set, return the token's
   tenant (and set the RLS tenant), 403 when `X-Tenant-ID` names another tenant, never
   auto-create a workspace; otherwise the existing code, unchanged.
4. Roles are untouched: `RequireMember` / `RequireAdmin` / `role_in_tenant` keep reading the
   membership of the same user in the same tenant, so a token never exceeds its owner's role.
5. Deny by default: any endpoint not in the table — auth, users, members, token management,
   settings, payments, platform, shop, DELETEs — refuses a token. A test pins the forbidden
   families and another resolves every table entry to a live route.
6. Revocation and expiry are checked on every request (no cache).

**Validated by the user via the orchestrator (2026-11-24, "Oui, valider")**, with conditions:
- RLS is off in production (`rls_enabled=false`), so the lookup query itself filters
  `WHERE token_hash = :hash` (exact, on the indexed SHA-256 column); RLS is a second belt only.
  A test runs the token path with RLS off and proves a token of tenant A never resolves to or
  serves tenant B.
- No match on `token_prefix` / `<id8>` alone ever authenticates; the prefix is display only.
- The final report states the `mcp` dependency's version, licence and new transitive packages.
- Granted: `backend/app/mcp_server/` and one line in `docs-site/sidebars.ts`.

## Project Structure

### Documentation (this feature)

```text
specs/010-mcp-server/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── api-tokens-api.md
│   └── mcp-tools.md
└── tasks.md
```

### Source Code

```text
backend/
├── alembic/versions/20261124_api_tokens.py        # revision api_tokens_v1 (down: print_sends_v1)
├── app/
│   ├── models/api_token.py                         # ApiToken
│   ├── models/__init__.py                          # + import line (shared file)
│   ├── schemas/api_token.py
│   ├── services/api_token_service.py               # create / list / revoke / status_of / hash
│   ├── auth/api_tokens.py                          # authenticate_api_token, ApiTokenContext
│   ├── auth/api_token_policy.py                    # TOKEN_ROUTE_SCOPES (deny by default)
│   ├── auth/dependencies.py                        # one branch in get_current_user / get_current_tenant
│   ├── api/v1/api_tokens.py                        # /api/v1/api-tokens
│   ├── main.py                                     # + include_router line (shared file)
│   └── mcp_server/
│       ├── __init__.py
│       ├── __main__.py                             # python -m app.mcp_server
│       ├── config.py                               # env vars, masking log filter
│       ├── client.py                               # BatchivoClient (httpx), error mapping
│       ├── server.py                               # MCPServer build + scope-filtered registration
│       └── tools/
│           ├── __init__.py                         # GROUPS
│           ├── base.py                             # ToolSpec
│           ├── account.py  ideas.py  models.py  printers.py
│           ├── spools.py   production.py  print_sends.py
├── pyproject.toml / poetry.lock                    # + mcp
└── tests/
    ├── api/test_api_tokens.py
    ├── unit/test_api_token_auth.py                 # auth path, policy, JWT regression, logs
    ├── unit/test_api_token_service.py
    ├── unit/test_api_token_model.py
    └── mcp_server/
        ├── conftest.py                             # respx mock_api, server factory
        ├── test_config_and_startup.py
        ├── test_client.py
        └── test_tools_<group>.py (7 files) + test_tool_coverage.py

frontend/
├── src/types/apiToken.ts
├── src/lib/api/apiTokens.ts
├── src/hooks/useApiTokens.ts
├── src/components/settings/ApiTokensSettings.tsx (+ .test.tsx)
├── src/pages/Settings.tsx                          # + one tab (agreed with 008)
└── e2e/tests/settings/api-tokens.spec.ts

docs-site/docs/mcp.md  (+ one entry in docs-site/sidebars.ts)
```

**Structure Decision**: existing web-application layout; the MCP process lives in
`backend/app/mcp_server/` as §7 specifies (research R11).

## Shared and out-of-zone files

- Shared (lines added only): `backend/app/main.py`, `backend/app/models/__init__.py`,
  `frontend/src/pages/Settings.tsx` (one tab), `specs/backlog.md` (own block),
  `backend/pyproject.toml` + `poetry.lock` (new `mcp` dependency — flagged to the orchestrator).
- `docs-site/sidebars.ts`: one entry after `ideas`, like 007. Docs are in this feature's zone.
- No file of 008's zone is touched.

## What later features will find (extension notes)

- **008 Generative AI layer**: if 008 merges before 010 converges, 010 adds the genai tools
  itself. Otherwise 008 adds, when it merges: `backend/app/mcp_server/tools/genai.py`
  (`list_capabilities`, `start_generation` — scope `genai`, W —, `get_generation_job`,
  `adopt_generation_output` — `genai`, W), one line in `tools/GROUPS`, its rows in
  `TOKEN_ROUTE_SCOPES` (`genai` for start/adopt, `read` for list/get), and
  `tests/mcp_server/test_tools_genai.py`. The `genai` scope already exists in tokens, the UI and
  the policy check; nothing in `auth/` changes beyond the rows. Pattern: `contracts/mcp-tools.md`
  §Extension pattern.
- **009 Preflight foundations**: adds `tools/design.py` (briefs, calibrations, typed notes
  filters, print test results) with `read`/`write` rows, same pattern. 009's typed note fields
  pass through `add_file_note` / `list_file_notes` unchanged, since these tools forward the body
  and query as given.
- **HTTP transport later**: `server.py` builds the MCPServer instance independently of the
  transport; adding streamable HTTP is a `__main__` option.

## Complexity Tracking

None.
