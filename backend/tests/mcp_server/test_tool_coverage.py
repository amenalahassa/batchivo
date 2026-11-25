"""Every MCP tool is declared consistently and tested (SC-005)."""

from pathlib import Path

from app.mcp_server.client import BatchivoClient
from app.mcp_server.tools import GROUPS
from app.mcp_server.tools.base import ToolSpec

HERE = Path(__file__).parent
SCOPES = {"read", "write", "genai", "print", "any"}


def _all_tools() -> list[ToolSpec]:
    client = BatchivoClient("http://unused.test", "bvt_unused")
    return [spec for group in GROUPS for spec in group.build_tools(client)]


def test_names_unique_and_scopes_known():
    tools = _all_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names))
    for tool in tools:
        assert tool.scope in SCOPES, tool.name
        assert tool.description.strip(), tool.name


def test_annotations_match_kind():
    for tool in _all_tools():
        if tool.scope in ("read", "any"):
            assert tool.read_only and not tool.destructive, tool.name
        else:
            assert not tool.read_only, tool.name
    destructive = {t.name for t in _all_tools() if t.destructive}
    assert destructive == {"confirm_print"}


def test_every_tool_has_a_test():
    sources = "\n".join(p.read_text(encoding="utf-8") for p in HERE.glob("test_tools_*.py"))
    untested = [t.name for t in _all_tools() if f'"{t.name}"' not in sources]
    assert untested == []
