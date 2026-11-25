"""Idea tools: list, read, create, update, timeline, images, import, convert (007 API)."""

from typing import Any, Literal, Optional

from app.mcp_server.client import BatchivoClient
from app.mcp_server.tools.base import ToolSpec, call_api, read_tool, with_extra, write_tool

IdeaStatus = Literal["inbox", "exploring", "validating", "ready", "converted", "parked", "dropped"]
WritableStatus = Literal["inbox", "exploring", "validating", "ready", "parked", "dropped"]
IdeaSource = Literal["manual", "pain_point_report", "customer", "other"]
TextEntryKind = Literal["note", "link", "measurement", "decision"]


def build_tools(client: BatchivoClient) -> list[ToolSpec]:
    """The idea tool group."""

    async def list_ideas(
        status: Optional[list[IdeaStatus]] = None,
        tag: Optional[list[str]] = None,
        source: Optional[IdeaSource] = None,
        search: Optional[str] = None,
        archived: Literal["false", "true", "all"] = "false",
        sort: Literal["updated", "score", "created"] = "updated",
        skip: int = 0,
        limit: int = 20,
    ) -> Any:
        params = {
            "status": status,
            "tag": tag,
            "source": source,
            "search": search,
            "archived": archived,
            "sort": sort,
            "skip": skip,
            "limit": limit,
        }
        return await call_api(client.get("/ideas", params=params))

    async def list_idea_tags() -> Any:
        return await call_api(client.get("/ideas/tags"))

    async def get_idea(idea_id: str) -> Any:
        return await call_api(client.get(f"/ideas/{idea_id}"))

    async def list_idea_entries(idea_id: str, archived: bool = False) -> Any:
        return await call_api(
            client.get(f"/ideas/{idea_id}/entries", params={"archived": str(archived).lower()})
        )

    async def get_idea_entry_image(idea_id: str, entry_id: str) -> Any:
        return await call_api(client.get_bytes(f"/ideas/{idea_id}/entries/{entry_id}/image"))

    async def create_idea(
        title: str,
        summary: Optional[str] = None,
        status: WritableStatus = "inbox",
        source: IdeaSource = "manual",
        source_url: Optional[str] = None,
        tags: Optional[list[str]] = None,
        scores: Optional[dict[str, int]] = None,
        report_score: Optional[int] = None,
    ) -> Any:
        body = with_extra(
            {
                "title": title,
                "summary": summary,
                "status": status,
                "source": source,
                "source_url": source_url,
                "tags": tags,
                "scores": scores,
                "report_score": report_score,
            },
            None,
        )
        return await call_api(client.post("/ideas", json=body))

    async def update_idea(
        idea_id: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        status: Optional[WritableStatus] = None,
        source: Optional[IdeaSource] = None,
        source_url: Optional[str] = None,
        tags: Optional[list[str]] = None,
        scores: Optional[dict[str, int]] = None,
        archived: Optional[bool] = None,
        cover_entry_id: Optional[str] = None,
    ) -> Any:
        body = with_extra(
            {
                "title": title,
                "summary": summary,
                "status": status,
                "source": source,
                "source_url": source_url,
                "tags": tags,
                "scores": scores,
                "archived": archived,
                "cover_entry_id": cover_entry_id,
            },
            None,
        )
        return await call_api(client.patch(f"/ideas/{idea_id}", json=body))

    async def add_idea_entry(
        idea_id: str,
        kind: TextEntryKind,
        body: Optional[str] = None,
        link_url: Optional[str] = None,
    ) -> Any:
        payload = with_extra({"kind": kind, "body": body, "link_url": link_url}, None)
        return await call_api(client.post(f"/ideas/{idea_id}/entries", json=payload))

    async def upload_idea_image(
        idea_id: str, file_path: str, kind: Literal["image", "sketch"] = "image"
    ) -> Any:
        return await call_api(
            client.upload(
                f"/ideas/{idea_id}/entries/images", "files", file_path, data={"kind": kind}
            )
        )

    async def update_idea_entry(
        idea_id: str,
        entry_id: str,
        body: Optional[str] = None,
        link_url: Optional[str] = None,
        pinned: Optional[bool] = None,
        archived: Optional[bool] = None,
    ) -> Any:
        payload = with_extra(
            {"body": body, "link_url": link_url, "pinned": pinned, "archived": archived}, None
        )
        return await call_api(client.patch(f"/ideas/{idea_id}/entries/{entry_id}", json=payload))

    async def add_idea_iteration(idea_id: str, note: Optional[str] = None) -> Any:
        return await call_api(
            client.post(f"/ideas/{idea_id}/iterations", json=with_extra({"note": note}, None))
        )

    async def import_ideas(items: list[dict[str, Any]], dry_run: bool = False) -> Any:
        return await call_api(
            client.post("/ideas/import", json={"items": items, "dry_run": dry_run})
        )

    async def parse_idea_report(text: str) -> Any:
        return await call_api(client.post("/ideas/import/parse-report", json={"text": text}))

    async def convert_idea(
        idea_id: str,
        target: Literal["model", "product"],
        name: Optional[str] = None,
        model_sku: Optional[str] = None,
        product_sku: Optional[str] = None,
        include_images: bool = True,
    ) -> Any:
        body = with_extra(
            {
                "target": target,
                "name": name,
                "model_sku": model_sku,
                "product_sku": product_sku,
                "include_images": include_images,
            },
            None,
        )
        return await call_api(client.post(f"/ideas/{idea_id}/convert", json=body))

    return [
        read_tool(
            "list_ideas",
            "List the shop's product ideas, filtered by status, tags (all must match), source "
            "or a search on title and summary; paginate with skip and limit (max 100).",
            list_ideas,
        ),
        read_tool("list_idea_tags", "List every tag used on ideas.", list_idea_tags),
        read_tool("get_idea", "Get one idea with its scores and status.", get_idea),
        read_tool(
            "list_idea_entries",
            "List an idea's timeline entries (notes, links, images, decisions).",
            list_idea_entries,
        ),
        read_tool(
            "get_idea_entry_image",
            "Fetch the image of an idea timeline entry.",
            get_idea_entry_image,
        ),
        write_tool("create_idea", "Create a product idea.", create_idea),
        write_tool(
            "update_idea",
            "Change an idea's title, summary, status, tags, scores, cover or archive flag.",
            update_idea,
        ),
        write_tool(
            "add_idea_entry",
            "Add a note, link, measurement or decision to an idea's timeline.",
            add_idea_entry,
        ),
        write_tool(
            "upload_idea_image",
            "Upload a local image file (JPEG, PNG or WebP, up to 10 MB) to an idea's timeline.",
            upload_idea_image,
        ),
        write_tool(
            "update_idea_entry",
            "Edit, pin or archive an idea timeline entry.",
            update_idea_entry,
        ),
        write_tool(
            "add_idea_iteration",
            "Start a new design iteration on an idea, with an optional note.",
            add_idea_iteration,
        ),
        write_tool(
            "import_ideas",
            "Import ideas from structured items (title, summary, scores, report_score, tags, "
            "source_url); dry_run previews without writing.",
            import_ideas,
        ),
        write_tool(
            "parse_idea_report",
            "Parse a raw pain-point report into importable idea items (writes nothing).",
            parse_idea_report,
        ),
        write_tool(
            "convert_idea",
            "Convert an idea into a model (or a model and a product).",
            convert_idea,
        ),
    ]
