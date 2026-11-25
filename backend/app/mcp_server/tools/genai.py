"""Generative AI tools: capabilities, estimate, jobs, outputs and adoption (spec 008 over 010).

Every tool forwards to the 008 API, which does the work and the checks: the
budget and concurrency limits, the tenant's own Replicate token, the role, and
the confirmation before a picture that does not show the real item goes on a
product. Starting, cancelling or adopting a generation needs the `genai` scope
(it can spend the shop's money); reading needs `read`.
"""

from typing import Any, Literal, Optional

from mcp.server.mcpserver.exceptions import ToolError

from app.mcp_server.client import BatchivoApiError, BatchivoClient, BatchivoUnreachable
from app.mcp_server.tools.base import ToolSpec, call_api, read_tool, with_extra, write_tool

Capability = Literal[
    "concept_image",
    "image_edit",
    "product_photo_enhance",
    "background_remove",
    "upscale",
    "lifestyle_scene",
    "image_to_3d",
]
TargetType = Literal["idea", "product", "model", "none"]
AdoptTargetType = Literal["idea", "product", "model"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]


def _target(target_type: str, target_id: Optional[str]) -> dict[str, Any]:
    return with_extra({"type": target_type, "id": target_id}, None)


async def call_api_json(operation: Any) -> dict[str, Any]:
    """An API call whose JSON the tool reads itself; a failure becomes a tool error."""
    try:
        return await operation
    except (BatchivoApiError, BatchivoUnreachable) as exc:
        raise ToolError(str(exc)) from None


def build_tools(client: BatchivoClient) -> list[ToolSpec]:
    """The generative AI tool group."""

    async def list_generation_capabilities() -> Any:
        return await call_api(client.get("/genai/capabilities"))

    async def estimate_generation(
        capability: Capability,
        inputs: dict[str, Any],
        target_type: TargetType = "none",
        target_id: Optional[str] = None,
    ) -> Any:
        body = {
            "capability": capability,
            "inputs": inputs,
            "target": _target(target_type, target_id),
        }
        return await call_api(client.post("/genai/estimate", json=body))

    async def start_generation(
        capability: Capability,
        inputs: dict[str, Any],
        target_type: TargetType = "none",
        target_id: Optional[str] = None,
    ) -> Any:
        body = {
            "capability": capability,
            "inputs": inputs,
            "target": _target(target_type, target_id),
        }
        return await call_api(client.post("/genai/jobs", json=body))

    async def list_generation_jobs(
        target_type: Optional[TargetType] = None,
        target_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
        capability: Optional[Capability] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> Any:
        params = {
            "target_type": target_type,
            "target_id": target_id,
            "status": status,
            "capability": capability,
            "skip": skip,
            "limit": limit,
        }
        return await call_api(client.get("/genai/jobs", params=params))

    async def get_generation_job(job_id: str) -> Any:
        return await call_api(client.get(f"/genai/jobs/{job_id}"))

    async def cancel_generation(job_id: str) -> Any:
        return await call_api(client.post(f"/genai/jobs/{job_id}/cancel", json={}))

    async def get_generation_output(job_id: str, asset_id: str, thumbnail: bool = False) -> Any:
        job = await call_api_json(client.get(f"/genai/jobs/{job_id}"))
        output = next((o for o in job.get("outputs", []) if o.get("id") == asset_id), None)
        if output is None:
            raise ToolError(f"Job {job_id} has no output {asset_id}.")
        if output.get("kind") != "image":
            # Decided from the job, before any download: a GLB can be 200 MB (T082).
            raise ToolError(
                "This output is a 3D draft (GLB), not an image. Adopt it into a model with "
                "adopt_generation_output, or open it in Batchivo to view or download it."
            )
        variant = "thumb" if thumbnail else "full"
        return await call_api(client.get_bytes(f"/genai/assets/{asset_id}/file?variant={variant}"))

    async def upload_generation_input(file_path: str) -> Any:
        return await call_api(client.upload("/genai/uploads", "file", file_path))

    async def adopt_generation_output(
        asset_id: str,
        target_type: AdoptTargetType,
        target_id: str,
        confirm_not_real_item: bool = False,
        alt_text: Optional[str] = None,
        version_note: Optional[str] = None,
    ) -> Any:
        body = with_extra(
            {
                "target": {"type": target_type, "id": target_id},
                "confirm_not_real_item": confirm_not_real_item,
                "alt_text": alt_text,
                "version_note": version_note,
            },
            None,
        )
        return await call_api(client.post(f"/genai/assets/{asset_id}/adopt", json=body))

    return [
        read_tool(
            "list_generation_capabilities",
            "List what the shop's AI can make (concept images, photo edits, background removal, "
            "upscale, lifestyle scenes, 3D drafts), with each model, price in USD, input rules "
            "and whether Replicate is connected.",
            list_generation_capabilities,
        ),
        read_tool(
            "estimate_generation",
            "Estimate a generation's cost in USD against this month's spend and budget, "
            "without starting it.",
            estimate_generation,
        ),
        write_tool(
            "start_generation",
            "Start an AI generation (it costs money on the shop's Replicate account). Inputs "
            "follow list_generation_capabilities; input_assets name images as "
            "{'type': 'asset'|'idea_entry'|'product_image'|'model_image', 'id': ...} (an "
            "uploaded input is an 'asset'). "
            "Refused over the monthly budget or the concurrency limit.",
            start_generation,
            scope="genai",
        ),
        read_tool(
            "list_generation_jobs",
            "List AI generation jobs, newest first, by target, status or capability.",
            list_generation_jobs,
        ),
        read_tool(
            "get_generation_job",
            "Get one AI generation job: status, cost, model, version that ran, outputs, "
            "where each output was adopted, and shows_real_item (false when its results do "
            "not show the real item, so a product needs a confirmation).",
            get_generation_job,
        ),
        write_tool(
            "cancel_generation",
            "Cancel a queued or running AI generation.",
            cancel_generation,
            scope="genai",
        ),
        read_tool(
            "get_generation_output",
            "Fetch an AI output image (or its thumbnail) by its job and output ids. A 3D "
            "draft (GLB) is not returned: adopt it into a model instead.",
            get_generation_output,
        ),
        write_tool(
            "upload_generation_input",
            "Upload a local image (JPEG, PNG or WebP) to use as a generation input.",
            upload_generation_input,
            scope="genai",
        ),
        write_tool(
            "adopt_generation_output",
            "Add an AI output to an idea's timeline, a product's images (labelled AI) or a "
            "model's files (a 3D draft becomes an inactive 'AI draft' version). On a product, "
            "an output whose job has shows_real_item=false (a concept image, a 3D draft, or "
            "a result made from one or from a sketch) needs confirm_not_real_item=true, after "
            "telling the operator it does not show the real item.",
            adopt_generation_output,
            scope="genai",
        ),
    ]
