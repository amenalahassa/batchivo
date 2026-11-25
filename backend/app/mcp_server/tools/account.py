"""Account tool: what the token in use may do."""

from typing import Any

from app.mcp_server.client import BatchivoClient
from app.mcp_server.tools.base import ANY, ToolSpec, call_api


def build_tools(client: BatchivoClient) -> list[ToolSpec]:
    """The account tool group."""

    async def get_token_info() -> Any:
        return await call_api(client.get("/api-tokens/current"))

    return [
        ToolSpec(
            "get_token_info",
            "Show the API token in use: its name, scopes, expiry and shop.",
            ANY,
            True,
            False,
            get_token_info,
        )
    ]
