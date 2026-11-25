"""Printer, spool, print job, production run and account tools against a mocked API."""

import pytest

from tests.mcp_server.conftest import result_error, result_json

pytestmark = pytest.mark.asyncio

PRINTER = "77777777-7777-4777-8777-777777777777"
OTHER = "88888888-8888-4888-8888-888888888888"


@pytest.mark.parametrize(
    "tool,args,path,expected_params",
    [
        ("list_printers", {"is_active": True}, "/printers", {"is_active": "true", "limit": "100"}),
        ("get_printer", {"printer_id": PRINTER}, f"/printers/{PRINTER}", {}),
        ("get_printer_status", {"printer_id": PRINTER}, f"/printers/{PRINTER}/status", {}),
        ("get_ams_slots", {"printer_id": PRINTER}, f"/printers/{PRINTER}/ams", {}),
        (
            "list_spools",
            {"search": "PLA", "low_stock_only": True},
            "/spools",
            {"search": "PLA", "low_stock_only": "true", "page": "1", "page_size": "20"},
        ),
        ("get_spool", {"spool_id": PRINTER}, f"/spools/{PRINTER}", {}),
        (
            "list_print_jobs",
            {"status": "queued", "printer_id": PRINTER},
            "/print-queue",
            {"status": "queued", "printer_id": PRINTER},
        ),
        ("get_print_job", {"job_id": PRINTER}, f"/print-queue/{PRINTER}", {}),
        (
            "list_production_runs",
            {"status": "completed", "start_date": "2026-11-01"},
            "/production-runs",
            {"status_filter": "completed", "start_date": "2026-11-01"},
        ),
        ("get_production_run", {"run_id": PRINTER}, f"/production-runs/{PRINTER}", {}),
        ("get_token_info", {}, "/api-tokens/current", {}),
    ],
)
async def test_read_tool_request_and_result(
    mock_api, mcp_client, tool, args, path, expected_params
):
    route = mock_api.get(path).respond(200, json={"ok": tool})
    async with mcp_client(["read"]) as client:
        result = await client.call_tool(tool, args)
    assert result_json(result) == {"ok": tool}
    params = route.calls.last.request.url.params
    for key, value in expected_params.items():
        assert params[key] == value


@pytest.mark.parametrize(
    "tool,arg",
    [
        ("get_printer", "printer_id"),
        ("get_spool", "spool_id"),
        ("get_print_job", "job_id"),
        ("get_production_run", "run_id"),
    ],
)
async def test_read_tool_not_found(mock_api, mcp_client, tool, arg):
    mock_api.route(path__regex=rf".*/{OTHER}$").respond(404, json={"detail": "Not found"})
    async with mcp_client(["read"]) as client:
        result = await client.call_tool(tool, {arg: OTHER})
    assert "404: Not found" in result_error(result)


async def test_server_error_without_json_body(mock_api, mcp_client):
    mock_api.get("/printers").respond(502, text="Bad gateway")
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("list_printers", {})
    assert "502: Bad gateway" in result_error(result)


async def test_token_info_available_with_any_scope(mcp_client):
    async with mcp_client(["print"]) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert "get_token_info" in names
    assert "list_printers" not in names
