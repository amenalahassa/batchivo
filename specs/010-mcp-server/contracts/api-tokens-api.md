# Contract: Personal API tokens (`/api/v1/api-tokens`)

Router `backend/app/api/v1/api_tokens.py`, mounted in `main.py` with prefix
`{api_v1_prefix}/api-tokens`. Dependencies: `CurrentUser`, `CurrentTenant`, `TenantDB`.
The management routes (list, create, revoke) are **JWT only**: they are absent from the token
policy table, so a token gets 403 there.

## Schemas (`backend/app/schemas/api_token.py`)

```text
ApiTokenScope = Literal["read", "write", "genai", "print"]

ApiTokenCreate
  name: str (strip, 1..100)
  scopes: list[ApiTokenScope] (min 1, deduplicated, sorted)
  expires_at: datetime (timezone-aware; now < expires_at <= now + 365 days)

ApiTokenResponse
  id: UUID
  name: str
  token_prefix: str            # "bvt_ab12cd34"
  scopes: list[str]
  created_at: datetime
  expires_at: datetime
  last_used_at: datetime | null
  revoked_at: datetime | null
  status: "active" | "expired" | "revoked"     # derived

ApiTokenCreated(ApiTokenResponse)
  token: str                   # full secret, this response only

ApiTokenListResponse
  items: list[ApiTokenResponse]  # newest first
  total: int

ApiTokenCurrent
  id, name, token_prefix, scopes, expires_at, tenant_id: UUID, tenant_name: str
```

## Endpoints

| Method | Path | Auth | Success | Errors |
|---|---|---|---|---|
| GET | `/api-tokens` | JWT | 200 `ApiTokenListResponse` (own tokens, current tenant) | 401 |
| POST | `/api-tokens` | JWT | 201 `ApiTokenCreated` | 401, 422 (name, scopes, expiry) |
| POST | `/api-tokens/{token_id}/revoke` | JWT | 200 `ApiTokenResponse` (idempotent) | 401, 404 (unknown or another user's), 422 (bad UUID) |
| GET | `/api-tokens/current` | token (any scope) | 200 `ApiTokenCurrent` | 401; 403 when called with a JWT ("only available to API tokens") |

## Token authentication (all allowlisted endpoints)

`Authorization: Bearer bvt_<id8>_<secret>`.

| Condition | Status | `detail` |
|---|---|---|
| unknown hash, revoked, expired, owner inactive, owner no longer member | 401 | `Invalid or expired API token` (one message: does not reveal which) |
| endpoint not in the policy table | 403 | `This endpoint does not accept API tokens` |
| scope missing | 403 | `API token is missing the '<scope>' scope` |
| `X-Tenant-ID` names another tenant | 403 | `API token is bound to another tenant` |
| role too low (e.g. viewer writing) | 403 | unchanged message of the existing role dependency |

## Policy table (`backend/app/auth/api_token_policy.py`)

Keyed by `(method, "<module>.<function>")` of the endpoint. Initial content (paths for reading;
the table itself uses the endpoint names found at implementation):

| Scope | Method + path (`/api/v1` omitted) |
|---|---|
| read | GET `/ideas`, `/ideas/tags`, `/ideas/{id}`, `/ideas/{id}/entries`, `/ideas/{id}/entries/{entry_id}/image` |
| write | POST `/ideas`, PATCH `/ideas/{id}`, POST `/ideas/{id}/entries`, POST `/ideas/{id}/entries/images`, PATCH `/ideas/{id}/entries/{entry_id}`, POST `/ideas/{id}/iterations`, POST `/ideas/import`, POST `/ideas/import/parse-report`, POST `/ideas/{id}/convert` |
| read | GET `/models`, `/models/{id}`, `/models/{id}/files`, `/models/{id}/file-versions`, `/models/{id}/file-notes` |
| write | POST `/models/{id}/files/{file_id}/notes`, PATCH `/models/{id}/file-notes/{note_id}`, POST `/models/{id}/file-notes/{note_id}/carry-forward` |
| read | GET `/printers`, `/printers/{id}`, `/printers/{id}/status`, `/printers/{id}/ams` |
| read | GET `/spools`, `/spools/{id}` |
| read | GET `/print-queue`, `/print-queue/{id}`, `/production-runs`, `/production-runs/{id}` |
| read | GET `/printers/{id}/prints`, `/printers/{id}/prints/{send_id}` |
| print | POST `/printers/{id}/prints/prepare`, `/printers/{id}/prints/confirm`, `/printers/{id}/prints/{send_id}/consumption/accept`, `/printers/{id}/prints/{send_id}/consumption/dismiss` |
| (any) | GET `/api-tokens/current` |

`parse-report` is a POST that persists nothing but requires the member role in 007; it is
classed `write` so a read-only token cannot spend server work on it.

Never in the table (pinned by a test): `/auth/*`, `/users/*`, `/tenant-members*`,
`/api-tokens` management, `/settings*`, `/payments*`, `/platform/*`, `/shop/*`, `/onboarding/*`,
`/test/*`, DELETE on any resource.

Added later by others: 008 → `genai` rows for its start/adopt routes and `read` rows for its list
and get routes; 009 → `read`/`write` rows for briefs and calibrations.
