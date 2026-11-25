# Data Model: Batchivo MCP Server (010)

One new table. The MCP server stores nothing.

## `api_tokens` (model `ApiToken`, `backend/app/models/api_token.py`)

| Column | Type | Rules |
|---|---|---|
| `id` | UUID PK | `UUIDMixin` |
| `tenant_id` | UUID FK `tenants.id` ON DELETE CASCADE, NOT NULL, indexed | the shop the token works in (R6) |
| `user_id` | UUID FK `users.id` ON DELETE CASCADE, NOT NULL, indexed | owner; the token acts as this user |
| `name` | VARCHAR(100) NOT NULL | 1–100 chars after trim; duplicates allowed |
| `token_prefix` | VARCHAR(12) NOT NULL | `bvt_<id8>`, shown in lists |
| `token_hash` | CHAR(64) NOT NULL, UNIQUE | sha256 hex of the full token (R2) |
| `scopes` | JSON (list of strings) NOT NULL | non-empty subset of `read`, `write`, `genai`, `print`; stored sorted, deduplicated |
| `expires_at` | TIMESTAMPTZ NOT NULL | `created_at < expires_at ≤ created_at + 365 days` (R8) |
| `last_used_at` | TIMESTAMPTZ NULL | updated at most once a minute (R7) |
| `revoked_at` | TIMESTAMPTZ NULL | set once, never cleared |
| `created_at`, `updated_at` | TIMESTAMPTZ | `TimestampMixin` |

Constraints:
- `CHECK (char_length(trim(name)) BETWEEN 1 AND 100)` (`ck_api_tokens_name_length`)
- Index `ix_api_tokens_tenant_user` on `(tenant_id, user_id, created_at)`.
- Scope validity and expiry bound are enforced in the Pydantic schema and the service (JSON
  array checks are not portable to SQLite, which the test suite also uses).

Row-level security (migration `api_tokens_v1`, `ENABLE` + `FORCE`):
- `tenant_isolation_select`: `USING (<tenant> OR token_hash = NULLIF(current_setting('app.current_api_token_hash', true), ''))`
- `tenant_isolation_update`: same `USING`
- `tenant_isolation_insert`: `WITH CHECK (<tenant>)`
- `tenant_isolation_delete`: `USING (<tenant>)`

where `<tenant>` is the project-wide `tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid`.

Derived (never stored): `status` = `revoked` if `revoked_at` else `expired` if `expires_at ≤ now`
else `active`.

State transitions: `active → revoked` (operator), `active → expired` (time). No way back.

Relationships: `ApiToken.user` (many-to-one), `ApiToken.tenant` (many-to-one). No back-reference
added to `User`/`Tenant` (keeps their files untouched).

## Runtime-only

- `ApiTokenContext` (dataclass on `request.state.api_token`): `id`, `tenant_id`, `scopes:
  frozenset[str]`, `prefix`. Never contains the secret.
- MCP `ToolSpec` (dataclass in `app/mcp_server/tools/base.py`): `name`, `description`, `scope`,
  `read_only: bool`, `destructive: bool`, `handler`.
