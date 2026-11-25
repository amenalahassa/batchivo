"""Idea write tools against a mocked API."""

import json

import pytest

from tests.mcp_server.conftest import result_error, result_json

pytestmark = pytest.mark.asyncio

IDEA = "11111111-1111-4111-8111-111111111111"
ENTRY = "22222222-2222-4222-8222-222222222222"


def _body(route):
    return json.loads(route.calls.last.request.content)


async def test_create_idea_sends_only_set_fields(mock_api, mcp_client):
    route = mock_api.post("/ideas").respond(201, json={"id": IDEA, "title": "Hook"})
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "create_idea", {"title": "Hook", "tags": ["wall"], "scores": {"gap": 4}}
        )
    assert result_json(result)["id"] == IDEA
    assert _body(route) == {
        "title": "Hook",
        "status": "inbox",
        "source": "manual",
        "tags": ["wall"],
        "scores": {"gap": 4},
    }


async def test_create_idea_validation_error_is_readable(mock_api, mcp_client):
    mock_api.post("/ideas").respond(
        422,
        json={
            "detail": [{"loc": ["body", "title"], "msg": "String should have at least 1 character"}]
        },
    )
    async with mcp_client(["write"]) as client:
        result = await client.call_tool("create_idea", {"title": ""})
    assert "422: title: String should have at least 1 character" in result_error(result)


async def test_missing_scope_message_reaches_the_agent(mock_api, mcp_client):
    mock_api.post("/ideas").respond(403, json={"detail": "API token is missing the 'write' scope"})
    async with mcp_client(["write"]) as client:
        result = await client.call_tool("create_idea", {"title": "x"})
    assert "403: API token is missing the 'write' scope" in result_error(result)


async def test_update_idea(mock_api, mcp_client):
    route = mock_api.patch(f"/ideas/{IDEA}").respond(200, json={"id": IDEA})
    async with mcp_client(["write"]) as client:
        await client.call_tool(
            "update_idea", {"idea_id": IDEA, "status": "ready", "archived": False}
        )
    assert _body(route) == {"status": "ready", "archived": False}


async def test_add_idea_entry(mock_api, mcp_client):
    route = mock_api.post(f"/ideas/{IDEA}/entries").respond(201, json={"id": ENTRY})
    async with mcp_client(["write"]) as client:
        await client.call_tool(
            "add_idea_entry", {"idea_id": IDEA, "kind": "note", "body": "Needs 3 mm walls"}
        )
    assert _body(route) == {"kind": "note", "body": "Needs 3 mm walls"}


async def test_upload_idea_image_from_local_file(mock_api, mcp_client, tmp_path):
    picture = tmp_path / "sketch.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    route = mock_api.post(f"/ideas/{IDEA}/entries/images").respond(201, json={"created": 1})
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "upload_idea_image", {"idea_id": IDEA, "file_path": str(picture), "kind": "sketch"}
        )
    assert result_json(result) == {"created": 1}
    request = route.calls.last.request
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="files"; filename="sketch.png"' in request.content
    assert b'name="kind"' in request.content and b"sketch" in request.content


async def test_upload_idea_image_missing_file(mock_api, mcp_client, tmp_path):
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "upload_idea_image", {"idea_id": IDEA, "file_path": str(tmp_path / "none.png")}
        )
    assert "No file at" in result_error(result)


async def test_update_idea_entry(mock_api, mcp_client):
    route = mock_api.patch(f"/ideas/{IDEA}/entries/{ENTRY}").respond(200, json={})
    async with mcp_client(["write"]) as client:
        await client.call_tool(
            "update_idea_entry", {"idea_id": IDEA, "entry_id": ENTRY, "pinned": True}
        )
    assert _body(route) == {"pinned": True}


async def test_add_idea_iteration(mock_api, mcp_client):
    route = mock_api.post(f"/ideas/{IDEA}/iterations").respond(201, json={})
    async with mcp_client(["write"]) as client:
        await client.call_tool("add_idea_iteration", {"idea_id": IDEA, "note": "v2: thicker"})
    assert _body(route) == {"note": "v2: thicker"}


async def test_import_ideas(mock_api, mcp_client):
    route = mock_api.post("/ideas/import").respond(200, json={"created": [], "skipped": []})
    items = [{"title": "Cable clip", "tags": ["desk"], "report_score": 18}]
    async with mcp_client(["write"]) as client:
        await client.call_tool("import_ideas", {"items": items, "dry_run": True})
    assert _body(route) == {"items": items, "dry_run": True}


async def test_parse_idea_report(mock_api, mcp_client):
    route = mock_api.post("/ideas/import/parse-report").respond(
        200, json={"items": [], "warnings": []}
    )
    async with mcp_client(["write"]) as client:
        await client.call_tool("parse_idea_report", {"text": "# Report"})
    assert _body(route) == {"text": "# Report"}


async def test_convert_idea(mock_api, mcp_client):
    route = mock_api.post(f"/ideas/{IDEA}/convert").respond(200, json={"model_id": "m"})
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "convert_idea", {"idea_id": IDEA, "target": "model", "name": "Hook v1"}
        )
    assert result_json(result) == {"model_id": "m"}
    assert _body(route) == {"target": "model", "name": "Hook v1", "include_images": True}


async def test_write_tools_annotations(mcp_client):
    async with mcp_client(["write"]) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    for name in ("create_idea", "update_idea", "add_idea_entry", "convert_idea"):
        assert tools[name].annotations.read_only_hint is False
        assert tools[name].annotations.destructive_hint is False
