"""Generative AI tools against a mocked Batchivo API (spec 008 over 010).

The tools only forward: no test here reaches Replicate, or even the Batchivo
backend. Starting, cancelling, uploading and adopting need the `genai` scope.
"""

import json

import httpx

import pytest

from tests.mcp_server.conftest import result_error, result_json

pytestmark = pytest.mark.asyncio

JOB = "44444444-4444-4444-8444-444444444444"
ASSET = "55555555-5555-4555-8555-555555555555"
IDEA = "66666666-6666-4666-8666-666666666666"
PRODUCT = "88888888-8888-4888-8888-888888888888"
PNG = b"\x89PNG\r\n\x1a\nfake"


async def _tool_names(mcp_client, scopes):
    async with mcp_client(scopes) as client:
        return {tool.name for tool in (await client.list_tools()).tools}


async def test_writes_need_the_genai_scope(mcp_client):
    read_only = await _tool_names(mcp_client, ["read"])
    assert {"list_generation_capabilities", "get_generation_job"} <= read_only
    assert not {"start_generation", "adopt_generation_output", "cancel_generation"} & read_only
    with_genai = await _tool_names(mcp_client, ["read", "genai"])
    assert {
        "start_generation",
        "cancel_generation",
        "upload_generation_input",
        "adopt_generation_output",
    } <= with_genai


async def test_list_capabilities(mock_api, mcp_client):
    mock_api.get("/genai/capabilities").respond(
        200, json={"connected": True, "capabilities": [{"capability": "concept_image"}]}
    )
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("list_generation_capabilities", {})
    assert result_json(result)["connected"] is True


async def test_estimate_sends_the_job_body(mock_api, mcp_client):
    route = mock_api.post("/genai/estimate").respond(
        200, json={"estimated_cost": "0.0030", "would_exceed_budget": False}
    )
    async with mcp_client(["read"]) as client:
        result = await client.call_tool(
            "estimate_generation",
            {"capability": "concept_image", "inputs": {"prompt": "a clip"}},
        )
    assert result_json(result)["estimated_cost"] == "0.0030"  # money stays a string
    assert json.loads(route.calls.last.request.content) == {
        "capability": "concept_image",
        "inputs": {"prompt": "a clip"},
        "target": {"type": "none"},
    }


async def test_start_generation_on_an_idea(mock_api, mcp_client):
    route = mock_api.post("/genai/jobs").respond(201, json={"id": JOB, "status": "queued"})
    async with mcp_client(["genai"]) as client:
        result = await client.call_tool(
            "start_generation",
            {
                "capability": "concept_image",
                "inputs": {"prompt": "a visor clip", "count": 2},
                "target_type": "idea",
                "target_id": IDEA,
            },
        )
    assert result_json(result)["id"] == JOB
    sent = json.loads(route.calls.last.request.content)
    assert sent["target"] == {"type": "idea", "id": IDEA}
    assert sent["inputs"]["count"] == 2


async def test_budget_refusal_reaches_the_agent(mock_api, mcp_client):
    mock_api.post("/genai/jobs").respond(
        409,
        json={
            "detail": {
                "code": "budget_exceeded",
                "message": "This generation would go over the monthly budget",
            }
        },
    )
    async with mcp_client(["genai"]) as client:
        result = await client.call_tool(
            "start_generation", {"capability": "concept_image", "inputs": {"prompt": "x"}}
        )
    error = result_error(result)
    assert "over the monthly budget" in error
    assert "budget_exceeded" in error


async def test_list_and_get_jobs(mock_api, mcp_client):
    listed = mock_api.get("/genai/jobs").respond(200, json={"items": [], "total": 0})
    mock_api.get(f"/genai/jobs/{JOB}").respond(200, json={"id": JOB, "status": "succeeded"})
    async with mcp_client(["read"]) as client:
        await client.call_tool(
            "list_generation_jobs", {"target_type": "idea", "target_id": IDEA, "status": "failed"}
        )
        job = await client.call_tool("get_generation_job", {"job_id": JOB})
    params = listed.calls.last.request.url.params
    assert (params["target_type"], params["target_id"], params["status"]) == (
        "idea",
        IDEA,
        "failed",
    )
    assert result_json(job)["status"] == "succeeded"


async def test_cancel_generation(mock_api, mcp_client):
    route = mock_api.post(f"/genai/jobs/{JOB}/cancel").respond(
        200, json={"id": JOB, "status": "canceled"}
    )
    async with mcp_client(["genai"]) as client:
        result = await client.call_tool("cancel_generation", {"job_id": JOB})
    assert route.called
    assert result_json(result)["status"] == "canceled"


def _job_with(kind: str) -> dict:
    return {"id": JOB, "status": "succeeded", "outputs": [{"id": ASSET, "kind": kind}]}


async def test_get_generation_output_returns_the_image(mock_api, mcp_client):
    mock_api.get(f"/genai/jobs/{JOB}").respond(200, json=_job_with("image"))
    route = mock_api.get(f"/genai/assets/{ASSET}/file").respond(
        200, content=PNG, headers={"content-type": "image/png"}
    )
    async with mcp_client(["read"]) as client:
        result = await client.call_tool(
            "get_generation_output", {"job_id": JOB, "asset_id": ASSET, "thumbnail": True}
        )
    assert route.calls.last.request.url.params["variant"] == "thumb"
    assert result.content[0].type == "image"


async def test_upload_generation_input(mock_api, mcp_client, tmp_path):
    photo = tmp_path / "front.png"
    photo.write_bytes(PNG)
    route = mock_api.post("/genai/uploads").respond(201, json={"id": ASSET, "kind": "image"})
    async with mcp_client(["genai"]) as client:
        result = await client.call_tool("upload_generation_input", {"file_path": str(photo)})
    assert result_json(result)["id"] == ASSET
    assert b'name="file"; filename="front.png"' in route.calls.last.request.content


async def test_adopt_into_a_product_needs_confirmation(mock_api, mcp_client):
    route = mock_api.post(f"/genai/assets/{ASSET}/adopt")
    route.side_effect = [
        httpx.Response(
            409,
            json={
                "detail": {
                    "code": "needs_confirmation",
                    "message": "This picture does not show the real item; confirm to add it",
                }
            },
        ),
        httpx.Response(201, json={"product_image_id": PRODUCT}),
    ]
    args = {"asset_id": ASSET, "target_type": "product", "target_id": PRODUCT}
    async with mcp_client(["genai"]) as client:
        refused = await client.call_tool("adopt_generation_output", args)
        adopted = await client.call_tool(
            "adopt_generation_output", {**args, "confirm_not_real_item": True}
        )
    assert "does not show the real item" in result_error(refused)
    assert "needs_confirmation" in result_error(refused)
    assert result_json(adopted)["product_image_id"] == PRODUCT
    first, second = (json.loads(c.request.content) for c in route.calls)
    assert first == {
        "target": {"type": "product", "id": PRODUCT},
        "confirm_not_real_item": False,
    }
    assert second["confirm_not_real_item"] is True


async def test_a_3d_draft_is_not_returned_as_an_image(mock_api, mcp_client):
    """T082: a GLB output is refused from the job, before any download."""
    mock_api.get(f"/genai/jobs/{JOB}").respond(200, json=_job_with("mesh"))
    file_route = mock_api.get(f"/genai/assets/{ASSET}/file").respond(200, content=b"glTF")
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("get_generation_output", {"job_id": JOB, "asset_id": ASSET})
    assert "3D draft (GLB), not an image" in result_error(result)
    assert not file_route.called


async def test_an_output_of_another_job_is_refused(mock_api, mcp_client):
    mock_api.get(f"/genai/jobs/{JOB}").respond(200, json={"id": JOB, "outputs": []})
    async with mcp_client(["read"]) as client:
        result = await client.call_tool("get_generation_output", {"job_id": JOB, "asset_id": ASSET})
    assert "has no output" in result_error(result)


async def test_the_confirmation_is_described_by_the_job_flag(mcp_client):
    """T103: agents are told to read the job's shows_real_item, not the capability."""
    async with mcp_client(["read", "genai"]) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    adopt = tools["adopt_generation_output"].description
    assert "shows_real_item=false" in adopt
    assert "from a sketch" in adopt
    assert "shows_real_item" in tools["get_generation_job"].description
