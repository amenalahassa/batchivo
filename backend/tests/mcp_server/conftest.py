"""Fixtures for the MCP server tests: a respx-mocked Batchivo API and an in-memory MCP client.

No database: the MCP server only ever talks HTTP to the API (FR-013), so every
test here mocks that API with respx and drives the server through the real
MCP protocol (`mcp.client.Client` over an in-memory transport).
"""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
import respx
from mcp.client import Client

from app.mcp_server.client import BatchivoClient
from app.mcp_server.server import build_server

API_URL = "http://batchivo.test"
API = f"{API_URL}/api/v1"
TOKEN = "bvt_testtest_" + "s" * 43
ALL_SCOPES = ["genai", "print", "read", "write"]


@pytest.fixture
def mock_api() -> respx.MockRouter:
    """A respx router on the test API; unmatched requests fail the test."""
    with respx.mock(base_url=API, assert_all_called=False) as router:
        yield router


@pytest.fixture
def batchivo_client() -> BatchivoClient:
    return BatchivoClient(API_URL, TOKEN)


@pytest.fixture
def mcp_client(batchivo_client) -> Callable[..., Any]:
    """`async with mcp_client(scopes) as client:` -> an MCP client of a server with those scopes."""

    @asynccontextmanager
    async def _open(scopes: list[str] = ALL_SCOPES) -> AsyncIterator[Client]:
        server = build_server(batchivo_client, scopes)
        async with Client(server) as client:
            yield client

    return _open


def result_json(result: Any) -> Any:
    """The JSON a tool returned, parsed from its text content."""
    assert not result.is_error, result.content
    texts = [block.text for block in result.content if getattr(block, "type", "") == "text"]
    assert texts, result.content
    if len(texts) == 1:
        return json.loads(texts[0])
    return [json.loads(t) for t in texts]


def result_error(result: Any) -> str:
    """The error text of a failed tool call."""
    assert result.is_error, result.content
    return " ".join(block.text for block in result.content if hasattr(block, "text"))


@pytest.fixture(autouse=True)
def clean_tables():
    """These tests touch no database: replace the suite-wide table cleaner with a no-op."""
    yield
