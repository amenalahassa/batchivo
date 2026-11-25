"""MCP tool groups (spec 010, contracts/mcp-tools.md §Extension pattern).

To add a group (008 genai, 009 design briefs and calibrations): write
`tools/<group>.py` exposing `build_tools(client) -> list[ToolSpec]`, append the
module to `GROUPS`, add its routes to `app/auth/api_token_policy.py`, and its
tests to `tests/mcp_server/test_tools_<group>.py`.
"""

from types import ModuleType

from app.mcp_server.tools import account, ideas, models, print_sends, printers, production, spools

GROUPS: list[ModuleType] = [account, ideas, models, printers, spools, production, print_sends]
