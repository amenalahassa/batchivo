"""Print send tools against a mocked API (US4, FR-015)."""

import json
from urllib.parse import parse_qs

import pytest

from tests.mcp_server.conftest import result_error, result_json

pytestmark = pytest.mark.asyncio

PRINTER = "77777777-7777-4777-8777-777777777777"
MODEL_FILE = "99999999-9999-4999-8999-999999999999"
SEND = "12121212-1212-4121-8121-121212121212"

MAPPING = [
    {"filament_id": 1, "slot": {"kind": "ams", "ams_id": 0, "tray_id": 2}},
    {"filament_id": 2, "slot": {"kind": "external"}},
]
SUMMARY = {
    "id": SEND,
    "confirmation_token": "opaque",
    "warnings": [{"code": "material_mismatch", "message": "Plate expects PLA, slot holds PETG"}],
    "requires_acknowledgement": True,
}


async def test_prepare_with_model_file(mock_api, mcp_client):
    route = mock_api.post(f"/printers/{PRINTER}/prints/prepare").respond(201, json=SUMMARY)
    async with mcp_client(["print"]) as client:
        result = await client.call_tool(
            "prepare_print",
            {
                "printer_id": PRINTER,
                "plate": 2,
                "ams_mapping": MAPPING,
                "model_file_id": MODEL_FILE,
            },
        )
    assert result_json(result)["confirmation_token"] == "opaque"
    form = parse_qs(route.calls.last.request.content.decode())
    assert form["plate"] == ["2"]
    assert form["model_file_id"] == [MODEL_FILE]
    assert json.loads(form["ams_mapping"][0]) == MAPPING


async def test_prepare_with_local_file(mock_api, mcp_client, tmp_path):
    sliced = tmp_path / "dragon.gcode.3mf"
    sliced.write_bytes(b"PK\x03\x04zip")
    route = mock_api.post(f"/printers/{PRINTER}/prints/prepare").respond(201, json=SUMMARY)
    async with mcp_client(["print"]) as client:
        await client.call_tool(
            "prepare_print",
            {"printer_id": PRINTER, "plate": 1, "ams_mapping": MAPPING, "file_path": str(sliced)},
        )
    content = route.calls.last.request.content
    assert b'name="file"; filename="dragon.gcode.3mf"' in content
    assert b'name="plate"' in content and b'name="ams_mapping"' in content


async def test_prepare_needs_exactly_one_source(mock_api, mcp_client):
    async with mcp_client(["print"]) as client:
        neither = await client.call_tool(
            "prepare_print", {"printer_id": PRINTER, "plate": 1, "ams_mapping": MAPPING}
        )
    assert "exactly one of model_file_id or file_path" in result_error(neither)


async def test_prepare_api_refusal_reaches_agent(mock_api, mcp_client):
    mock_api.post(f"/printers/{PRINTER}/prints/prepare").respond(
        409, json={"detail": "Send not available: Developer Mode is off"}
    )
    async with mcp_client(["print"]) as client:
        result = await client.call_tool(
            "prepare_print",
            {
                "printer_id": PRINTER,
                "plate": 1,
                "ams_mapping": MAPPING,
                "model_file_id": MODEL_FILE,
            },
        )
    assert "409: Send not available" in result_error(result)


async def test_confirm_never_acknowledges_by_default(mock_api, mcp_client):
    route = mock_api.post(f"/printers/{PRINTER}/prints/confirm").respond(
        422, json={"detail": "Warnings must be acknowledged"}
    )
    async with mcp_client(["print"]) as client:
        result = await client.call_tool(
            "confirm_print", {"printer_id": PRINTER, "confirmation_token": "opaque"}
        )
    assert json.loads(route.calls.last.request.content) == {
        "confirmation_token": "opaque",
        "acknowledge_warnings": False,
    }
    assert "Warnings must be acknowledged" in result_error(result)


async def test_confirm_with_explicit_acknowledgement(mock_api, mcp_client):
    route = mock_api.post(f"/printers/{PRINTER}/prints/confirm").respond(
        200, json={"id": SEND, "status": "started"}
    )
    async with mcp_client(["print"]) as client:
        result = await client.call_tool(
            "confirm_print",
            {"printer_id": PRINTER, "confirmation_token": "opaque", "acknowledge_warnings": True},
        )
    assert result_json(result)["status"] == "started"
    assert json.loads(route.calls.last.request.content)["acknowledge_warnings"] is True


async def test_list_and_get_print_sends(mock_api, mcp_client):
    listing = mock_api.get(f"/printers/{PRINTER}/prints").respond(200, json={"items": []})
    mock_api.get(f"/printers/{PRINTER}/prints/{SEND}").respond(200, json={"id": SEND})
    async with mcp_client(["read"]) as client:
        await client.call_tool("list_print_sends", {"printer_id": PRINTER, "limit": 5})
        result = await client.call_tool("get_print_send", {"printer_id": PRINTER, "send_id": SEND})
    assert listing.calls.last.request.url.params["limit"] == "5"
    assert result_json(result)["id"] == SEND


async def test_annotations_and_scope(mcp_client):
    async with mcp_client(["print"]) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert tools["confirm_print"].annotations.destructive_hint is True
    assert tools["confirm_print"].annotations.read_only_hint is False
    assert tools["prepare_print"].annotations.destructive_hint is False

    async with mcp_client(["read", "write", "genai"]) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert "prepare_print" not in names and "confirm_print" not in names
    assert "list_print_sends" in names
