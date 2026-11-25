"""Spool tools: filament spools in stock (read only)."""

from typing import Any, Optional

from app.mcp_server.client import BatchivoClient
from app.mcp_server.tools.base import ToolSpec, call_api, read_tool


def build_tools(client: BatchivoClient) -> list[ToolSpec]:
    """The spool tool group."""

    async def list_spools(
        search: Optional[str] = None,
        material_type_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        low_stock_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> Any:
        params = {
            "search": search,
            "material_type_id": material_type_id,
            "is_active": is_active,
            "low_stock_only": str(low_stock_only).lower(),
            "page": page,
            "page_size": page_size,
        }
        return await call_api(client.get("/spools", params=params))

    async def get_spool(spool_id: str) -> Any:
        return await call_api(client.get(f"/spools/{spool_id}"))

    return [
        read_tool(
            "list_spools",
            "List filament spools; search by spool id, brand or colour; page_size max 100.",
            list_spools,
        ),
        read_tool("get_spool", "Get one spool with its remaining weight.", get_spool),
    ]
