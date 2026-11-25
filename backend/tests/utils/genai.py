"""Shared fixtures and builders for the generative AI tests (spec 008).

The Replicate HTTP API is always mocked with respx: ``replicate_mock`` installs
routes on the provider base URL with ``assert_all_mocked=True``, so a request to
any route not mocked fails the test instead of reaching the network. A test
that does not ask for ``replicate_mock`` runs under ``no_real_replicate``
(autouse): the provider base URL points at an unroutable fake host and every
outgoing HTTP request fails the test. No real token is ever used (the test
token below is a fixed fake).

Import the fixtures into a test module or conftest with
``from tests.utils.genai import *  # noqa: F401,F403``.
"""

import base64
import json
import time
import uuid
from io import BytesIO
from typing import Optional

import httpx
import pytest
import pytest_asyncio
import respx
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.encryption import encrypt_value
from app.models.generation_job import GenAIAsset, GenerationJob
from app.models.tenant import Tenant
from app.services.genai import credentials
from app.services.genai.glb import build_glb
from app.services.genai.webhooks import sign

FAKE_TOKEN = "r8_FakeTestToken0000000000000000000000"
FAKE_SECRET = "whsec_" + base64.b64encode(b"batchivo-genai-test-webhook-secret").decode()
GENAI = "/api/v1/genai"
DELIVERY = "https://replicate.delivery/xezq/out"
#: RFC 2606: ``.invalid`` never resolves, so nothing sent there leaves the machine
UNROUTABLE_PROVIDER = "https://replicate.invalid/v1"


def png_bytes(width: int = 64, height: int = 48, color: str = "orange") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def glb_bytes() -> bytes:
    return build_glb([(0, 0, 0), (40, 0, 0), (0, 30, 0), (0, 0, 20)], [0, 1, 2, 0, 1, 3])


def provider_url() -> str:
    return get_settings().genai_provider_url


def prediction(
    pid: str = "pred-1",
    status: str = "processing",
    output=None,
    predict_time: Optional[float] = None,
    version: str = "v" * 64,
    error: Optional[str] = None,
) -> dict:
    body = {"id": pid, "status": status, "output": output, "version": version, "error": error}
    if predict_time is not None:
        body["metrics"] = {"predict_time": predict_time}
    return body


def signed_headers(body: bytes, secret: str = FAKE_SECRET, ts: Optional[int] = None) -> dict:
    ts = int(time.time()) if ts is None else ts
    wid = f"msg_{uuid.uuid4().hex}"
    return {
        "webhook-id": wid,
        "webhook-timestamp": str(ts),
        "webhook-signature": sign(secret, wid, str(ts), body),
        "content-type": "application/json",
    }


async def connect(db: AsyncSession, tenant: Tenant, token: str = FAKE_TOKEN, **extra) -> Tenant:
    """Give the tenant its own (fake) Replicate token and optional settings."""
    settings = dict(tenant.settings or {})
    config = dict(settings.get("replicate") or {})
    config["api_token_encrypted"] = encrypt_value(token)
    config.update(extra)
    settings["replicate"] = config
    tenant.settings = settings
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def make_output_job(
    db: AsyncSession,
    tenant: Tenant,
    *,
    capability: str = "concept_image",
    kind: str = "image",
    status: str = "succeeded",
    target_type: str = "none",
    target_id: Optional[uuid.UUID] = None,
    content: Optional[bytes] = None,
    shows_real_item: Optional[bool] = None,
) -> tuple[GenerationJob, GenAIAsset]:
    """A finished job with one stored output, as the runner leaves it.

    ``shows_real_item`` defaults to what the capability alone says, as the service
    decides for a job whose inputs are all real.
    """
    from app.services.genai.capabilities import NOT_REAL_ITEM, Capability
    from app.services.genai.storage import GenAIFileStore

    if shows_real_item is None:
        shows_real_item = Capability(capability) not in NOT_REAL_ITEM

    job = GenerationJob(
        tenant_id=tenant.id,
        capability=capability,
        provider="replicate",
        model_ref="owner/model",
        model_version="official",
        model_version_ran="ab" * 32,
        inputs={"prompt": "a clip", "input_assets": []},
        seed=7,
        target_type=target_type,
        target_id=target_id,
        status=status,
        external_id=f"pred-{uuid.uuid4().hex[:8]}",
        estimated_cost=0,
        cost=0,
        cost_provenance="computed",
        price_snapshot={"unit": "per_output", "amount_usd": "0.003"},
        shows_real_item=shows_real_item,
    )
    db.add(job)
    await db.flush()
    store = GenAIFileStore()
    if kind == "mesh":
        saved = await store.save_mesh(content or glb_bytes(), str(job.id))
    else:
        saved = await store.save_image(content or png_bytes(), "image/png", str(job.id))
    asset = GenAIAsset(
        tenant_id=tenant.id,
        job_id=job.id,
        source="output",
        kind=kind,
        storage_url=saved["url"],
        thumbnail_url=saved["thumbnail_url"],
        content_type=saved["content_type"],
        file_size=saved["file_size"],
        width=saved["width"],
        height=saved["height"],
        ai_generated=True,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(job)
    await db.refresh(asset)
    return job, asset


@pytest.fixture(autouse=True)
def genai_storage(tmp_path):
    """Keep every file this suite writes in a temporary directory."""
    from app.services.image_storage import get_image_storage

    storage = get_image_storage()
    saved = (storage.storage_type, storage.base_path)
    storage.storage_type = "local"
    storage.base_path = tmp_path
    (tmp_path / "products").mkdir(exist_ok=True)
    yield storage
    storage.storage_type, storage.base_path = saved


@pytest.fixture(autouse=True)
def dispatched(monkeypatch):
    """Record dispatch calls instead of reaching a broker."""
    calls: dict[str, list] = {"submit": [], "poll": []}
    import app.tasks.genai as tasks

    monkeypatch.setattr(
        tasks, "dispatch_submit", lambda job_id, tenant_id, **kw: calls["submit"].append(job_id)
    )
    monkeypatch.setattr(
        tasks,
        "dispatch_poll",
        lambda job_id, tenant_id, delay: calls["poll"].append((job_id, delay)),
    )
    credentials.clear_platform_cache()
    return calls


@pytest.fixture(autouse=True)
def no_real_replicate(request, monkeypatch):
    """Guarantee that no genai test reaches Replicate (research R14, finding F4).

    With ``replicate_mock`` the respx router (``assert_all_mocked=True``) already
    refuses any unmocked request. Without it, the provider is pointed at an
    unroutable host and an empty respx router makes any outgoing request fail.
    """
    if "replicate_mock" in request.fixturenames:
        yield None
        return
    settings = get_settings()
    monkeypatch.setattr(settings, "genai_provider_base_url", UNROUTABLE_PROVIDER)
    assert settings.genai_provider_url == UNROUTABLE_PROVIDER, "test levers must be allowed"
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        yield router


@pytest.fixture
def replicate_mock():
    """respx router on the provider API; anything unmocked fails the test."""
    with respx.mock(assert_all_mocked=True, assert_all_called=False) as router:
        base = provider_url()
        router.get(f"{base}/account").mock(
            return_value=httpx.Response(200, json={"type": "user", "username": "shop-owner"})
        )
        router.get(f"{base}/webhooks/default/secret").mock(
            return_value=httpx.Response(200, json={"key": FAKE_SECRET})
        )
        router.post(f"{base}/files").mock(
            return_value=httpx.Response(
                201, json={"id": "file1", "urls": {"get": f"{base}/files/file1"}}
            )
        )
        router.delete(url__startswith=f"{base}/files/").mock(return_value=httpx.Response(204))
        router.get(url__startswith=DELIVERY).mock(
            side_effect=lambda request: httpx.Response(
                200,
                content=glb_bytes() if request.url.path.endswith(".glb") else png_bytes(),
                headers={
                    "content-type": "model/gltf-binary"
                    if request.url.path.endswith(".glb")
                    else "image/png"
                },
            )
        )
        yield router


@pytest_asyncio.fixture
async def connected_tenant(db_session: AsyncSession, test_tenant: Tenant) -> Tenant:
    return await connect(db_session, test_tenant)


def body_json(obj: dict) -> bytes:
    return json.dumps(obj).encode()


__all__ = [
    "DELIVERY",
    "FAKE_SECRET",
    "FAKE_TOKEN",
    "GENAI",
    "UNROUTABLE_PROVIDER",
    "body_json",
    "connect",
    "connected_tenant",
    "dispatched",
    "genai_storage",
    "glb_bytes",
    "make_output_job",
    "no_real_replicate",
    "png_bytes",
    "prediction",
    "provider_url",
    "replicate_mock",
    "signed_headers",
]
