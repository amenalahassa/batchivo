"""Every MCP tool reaches a Batchivo route that accepts API tokens (FR-007, FR-012).

The MCP tests mock the API, so they cannot tell whether the route a tool calls
is in the token policy table. This test runs every tool, taken from the server's
own list, against the real application with a real token, and checks that no
call is refused for being made with a token or for a missing scope. Placeholder
identifiers make most calls end in 404 or 422, which is fine: the policy check
runs before the handler, so either answer proves the route accepts the token.
"""

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport
from mcp.client import Client

from app.auth.api_tokens import INVALID_TOKEN_DETAIL, NOT_ACCEPTED_DETAIL
from app.main import app
from app.mcp_server.client import BatchivoClient
from app.mcp_server.server import build_server
from tests.api_token_helpers import make_token
from tests.mcp_server.tool_args import minimal_arguments, upload_file

pytestmark = pytest.mark.asyncio

ALL_SCOPES = ["genai", "print", "read", "write"]
REFUSALS = (NOT_ACCEPTED_DETAIL, "is missing the", INVALID_TOKEN_DETAIL)


@asynccontextmanager
async def _server_on_the_app(secret: str):
    client = BatchivoClient("http://test", secret, transport=ASGITransport(app=app))
    async with Client(build_server(client, ALL_SCOPES)) as mcp:
        yield mcp


async def test_every_tool_is_accepted_with_a_token(
    unauthenticated_client, db_session, test_tenant, test_user, tmp_path
):
    _, secret = await make_token(db_session, test_tenant, test_user, ALL_SCOPES)
    upload = upload_file(tmp_path)
    refused = {}
    async with _server_on_the_app(secret) as mcp:
        tools = (await mcp.list_tools()).tools
        assert len(tools) > 30
        for tool in tools:
            result = await mcp.call_tool(tool.name, minimal_arguments(tool, upload))
            text = " ".join(getattr(block, "text", "") for block in result.content)
            if any(refusal in text for refusal in REFUSALS) or "500:" in text:
                refused[tool.name] = text
    assert refused == {}


async def test_a_read_token_is_refused_by_the_api_on_write_and_print_tools(
    unauthenticated_client, db_session, test_tenant, test_user, tmp_path
):
    """The server only lists in-scope tools, but the API is the authority (FR-007, SC-002)."""
    _, secret = await make_token(db_session, test_tenant, test_user, ["read"])
    upload = upload_file(tmp_path)
    not_refused = {}
    async with _server_on_the_app(secret) as mcp:
        for tool in (await mcp.list_tools()).tools:
            if tool.annotations.read_only_hint:
                continue
            result = await mcp.call_tool(tool.name, minimal_arguments(tool, upload))
            text = " ".join(getattr(block, "text", "") for block in result.content)
            if "403:" not in text or "is missing the" not in text:
                not_refused[tool.name] = text
    assert not_refused == {}
