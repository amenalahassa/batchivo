"""Build and run the Batchivo MCP server (spec 010, contracts/mcp-tools.md).

At startup the server asks the API what its token may do
(`GET /api-tokens/current`) and registers only the tools within those scopes.
That is a convenience for the agent; the API enforces the scopes regardless.
"""

import logging
import sys
from collections.abc import Iterable
from types import ModuleType
from typing import Optional

import httpx
from mcp.server.mcpserver import MCPServer

from app.mcp_server.client import BatchivoApiError, BatchivoClient, BatchivoUnreachable
from app.mcp_server.config import (
    EXIT_STARTUP_FAILURE,
    McpConfig,
    StartupError,
    configure_logging,
    load_config,
    mask_secrets,
)
from app.mcp_server.tools import GROUPS
from app.mcp_server.tools.base import ANY, ToolSpec

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Batchivo is a 3D-print business platform. These tools read and write the operator's shop "
    "through Batchivo's own API, with the operator's permissions. Before starting a print with "
    "confirm_print, always show the operator the summary and warnings returned by prepare_print."
)


def tools_for_scopes(
    client: BatchivoClient, scopes: Iterable[str], groups: Optional[list[ModuleType]] = None
) -> list[ToolSpec]:
    """Every tool of every group that the given scopes allow."""
    held = set(scopes)
    selected: list[ToolSpec] = []
    for group in groups if groups is not None else GROUPS:
        for spec in group.build_tools(client):
            if spec.scope == ANY or spec.scope in held:
                selected.append(spec)
    return selected


def build_server(
    client: BatchivoClient, scopes: Iterable[str], groups: Optional[list[ModuleType]] = None
) -> MCPServer:
    """An MCP server exposing the tools the token's scopes allow."""
    server = MCPServer(name="batchivo", instructions=INSTRUCTIONS)
    for spec in tools_for_scopes(client, scopes, groups):
        server.add_tool(
            spec.handler,
            name=spec.name,
            description=spec.description,
            annotations=spec.annotations,
            structured_output=False,
        )
    return server


async def fetch_scopes(client: BatchivoClient) -> list[str]:
    """Ask the API what this token may do; a refused or unreachable API stops startup."""
    try:
        current = await client.get("/api-tokens/current")
    except BatchivoUnreachable as exc:
        raise StartupError(str(exc)) from None
    except BatchivoApiError as exc:
        if exc.status_code == 401:
            raise StartupError(
                "Batchivo refused the API token (revoked, expired or unknown). "
                "Create a new one in Settings > API tokens."
            ) from None
        raise StartupError(f"Batchivo answered {exc}") from None
    return list(current.get("scopes", []))


async def create_server(
    config: McpConfig, transport: Optional[httpx.AsyncBaseTransport] = None
) -> tuple[MCPServer, BatchivoClient]:
    """Connect to Batchivo, check the token, and build the server."""
    client = BatchivoClient(config.api_url, config.token, transport=transport)
    try:
        scopes = await fetch_scopes(client)
    except StartupError:
        await client.aclose()
        raise
    server = build_server(client, scopes)
    logger.info(f"Batchivo MCP server ready for {config.api_url} with scopes {sorted(scopes)}")
    return server, client


async def serve(config: McpConfig) -> None:
    """Run over stdio until the client disconnects."""
    server, client = await create_server(config)
    try:
        await server.run_stdio_async()
    finally:
        await client.aclose()


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point of `python -m app.mcp_server`. Returns the exit code."""
    import anyio

    configure_logging()
    try:
        config = load_config()
        anyio.run(serve, config)
    except StartupError as exc:
        sys.stderr.write(mask_secrets(f"batchivo-mcp: {exc}") + "\n")
        return EXIT_STARTUP_FAILURE
    except KeyboardInterrupt:
        return 0
    return 0
