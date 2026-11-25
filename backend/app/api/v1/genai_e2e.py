"""A local imitation of the Replicate API for e2e runs (spec 008, research R14).

Mounted always but inert: every route answers 404 unless E2E test hooks are on
and the instance is not production, exactly like the other e2e hooks. A backend
started with ``GENAI_PROVIDER_BASE_URL=<this router>`` then runs generation jobs
end to end with no real token, no network call to Replicate and no cost.

A prediction succeeds on its second read. Images are small PNGs; image-to-3D
returns ``{"model_file": <tiny GLB>}`` like the default model.
"""

import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from PIL import Image

from app.config import Settings, get_settings
from app.services.genai.glb import build_glb

# Hidden from the published API on every route, not only where main.py mounts it.
router = APIRouter(include_in_schema=False)

FAKE_SECRET = "whsec_" + "ZTJlLWZha2Utd2ViaG9vay1zZWNyZXQtMDAwMDAwMDA="
_predictions: dict[str, dict[str, Any]] = {}


def _enabled(settings: Settings = Depends(get_settings)) -> None:
    if settings.is_production or not settings.e2e_test_hooks_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


def _png(color: tuple[int, int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _base(request: Request) -> str:
    return str(request.url).split("/genai/e2e-fake")[0] + "/genai/e2e-fake"


@router.get("/status", dependencies=[Depends(_enabled)])
async def status(settings: Settings = Depends(get_settings)) -> dict:
    """Whether this backend's jobs go to this fake: e2e runs skip unless they do."""
    return {"provider_is_fake": settings.genai_provider_url.endswith("/genai/e2e-fake")}


@router.get("/account", dependencies=[Depends(_enabled)])
async def account() -> dict:
    return {"type": "user", "username": "e2e-fake", "name": "E2E fake provider"}


@router.get("/webhooks/default/secret", dependencies=[Depends(_enabled)])
async def secret() -> dict:
    return {"key": FAKE_SECRET}


@router.post("/files", dependencies=[Depends(_enabled)])
async def upload_file(request: Request) -> dict:
    file_id = uuid.uuid4().hex
    return {"id": file_id, "urls": {"get": f"{_base(request)}/files/{file_id}"}}


@router.post("/predictions", status_code=201, dependencies=[Depends(_enabled)])
async def create_prediction(request: Request) -> dict:
    body = await request.json()
    version = str(body.get("version", ""))
    payload = body.get("input") or {}
    prediction_id = uuid.uuid4().hex
    base = _base(request)
    if "trellis" in version or "3d" in version.lower():
        output: Any = {"model_file": f"{base}/outputs/{prediction_id}-0.glb"}
    else:
        count = int(payload.get("num_outputs") or 1)
        output = [f"{base}/outputs/{prediction_id}-{i}.png" for i in range(max(count, 1))]
    _predictions[prediction_id] = {"reads": 0, "output": output, "status": "starting"}
    return {
        "id": prediction_id,
        "status": "starting",
        "version": version.split(":", 1)[1] if ":" in version else "e2e0fficial",
        "output": None,
    }


@router.get("/predictions/{prediction_id}", dependencies=[Depends(_enabled)])
async def get_prediction(prediction_id: str) -> dict:
    item = _predictions.get(prediction_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Not found")
    item["reads"] += 1
    if item["status"] == "starting" and item["reads"] >= 2:
        item["status"] = "succeeded"
    done = item["status"] == "succeeded"
    return {
        "id": prediction_id,
        "status": item["status"],
        "output": item["output"] if done else None,
        "metrics": {"predict_time": 1.5} if done else {},
    }


@router.post("/predictions/{prediction_id}/cancel", dependencies=[Depends(_enabled)])
async def cancel_prediction(prediction_id: str) -> dict:
    item = _predictions.setdefault(prediction_id, {"reads": 0, "output": None})
    item["status"] = "canceled"
    return {"id": prediction_id, "status": "canceled"}


@router.get("/outputs/{name}", dependencies=[Depends(_enabled)])
async def output_file(name: str) -> Response:
    if name.endswith(".glb"):
        mesh = build_glb(
            [(0, 0, 0), (40, 0, 0), (0, 30, 0), (0, 0, 20)], [0, 1, 2, 0, 1, 3, 0, 2, 3]
        )
        return Response(content=mesh, media_type="model/gltf-binary")
    index = sum(ord(c) for c in name) % 200
    return Response(content=_png((40 + index, 120, 200 - index // 2)), media_type="image/png")


__all__ = ["FAKE_SECRET", "router"]
