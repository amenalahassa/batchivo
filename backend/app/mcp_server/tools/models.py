"""Model tools: models, their files and versions, and the notes pinned on them (004 API)."""

from typing import Any, Literal, Optional

from app.mcp_server.client import BatchivoClient
from app.mcp_server.tools.base import ToolSpec, call_api, read_tool, with_extra, write_tool

Vector = list[float]


def build_tools(client: BatchivoClient) -> list[ToolSpec]:
    """The model, file version and pinned note tool group."""

    async def list_models(
        search: Optional[str] = None,
        category: Optional[str] = None,
        is_active: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> Any:
        params = {
            "search": search,
            "category": category,
            "is_active": is_active,
            "skip": skip,
            "limit": limit,
        }
        return await call_api(client.get("/models", params=params))

    async def get_model(model_id: str) -> Any:
        return await call_api(client.get(f"/models/{model_id}"))

    async def list_model_files(model_id: str, file_type: Optional[str] = None) -> Any:
        return await call_api(
            client.get(f"/models/{model_id}/files", params={"file_type": file_type})
        )

    async def list_file_versions(model_id: str) -> Any:
        return await call_api(client.get(f"/models/{model_id}/file-versions"))

    async def list_file_notes(
        model_id: str,
        file_id: Optional[str] = None,
        version_id: Optional[str] = None,
        status: Optional[Literal["open", "resolved", "carried_forward"]] = None,
        include_archived: bool = False,
        extra_filters: Optional[dict[str, Any]] = None,
    ) -> Any:
        params = {
            "file_id": file_id,
            "version_id": version_id,
            "status": status,
            "include_archived": str(include_archived).lower(),
            **(extra_filters or {}),
        }
        return await call_api(client.get(f"/models/{model_id}/file-notes", params=params))

    async def add_file_note(
        model_id: str,
        file_id: str,
        text: str,
        position: Vector,
        normal: Vector,
        layer: Optional[int] = None,
        extra_fields: Optional[dict[str, Any]] = None,
    ) -> Any:
        body = with_extra(
            {"text": text, "position": position, "normal": normal, "layer": layer}, extra_fields
        )
        return await call_api(client.post(f"/models/{model_id}/files/{file_id}/notes", json=body))

    async def update_file_note(
        model_id: str,
        note_id: str,
        text: Optional[str] = None,
        status: Optional[Literal["open", "resolved"]] = None,
        resolved_in_version_id: Optional[str] = None,
        position: Optional[Vector] = None,
        normal: Optional[Vector] = None,
        extra_fields: Optional[dict[str, Any]] = None,
    ) -> Any:
        body = with_extra(
            {
                "text": text,
                "status": status,
                "resolved_in_version_id": resolved_in_version_id,
                "position": position,
                "normal": normal,
            },
            extra_fields,
        )
        return await call_api(client.patch(f"/models/{model_id}/file-notes/{note_id}", json=body))

    async def carry_forward_note(model_id: str, note_id: str, target_file_id: str) -> Any:
        return await call_api(
            client.post(
                f"/models/{model_id}/file-notes/{note_id}/carry-forward",
                json={"target_file_id": target_file_id},
            )
        )

    return [
        read_tool(
            "list_models",
            "List the shop's models (printable designs); search by SKU or name.",
            list_models,
        ),
        read_tool("get_model", "Get one model with its details.", get_model),
        read_tool("list_model_files", "List a model's files (STL, 3MF, sliced).", list_model_files),
        read_tool(
            "list_file_versions",
            "List a model's file versions, newest first, with their open note counts.",
            list_file_versions,
        ),
        read_tool(
            "list_file_notes",
            "List the notes pinned on a model's files, filtered by file, version or status. "
            "`extra_filters` passes further query filters through unchanged.",
            list_file_notes,
        ),
        write_tool(
            "add_file_note",
            "Pin a note on a model file at a point (position and surface normal, in mm). "
            "`extra_fields` passes further note fields through unchanged.",
            add_file_note,
        ),
        write_tool(
            "update_file_note",
            "Edit a pinned note, or resolve it (status 'resolved', optionally naming the version "
            "that resolved it).",
            update_file_note,
        ),
        write_tool(
            "carry_forward_note",
            "Carry an open note forward to a file of a newer version.",
            carry_forward_note,
        ),
    ]
