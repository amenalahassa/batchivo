"""Preflight tools against a mocked Batchivo API (spec 009 over 010).

The tools only forward to the 009 API: each test checks the request a tool
sends and that its answer (or error) reaches the agent. Reading needs `read`;
recording or changing anything needs `write`.
"""

import json

import pytest

from tests.mcp_server.conftest import result_error, result_json

pytestmark = pytest.mark.asyncio

IDEA = "66666666-6666-4666-8666-666666666666"
MODEL = "77777777-7777-4777-8777-777777777777"
BRIEF = "99999999-9999-4999-8999-999999999999"
FILE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
NOTE = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PRINTER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
RESULT = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
VERSION = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

READS = {
    "get_design_brief",
    "list_design_brief_revisions",
    "list_typed_notes",
    "lookup_calibration",
    "list_calibrations",
    "export_atelier_calibrations",
    "get_test_result",
    "list_test_results",
}
WRITES = {
    "start_design_brief",
    "update_design_brief",
    "add_typed_note",
    "dismiss_note",
    "record_calibration",
    "record_test_result",
    "update_test_result",
    "upload_test_result_photo",
}


async def _tool_names(mcp_client, scopes):
    async with mcp_client(scopes) as client:
        return {tool.name for tool in (await client.list_tools()).tools}


async def test_reads_need_read_and_writes_need_write(mcp_client):
    read_only = await _tool_names(mcp_client, ["read"])
    assert READS <= read_only
    assert not WRITES & read_only
    assert WRITES <= await _tool_names(mcp_client, ["read", "write"])


# ============================================
# Design briefs
# ============================================


@pytest.mark.parametrize(
    "arguments,path",
    [
        ({"idea_id": IDEA}, f"/ideas/{IDEA}/design-brief"),
        ({"model_id": MODEL}, f"/models/{MODEL}/design-brief"),
        ({"brief_id": BRIEF}, f"/design-briefs/{BRIEF}"),
    ],
)
async def test_get_design_brief_by_owner(mock_api, mcp_client, arguments, path):
    mock_api.get(path).respond(200, json={"id": BRIEF})
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("get_design_brief", arguments)
    assert result_json(result)["id"] == BRIEF


async def test_get_design_brief_needs_exactly_one_id(mcp_client):
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("get_design_brief", {"idea_id": IDEA, "model_id": MODEL})
    assert "exactly one" in result_error(result)


async def test_start_design_brief_with_intent_yaml(mock_api, mcp_client):
    route = mock_api.post(f"/models/{MODEL}/design-brief").respond(201, json={"id": BRIEF})
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "start_design_brief", {"model_id": MODEL, "intent_yaml": "schema_version: 1\n"}
        )
    assert result_json(result)["id"] == BRIEF
    assert json.loads(route.calls[0].request.content) == {"intent_yaml": "schema_version: 1\n"}


async def test_update_design_brief_groups_the_risk_part(mock_api, mcp_client):
    route = mock_api.patch(f"/design-briefs/{BRIEF}").respond(
        200, json={"id": BRIEF, "created_revisions": ["risk"]}
    )
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "update_design_brief",
            {
                "brief_id": BRIEF,
                "risk_class": "moyen",
                "risk_md": "# Risque",
                "steps": {"risk": "done"},
            },
        )
    assert result_json(result)["created_revisions"] == ["risk"]
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "risk": {"risk_class": "moyen", "risk_md": "# Risque", "triage": None},
        "steps": {"risk": "done"},
    }


async def test_list_design_brief_revisions(mock_api, mcp_client):
    route = mock_api.get(f"/design-briefs/{BRIEF}/revisions").respond(200, json=[])
    async with mcp_client(["read"]) as client:
        result = await client.call_tool(
            "list_design_brief_revisions", {"brief_id": BRIEF, "part": "intent"}
        )
    assert result_json(result) == []
    assert route.calls[0].request.url.params["part"] == "intent"


async def test_api_error_reaches_the_agent(mock_api, mcp_client):
    mock_api.patch(f"/design-briefs/{BRIEF}").respond(
        422, json={"detail": [{"loc": ["intent", "loads", 0, "duration"], "msg": "bad"}]}
    )
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "update_design_brief", {"brief_id": BRIEF, "intent": {"schema_version": 1}}
        )
    assert "duration" in result_error(result)


# ============================================
# Typed notes
# ============================================


async def test_add_typed_note_sends_its_type(mock_api, mcp_client):
    route = mock_api.post(f"/models/{MODEL}/files/{FILE}/notes").respond(201, json={"id": NOTE})
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "add_typed_note",
            {
                "model_id": MODEL,
                "file_id": FILE,
                "text": "Paroi trop fine",
                "position": [1, 2, 3],
                "normal": [0, 0, 1],
                "severity": "échec",
                "rule_id": "dfam.wall.extrusion-multiple",
                "measured_value": 0.6,
                "expected_value": 0.9,
                "value_unit": "mm",
            },
        )
    assert result_json(result)["id"] == NOTE
    body = json.loads(route.calls[0].request.content)
    assert body["source"] == "preflight"
    assert body["severity"] == "échec"
    assert body["rule_id"] == "dfam.wall.extrusion-multiple"
    assert (body["measured_value"], body["expected_value"]) == ("0.6", "0.9")


async def test_list_typed_notes_filters(mock_api, mcp_client):
    route = mock_api.get(f"/models/{MODEL}/file-notes").respond(200, json=[])
    async with mcp_client(["read"]) as client:
        await client.call_tool(
            "list_typed_notes", {"model_id": MODEL, "source": "preflight", "severity": "failure"}
        )
    params = route.calls[0].request.url.params
    assert (params["source"], params["severity"]) == ("preflight", "failure")


async def test_dismiss_note_sends_the_justification(mock_api, mcp_client):
    route = mock_api.patch(f"/models/{MODEL}/file-notes/{NOTE}").respond(
        200, json={"status": "dismissed"}
    )
    async with mcp_client(["write"]) as client:
        await client.call_tool(
            "dismiss_note", {"model_id": MODEL, "note_id": NOTE, "justification": "cosmetic"}
        )
    assert json.loads(route.calls[0].request.content) == {
        "status": "dismissed",
        "dismissal_reason": "cosmetic",
    }


# ============================================
# Calibrations
# ============================================


async def test_lookup_calibration(mock_api, mcp_client):
    route = mock_api.get("/calibrations/lookup").respond(200, json={"found": False})
    async with mcp_client(["read"]) as client:
        result = await client.call_tool(
            "lookup_calibration",
            {
                "printer_id": PRINTER,
                "fit_type": "slide",
                "orientation": "vertical",
                "material": "PLA",
            },
        )
    assert result_json(result) == {"found": False}
    assert route.calls[0].request.url.params["material"] == "PLA"


async def test_list_calibrations(mock_api, mcp_client):
    route = mock_api.get(f"/printers/{PRINTER}/calibrations").respond(200, json=[])
    async with mcp_client(["read"]) as client:
        await client.call_tool("list_calibrations", {"printer_id": PRINTER, "current_only": True})
    assert route.calls[0].request.url.params["current_only"] == "true"


async def test_export_atelier_calibrations(mock_api, mcp_client):
    mock_api.get("/calibrations/atelier").respond(200, json={"calibrations": []})
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("export_atelier_calibrations", {})
    assert result_json(result) == {"calibrations": []}


async def test_record_calibration_sends_an_exact_value(mock_api, mcp_client):
    route = mock_api.post(f"/printers/{PRINTER}/calibrations").respond(
        201, json={"value_mm": "0.150"}
    )
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "record_calibration",
            {
                "printer_id": PRINTER,
                "fit_type": "slide",
                "orientation": "vertical",
                "value_mm": 0.15,
                "provenance": "measured",
                "material": "PLA",
            },
        )
    assert result_json(result)["value_mm"] == "0.150"
    assert json.loads(route.calls[0].request.content)["value_mm"] == "0.15"


# ============================================
# Test results
# ============================================


async def test_record_test_result(mock_api, mcp_client):
    route = mock_api.post("/print-test-results").respond(201, json={"id": RESULT})
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "record_test_result",
            {
                "kind": "critical_zone",
                "outcome": "fail",
                "model_file_version_id": VERSION,
                "failure_mode": "rupture à l'encastrement à 7 kg",
                "measurements": [{"name": "load_kg", "value": 7}],
            },
        )
    assert result_json(result)["id"] == RESULT
    body = json.loads(route.calls[0].request.content)
    assert body["measurements"] == [{"name": "load_kg", "value": 7}]
    assert "print_job_id" not in body


async def test_update_test_result(mock_api, mcp_client):
    route = mock_api.patch(f"/print-test-results/{RESULT}").respond(200, json={"outcome": "pass"})
    async with mcp_client(["write"]) as client:
        await client.call_tool("update_test_result", {"result_id": RESULT, "outcome": "pass"})
    assert json.loads(route.calls[0].request.content) == {"outcome": "pass"}


async def test_upload_test_result_photo(mock_api, mcp_client, tmp_path):
    photo = tmp_path / "break.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    route = mock_api.post(f"/print-test-results/{RESULT}/photo").respond(
        200, json={"photo_available": True}
    )
    async with mcp_client(["write"]) as client:
        result = await client.call_tool(
            "upload_test_result_photo", {"result_id": RESULT, "file_path": str(photo)}
        )
    assert result_json(result)["photo_available"] is True
    assert b"break.png" in route.calls[0].request.content


async def test_get_and_list_test_results(mock_api, mcp_client):
    mock_api.get(f"/print-test-results/{RESULT}").respond(200, json={"id": RESULT})
    route = mock_api.get("/print-test-results").respond(200, json={"items": [], "total": 0})
    async with mcp_client(["read"]) as client:
        one = await client.call_tool("get_test_result", {"result_id": RESULT})
        many = await client.call_tool("list_test_results", {"model_id": MODEL, "outcome": "pass"})
    assert result_json(one)["id"] == RESULT
    assert result_json(many)["total"] == 0
    assert route.calls[0].request.url.params["outcome"] == "pass"
