"""Minimal valid arguments for any MCP tool, derived from its published input schema.

Used by the tests that run *every* tool (error paths, reachability through the real
API) so a new tool is covered without anyone adding it to a list.
"""

from pathlib import Path
from typing import Any

PLACEHOLDER_ID = "33333333-3333-4333-8333-333333333333"

#: Tools that need one of several optional arguments to reach the API at all.
EXTRA_ARGUMENTS: dict[str, dict[str, Any]] = {
    "prepare_print": {"model_file_id": PLACEHOLDER_ID},
    # Spec 009: exactly one owner id is needed to build the path.
    "get_design_brief": {"brief_id": PLACEHOLDER_ID},
    "start_design_brief": {"idea_id": PLACEHOLDER_ID},
}


def _value(name: str, schema: dict[str, Any], defs: dict[str, Any], upload: Path) -> Any:
    if "$ref" in schema:
        schema = defs[schema["$ref"].rsplit("/", 1)[-1]]
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for option in schema.get("anyOf", []):
        if option.get("type") != "null":
            return _value(name, option, defs, upload)
    kind = schema.get("type")
    if kind == "string":
        if name == "file_path":
            return str(upload)
        return PLACEHOLDER_ID if name.endswith("_id") or name.endswith("token") else "x"
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        return {}
    raise AssertionError(f"no placeholder for {name}: {schema}")


def minimal_arguments(tool: Any, upload: Path) -> dict[str, Any]:
    """Required arguments of an MCP tool (`mcp.types.Tool`), filled with placeholders."""
    schema = tool.input_schema
    defs = schema.get("$defs", {})
    properties = schema.get("properties", {})
    arguments = {
        name: _value(name, properties[name], defs, upload) for name in schema.get("required", [])
    }
    arguments.update(EXTRA_ARGUMENTS.get(tool.name, {}))
    return arguments


def upload_file(directory: Path) -> Path:
    """A small file the upload tools can send."""
    path = directory / "upload.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nplaceholder")
    return path
