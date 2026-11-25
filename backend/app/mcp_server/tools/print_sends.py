"""Print send tools: prepare, confirm, follow a send to a Bambu printer (011 API).

Starting a print needs the `print` scope, a separate opt-in on the token.
`confirm_print` is declared destructive, so the agent's client asks the
operator before running it, and it never acknowledges spool warnings unless
told to explicitly (FR-015).
"""

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.mcp_server.client import BatchivoClient
from app.mcp_server.tools.base import ToolSpec, call_api, read_tool, write_tool
from mcp.server.mcpserver.exceptions import ToolError


class SlotChoice(BaseModel):
    """Which AMS tray (or the external holder) feeds one filament of the plate."""

    kind: Literal["ams", "external"] = "ams"
    ams_id: Optional[int] = Field(None, ge=0, le=3, description="AMS unit 0-3 (kind 'ams')")
    tray_id: Optional[int] = Field(None, ge=0, le=3, description="Tray 0-3 (kind 'ams')")


class FilamentSlot(BaseModel):
    """One filament of the plate and the slot it is drawn from."""

    filament_id: int = Field(..., ge=1, description="Filament number in the sliced file")
    slot: SlotChoice


def _mapping_json(mapping: list[FilamentSlot]) -> str:
    entries = []
    for entry in mapping:
        slot = {"kind": entry.slot.kind}
        if entry.slot.kind == "ams":
            slot.update(ams_id=entry.slot.ams_id, tray_id=entry.slot.tray_id)
        entries.append({"filament_id": entry.filament_id, "slot": slot})
    return json.dumps(entries)


def build_tools(client: BatchivoClient) -> list[ToolSpec]:
    """The print send tool group."""

    async def prepare_print(
        printer_id: str,
        plate: int,
        ams_mapping: list[FilamentSlot],
        model_file_id: Optional[str] = None,
        file_path: Optional[str] = None,
        attach_to_model_id: Optional[str] = None,
    ) -> Any:
        if (model_file_id is None) == (file_path is None):
            raise ToolError("Give exactly one of model_file_id or file_path")
        form = {
            "plate": plate,
            "ams_mapping": _mapping_json(ams_mapping),
            "model_file_id": model_file_id,
            "attach_to_model_id": attach_to_model_id,
        }
        path = f"/printers/{printer_id}/prints/prepare"
        if file_path is not None:
            return await call_api(client.upload(path, "file", file_path, data=form))
        return await call_api(client.post_form(path, form))

    async def confirm_print(
        printer_id: str, confirmation_token: str, acknowledge_warnings: bool = False
    ) -> Any:
        body = {
            "confirmation_token": confirmation_token,
            "acknowledge_warnings": acknowledge_warnings,
        }
        return await call_api(client.post(f"/printers/{printer_id}/prints/confirm", json=body))

    async def list_print_sends(printer_id: str, limit: int = 20) -> Any:
        return await call_api(client.get(f"/printers/{printer_id}/prints", params={"limit": limit}))

    async def get_print_send(printer_id: str, send_id: str) -> Any:
        return await call_api(client.get(f"/printers/{printer_id}/prints/{send_id}"))

    return [
        write_tool(
            "prepare_print",
            "Prepare a print on a Bambu printer from a sliced .gcode.3mf (a model file id, or a "
            "local file path) for one plate and an AMS slot per filament. Sends nothing to the "
            "printer. Returns the summary (time, weight, each slot's expected and loaded "
            "filament), warnings and a confirmation token valid 5 minutes. Show the summary and "
            "every warning to the operator before calling confirm_print.",
            prepare_print,
            scope="print",
        ),
        write_tool(
            "confirm_print",
            "START the prepared print on the printer. Only after the operator has seen the "
            "summary. acknowledge_warnings must be true only when the operator explicitly "
            "accepted the listed spool warnings; it is false by default and the print is then "
            "refused when warnings exist.",
            confirm_print,
            scope="print",
            destructive=True,
        ),
        read_tool(
            "list_print_sends", "List the prints sent to a printer, newest first.", list_print_sends
        ),
        read_tool("get_print_send", "Get one print send and its outcome.", get_print_send),
    ]
