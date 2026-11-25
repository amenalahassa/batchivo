"""Model, file version and pinned note tools against a mocked API."""

import json

import pytest

from tests.mcp_server.conftest import result_error, result_json

pytestmark = pytest.mark.asyncio

MODEL = "44444444-4444-4444-8444-444444444444"
FILE = "55555555-5555-4555-8555-555555555555"
NOTE = "66666666-6666-4666-8666-666666666666"


async def test_list_models(mock_api, mcp_client):
    route = mock_api.get("/models").respond(200, json={"models": [], "total": 0})
    async with mcp_client(["read"]) as client:
        await client.call_tool("list_models", {"search": "hook", "limit": 5})
    params = route.calls.last.request.url.params
    assert params["search"] == "hook" and params["limit"] == "5" and params["skip"] == "0"


async def test_get_model(mock_api, mcp_client):
    mock_api.get(f"/models/{MODEL}").respond(200, json={"id": MODEL})
    async with mcp_client(["read"]) as client:
        assert result_json(await client.call_tool("get_model", {"model_id": MODEL}))["id"] == MODEL


async def test_list_model_files(mock_api, mcp_client):
    route = mock_api.get(f"/models/{MODEL}/files").respond(200, json=[])
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("list_model_files", {"model_id": MODEL, "file_type": "stl"})
    assert result_json(result) == []
    assert route.calls.last.request.url.params["file_type"] == "stl"


async def test_list_file_versions(mock_api, mcp_client):
    mock_api.get(f"/models/{MODEL}/file-versions").respond(200, json=[{"version": 3}])
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("list_file_versions", {"model_id": MODEL})
    assert result_json(result) == [{"version": 3}]


async def test_list_file_notes_filters_and_passthrough(mock_api, mcp_client):
    route = mock_api.get(f"/models/{MODEL}/file-notes").respond(200, json=[])
    async with mcp_client(["read"]) as client:
        await client.call_tool(
            "list_file_notes",
            {"model_id": MODEL, "status": "open", "extra_filters": {"severity": "warning"}},
        )
    params = route.calls.last.request.url.params
    assert params["status"] == "open"
    assert params["include_archived"] == "false"
    assert params["severity"] == "warning"


async def test_list_file_notes_not_found(mock_api, mcp_client):
    mock_api.get(f"/models/{MODEL}/file-notes").respond(404, json={"detail": "Model not found"})
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("list_file_notes", {"model_id": MODEL})
    assert "404: Model not found" in result_error(result)


async def test_add_file_note_with_extra_fields(mock_api, mcp_client):
    route = mock_api.post(f"/models/{MODEL}/files/{FILE}/notes").respond(201, json={"id": NOTE})
    async with mcp_client(["write"]) as client:
        await client.call_tool(
            "add_file_note",
            {
                "model_id": MODEL,
                "file_id": FILE,
                "text": "Wall too thin",
                "position": [1.0, 2.0, 3.0],
                "normal": [0.0, 0.0, 1.0],
                "extra_fields": {"severity": "warning"},
            },
        )
    assert json.loads(route.calls.last.request.content) == {
        "text": "Wall too thin",
        "position": [1.0, 2.0, 3.0],
        "normal": [0.0, 0.0, 1.0],
        "severity": "warning",
    }


async def test_update_file_note_resolve(mock_api, mcp_client):
    route = mock_api.patch(f"/models/{MODEL}/file-notes/{NOTE}").respond(200, json={})
    async with mcp_client(["write"]) as client:
        await client.call_tool(
            "update_file_note",
            {
                "model_id": MODEL,
                "note_id": NOTE,
                "status": "resolved",
                "resolved_in_version_id": FILE,
            },
        )
    assert json.loads(route.calls.last.request.content) == {
        "status": "resolved",
        "resolved_in_version_id": FILE,
    }


async def test_carry_forward_note(mock_api, mcp_client):
    route = mock_api.post(f"/models/{MODEL}/file-notes/{NOTE}/carry-forward").respond(201, json={})
    async with mcp_client(["write"]) as client:
        await client.call_tool(
            "carry_forward_note", {"model_id": MODEL, "note_id": NOTE, "target_file_id": FILE}
        )
    assert json.loads(route.calls.last.request.content) == {"target_file_id": FILE}
