"""Idea read tools against a mocked API."""

import httpx
import pytest

from tests.mcp_server.conftest import TOKEN, result_error, result_json

pytestmark = pytest.mark.asyncio

IDEA = "11111111-1111-4111-8111-111111111111"
ENTRY = "22222222-2222-4222-8222-222222222222"


async def test_list_ideas_passes_every_filter(mock_api, mcp_client):
    route = mock_api.get("/ideas").respond(200, json={"items": [{"title": "Hook"}], "total": 1})
    async with mcp_client(["read"]) as client:
        result = await client.call_tool(
            "list_ideas",
            {
                "status": ["inbox", "ready"],
                "tag": ["kitchen", "wall"],
                "source": "manual",
                "search": "hook",
                "archived": "all",
                "sort": "score",
                "skip": 20,
                "limit": 10,
            },
        )
    assert result_json(result) == {"items": [{"title": "Hook"}], "total": 1}
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    params = request.url.params
    assert params.get_list("status") == ["inbox", "ready"]
    assert params.get_list("tag") == ["kitchen", "wall"]
    assert params["source"] == "manual"
    assert params["search"] == "hook"
    assert params["archived"] == "all"
    assert params["sort"] == "score"
    assert params["skip"] == "20"
    assert params["limit"] == "10"


async def test_list_ideas_defaults_omit_unset_filters(mock_api, mcp_client):
    route = mock_api.get("/ideas").respond(200, json={"items": [], "total": 0})
    async with mcp_client(["read"]) as client:
        await client.call_tool("list_ideas", {})
    params = route.calls.last.request.url.params
    assert "status" not in params and "tag" not in params and "search" not in params


async def test_list_idea_tags(mock_api, mcp_client):
    mock_api.get("/ideas/tags").respond(200, json=["kitchen"])
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("list_idea_tags", {})
    assert result_json(result) == ["kitchen"]


async def test_get_idea_and_not_found(mock_api, mcp_client):
    mock_api.get(f"/ideas/{IDEA}").respond(200, json={"id": IDEA, "title": "Hook"})
    other = "33333333-3333-4333-8333-333333333333"
    mock_api.get(f"/ideas/{other}").respond(404, json={"detail": "Idea not found"})
    async with mcp_client(["read"]) as client:
        found = await client.call_tool("get_idea", {"idea_id": IDEA})
        missing = await client.call_tool("get_idea", {"idea_id": other})
    assert result_json(found)["title"] == "Hook"
    assert "404: Idea not found" in result_error(missing)


async def test_list_idea_entries(mock_api, mcp_client):
    route = mock_api.get(f"/ideas/{IDEA}/entries").respond(200, json={"items": []})
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("list_idea_entries", {"idea_id": IDEA, "archived": True})
    assert result_json(result) == {"items": []}
    assert route.calls.last.request.url.params["archived"] == "true"


async def test_get_idea_entry_image_returns_image_content(mock_api, mcp_client):
    png = b"\x89PNG\r\n\x1a\nfake"
    mock_api.get(f"/ideas/{IDEA}/entries/{ENTRY}/image").respond(
        200, content=png, headers={"content-type": "image/png"}
    )
    async with mcp_client(["read"]) as client:
        result = await client.call_tool(
            "get_idea_entry_image", {"idea_id": IDEA, "entry_id": ENTRY}
        )
    assert not result.is_error
    image = result.content[0]
    assert image.type == "image"
    assert image.mime_type == "image/png"


async def test_unreachable_api_is_a_tool_error(mock_api, mcp_client):
    mock_api.get("/ideas/tags").mock(side_effect=httpx.ConnectError("refused"))
    async with mcp_client(["read"]) as client:
        first = await client.call_tool("list_idea_tags", {})
        mock_api.get("/ideas/tags").respond(200, json=[])
        second = await client.call_tool("list_idea_tags", {})
    assert "could not be reached" in result_error(first)
    # The server keeps running after the failure.
    assert result_json(second) == []


async def test_read_tools_are_read_only(mcp_client):
    async with mcp_client(["read"]) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in ("list_ideas", "list_idea_tags", "get_idea", "list_idea_entries"):
        assert tools[name].annotations.read_only_hint is True
