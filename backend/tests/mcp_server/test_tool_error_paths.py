"""Every MCP tool hands the API's refusal to the agent (SC-005, FR-016).

Derived from the server's own tool list, so a tool added later is covered by
this test without being named in it.
"""

import pytest

from tests.mcp_server.conftest import result_error
from tests.mcp_server.tool_args import minimal_arguments, upload_file

pytestmark = pytest.mark.asyncio


async def test_every_tool_reports_the_api_error(mock_api, mcp_client, tmp_path):
    route = mock_api.route().respond(409, json={"detail": "Conflict from the API"})
    upload = upload_file(tmp_path)
    async with mcp_client() as client:
        tools = (await client.list_tools()).tools
        assert len(tools) > 30
        failures = {}
        for tool in tools:
            calls_before = route.call_count
            result = await client.call_tool(tool.name, minimal_arguments(tool, upload))
            text = " ".join(getattr(b, "text", "") for b in result.content)
            if route.call_count == calls_before:
                failures[tool.name] = f"never called the API: {text}"
            elif not result.is_error or "409: Conflict from the API" not in result_error(result):
                failures[tool.name] = text
    assert failures == {}


async def test_every_tool_reports_an_unreachable_api(mock_api, mcp_client, tmp_path):
    import httpx

    mock_api.route().mock(side_effect=httpx.ConnectError("refused"))
    upload = upload_file(tmp_path)
    async with mcp_client() as client:
        tools = (await client.list_tools()).tools
        failures = {}
        for tool in tools:
            result = await client.call_tool(tool.name, minimal_arguments(tool, upload))
            if not result.is_error or "could not be reached" not in result_error(result):
                failures[tool.name] = " ".join(getattr(b, "text", "") for b in result.content)
    assert failures == {}
