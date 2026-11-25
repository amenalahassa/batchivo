"""Printer tools: printers, live status and AMS slots (read only)."""

from typing import Any, Optional

from app.mcp_server.client import BatchivoClient
from app.mcp_server.tools.base import ToolSpec, call_api, read_tool


def build_tools(client: BatchivoClient) -> list[ToolSpec]:
    """The printer tool group."""

    async def list_printers(
        is_active: Optional[bool] = None, skip: int = 0, limit: int = 100
    ) -> Any:
        params = {"is_active": is_active, "skip": skip, "limit": limit}
        return await call_api(client.get("/printers", params=params))

    async def get_printer(printer_id: str) -> Any:
        return await call_api(client.get(f"/printers/{printer_id}"))

    async def get_printer_status(printer_id: str) -> Any:
        return await call_api(client.get(f"/printers/{printer_id}/status"))

    async def get_ams_slots(printer_id: str) -> Any:
        return await call_api(client.get(f"/printers/{printer_id}/ams"))

    return [
        read_tool("list_printers", "List the shop's printers.", list_printers),
        read_tool("get_printer", "Get one printer's settings.", get_printer),
        read_tool(
            "get_printer_status",
            "Get a connected printer's live status (state, progress, temperatures).",
            get_printer_status,
        ),
        read_tool(
            "get_ams_slots",
            "List a printer's AMS slots and the spool Batchivo believes is in each.",
            get_ams_slots,
        ),
    ]
