"""What a tool is, and how its result or error reaches the agent (spec 010, contracts/mcp-tools.md).

A tool group is a module exposing `build_tools(client) -> list[ToolSpec]`.
Each tool is an async function with typed parameters (they become the tool's
input schema), closing over the `BatchivoClient`. `scope` decides whether the
tool is registered for a given token; the API enforces it again regardless.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.types import Image
from mcp_types import ToolAnnotations

from app.mcp_server.client import BatchivoApiError, BatchivoUnreachable, BinaryResponse

ToolScope = Literal["read", "write", "genai", "print", "any"]
ANY: ToolScope = "any"


@dataclass(frozen=True)
class ToolSpec:
    """One MCP tool mapped to one Batchivo API operation."""

    name: str
    description: str
    scope: ToolScope
    read_only: bool
    destructive: bool
    handler: Callable[..., Awaitable[Any]]

    @property
    def annotations(self) -> ToolAnnotations:
        if self.read_only:
            return ToolAnnotations(read_only_hint=True, destructive_hint=False)
        return ToolAnnotations(read_only_hint=False, destructive_hint=self.destructive)


def read_tool(name: str, description: str, handler: Callable[..., Awaitable[Any]]) -> ToolSpec:
    """A tool that only reads (scope `read`)."""
    return ToolSpec(name, description, "read", True, False, handler)


def write_tool(
    name: str,
    description: str,
    handler: Callable[..., Awaitable[Any]],
    *,
    scope: ToolScope = "write",
    destructive: bool = False,
) -> ToolSpec:
    """A tool that changes data (scope `write` unless said otherwise)."""
    return ToolSpec(name, description, scope, False, destructive, handler)


async def call_api(operation: Awaitable[Any]) -> Any:
    """Await an API call; turn its failure into a tool error the agent can read (FR-016)."""
    try:
        result = await operation
    except BatchivoApiError as exc:
        raise ToolError(str(exc)) from None
    except BatchivoUnreachable as exc:
        raise ToolError(str(exc)) from None
    except FileNotFoundError as exc:
        raise ToolError(str(exc)) from None
    if isinstance(result, BinaryResponse):
        subtype = result.content_type.split("/")[-1] if "/" in result.content_type else "png"
        return Image(data=result.content, format=subtype)
    # One JSON text block, whatever the shape: lists and empty bodies stay readable.
    return json.dumps(result, ensure_ascii=False, default=str)


def with_extra(body: dict[str, Any], extra_fields: dict[str, Any] | None) -> dict[str, Any]:
    """Drop unset fields, then merge `extra_fields` (fields added by later features pass through)."""
    merged = {k: v for k, v in body.items() if v is not None}
    if extra_fields:
        merged.update(extra_fields)
    return merged
