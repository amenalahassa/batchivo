"""Production tools: print jobs (queue) and production runs (read only)."""

from typing import Any, Optional

from app.mcp_server.client import BatchivoClient
from app.mcp_server.tools.base import ToolSpec, call_api, read_tool


def build_tools(client: BatchivoClient) -> list[ToolSpec]:
    """The print job and production run tool group."""

    async def list_print_jobs(
        status: Optional[str] = None,
        printer_id: Optional[str] = None,
        priority: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Any:
        params = {
            "status": status,
            "printer_id": printer_id,
            "priority": priority,
            "page": page,
            "page_size": page_size,
        }
        return await call_api(client.get("/print-queue", params=params))

    async def get_print_job(job_id: str) -> Any:
        return await call_api(client.get(f"/print-queue/{job_id}"))

    async def list_production_runs(
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Any:
        params = {
            "status_filter": status,
            "start_date": start_date,
            "end_date": end_date,
            "skip": skip,
            "limit": limit,
        }
        return await call_api(client.get("/production-runs", params=params))

    async def get_production_run(run_id: str) -> Any:
        return await call_api(client.get(f"/production-runs/{run_id}"))

    return [
        read_tool(
            "list_print_jobs",
            "List print jobs in the queue, filtered by status, printer or priority.",
            list_print_jobs,
        ),
        read_tool("get_print_job", "Get one print job.", get_print_job),
        read_tool(
            "list_production_runs",
            "List production runs, filtered by status or date range (ISO dates).",
            list_production_runs,
        ),
        read_tool(
            "get_production_run",
            "Get one production run with its items, materials and plates.",
            get_production_run,
        ),
    ]
