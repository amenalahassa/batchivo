# Contract: MCP tools (`backend/app/mcp_server/`)

Process: `python -m app.mcp_server` (stdio). Environment: `BATCHIVO_API_URL` (required, base URL
without `/api/v1`), `BATCHIVO_API_TOKEN` (required). Every tool calls
`{BATCHIVO_API_URL}/api/v1/...` with `Authorization: Bearer <token>` and nothing else (FR-013).

Startup: `GET /api/v1/api-tokens/current`. 401 → exit 2, "Batchivo refused the API token
(revoked, expired or unknown)". Unreachable → exit 2, "Batchivo could not be reached at <url>".
Then only the tools whose scope is in the token's scopes are registered.

Result: the API's JSON body as structured content (and text). Error: `isError` with
`"<status>: <detail>"` (422 bodies are flattened to `field: message` lines). Connection error:
`isError` with "Batchivo could not be reached at <url>"; the server keeps running.

Annotations: R = `readOnlyHint: true`; W = `readOnlyHint: false, destructiveHint: false`;
D = `readOnlyHint: false, destructiveHint: true`.

## Group `account` (`tools/account.py`)

| Tool | Scope | Ann. | API |
|---|---|---|---|
| `get_token_info` | any | R | GET `/api-tokens/current` |

## Group `ideas` (`tools/ideas.py`)

| Tool | Scope | Ann. | API | Arguments |
|---|---|---|---|---|
| `list_ideas` | read | R | GET `/ideas` | `status[]`, `tag[]`, `source`, `search`, `archived`, `sort`, `skip`, `limit` (passed through) |
| `list_idea_tags` | read | R | GET `/ideas/tags` | — |
| `get_idea` | read | R | GET `/ideas/{idea_id}` | `idea_id` |
| `list_idea_entries` | read | R | GET `/ideas/{idea_id}/entries` | `idea_id`, paging passthrough |
| `get_idea_entry_image` | read | R | GET `/ideas/{idea_id}/entries/{entry_id}/image` | returns MCP image content |
| `create_idea` | write | W | POST `/ideas` | body fields of `IdeaCreate` |
| `update_idea` | write | W | PATCH `/ideas/{idea_id}` | `idea_id` + `IdeaUpdate` fields |
| `add_idea_entry` | write | W | POST `/ideas/{idea_id}/entries` | `idea_id` + entry body |
| `upload_idea_image` | write | W | POST `/ideas/{idea_id}/entries/images` (multipart) | `idea_id`, `file_path` (local), optional caption fields of the endpoint |
| `update_idea_entry` | write | W | PATCH `/ideas/{idea_id}/entries/{entry_id}` | |
| `add_idea_iteration` | write | W | POST `/ideas/{idea_id}/iterations` | |
| `import_ideas` | write | W | POST `/ideas/import` | `items[]` as in the 007 contract |
| `parse_idea_report` | write | W | POST `/ideas/import/parse-report` | raw report text |
| `convert_idea` | write | W | POST `/ideas/{idea_id}/convert` | |

## Group `models` (`tools/models.py`)

| Tool | Scope | Ann. | API |
|---|---|---|---|
| `list_models` | read | R | GET `/models` (paging/search passthrough) |
| `get_model` | read | R | GET `/models/{model_id}` |
| `list_model_files` | read | R | GET `/models/{model_id}/files` |
| `list_file_versions` | read | R | GET `/models/{model_id}/file-versions` |
| `list_file_notes` | read | R | GET `/models/{model_id}/file-notes` (filters passthrough) |
| `add_file_note` | write | W | POST `/models/{model_id}/files/{file_id}/notes` |
| `update_file_note` | write | W | PATCH `/models/{model_id}/file-notes/{note_id}` (incl. resolve) |
| `carry_forward_note` | write | W | POST `/models/{model_id}/file-notes/{note_id}/carry-forward` |

## Group `printers` (`tools/printers.py`)

| Tool | Scope | Ann. | API |
|---|---|---|---|
| `list_printers` | read | R | GET `/printers` |
| `get_printer` | read | R | GET `/printers/{printer_id}` |
| `get_printer_status` | read | R | GET `/printers/{printer_id}/status` |
| `get_ams_slots` | read | R | GET `/printers/{printer_id}/ams` |

## Group `spools` (`tools/spools.py`)

| Tool | Scope | Ann. | API |
|---|---|---|---|
| `list_spools` | read | R | GET `/spools` (filters/paging passthrough) |
| `get_spool` | read | R | GET `/spools/{spool_id}` |

## Group `production` (`tools/production.py`)

| Tool | Scope | Ann. | API |
|---|---|---|---|
| `list_print_jobs` | read | R | GET `/print-queue` |
| `get_print_job` | read | R | GET `/print-queue/{job_id}` |
| `list_production_runs` | read | R | GET `/production-runs` |
| `get_production_run` | read | R | GET `/production-runs/{run_id}` |

## Group `print_sends` (`tools/print_sends.py`)

| Tool | Scope | Ann. | API | Notes |
|---|---|---|---|---|
| `prepare_print` | print | W | POST `/printers/{printer_id}/prints/prepare` (multipart) | either `model_file_id` or `file_path` (local); `plate`, `slot_mapping`; returns summary + `confirmation_token`; description tells the agent to show the summary to the operator |
| `confirm_print` | print | **D** | POST `/printers/{printer_id}/prints/confirm` | `confirmation_token` (required), `acknowledge_warnings: bool = false` (FR-015) |
| `list_print_sends` | read | R | GET `/printers/{printer_id}/prints` | |
| `get_print_send` | read | R | GET `/printers/{printer_id}/prints/{send_id}` | |

## Extension pattern (for 008 and 009)

1. Add `backend/app/mcp_server/tools/<group>.py` exposing `build_tools(client: BatchivoClient) -> list[ToolSpec]`;
   each tool is an async function with typed parameters (its input schema) closing over the
   client and calling `client.get/post/patch/upload` through `call_api`, wrapped with
   `read_tool(...)` / `write_tool(..., scope=..., destructive=...)`.
2. Append the module to `GROUPS` in `backend/app/mcp_server/tools/__init__.py`.
3. Add the matching `(method, endpoint)` rows to `TOKEN_ROUTE_SCOPES` in
   `backend/app/auth/api_token_policy.py` (`genai` for generation start/adopt).
4. Add `backend/tests/mcp_server/test_tools_<group>.py` using the `mock_api` (respx) fixture of
   `backend/tests/mcp_server/conftest.py`: request shape, success, API error, scope-filtered
   registration. The coverage test (every registered tool has a test id) picks it up.
