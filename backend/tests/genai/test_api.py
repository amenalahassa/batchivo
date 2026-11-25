"""HTTP API of the generative AI layer (spec 008): jobs, files, adoption, settings, webhook."""

import json
import logging
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from app.models.generation_job import GenAIAdoption, GenerationJob
from app.models.idea import IdeaEntry
from app.models.product_image import ProductImage
from app.models.user import UserRole
from app.services.genai import runner
from tests.utils.genai import (
    FAKE_SECRET,
    FAKE_TOKEN,
    GENAI,
    connect,
    make_output_job,
    png_bytes,
    prediction,
    provider_url,
    signed_headers,
)
from tests.utils.ideas import idea_in, other_tenant, signed_out

SETTINGS = "/api/v1/settings/replicate"
CONCEPT = {"capability": "concept_image", "inputs": {"prompt": "a clip", "count": 1}}


# ============================================
# Capabilities and estimate
# ============================================


async def test_capabilities_not_connected(client):
    response = await client.get(f"{GENAI}/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is False
    assert body["currency"] == "USD"
    assert {c["capability"] for c in body["capabilities"]} >= {"concept_image", "image_to_3d"}
    mesh = next(c for c in body["capabilities"] if c["capability"] == "image_to_3d")
    assert mesh["pinnable"] is True and mesh["shows_real_item"] is False


async def test_capabilities_requires_auth(unauthenticated_client):
    with signed_out():
        response = await unauthenticated_client.get(f"{GENAI}/capabilities")
    assert response.status_code == 401


async def test_estimate_is_a_decimal_string(client, connected_tenant):
    response = await client.post(
        f"{GENAI}/estimate", json={**CONCEPT, "inputs": {"prompt": "x", "count": 3}}
    )
    assert response.status_code == 200
    assert response.json()["estimated_cost"] == "0.0090"
    assert response.json()["would_exceed_budget"] is False


# ============================================
# Jobs
# ============================================


async def test_create_job_201(client, connected_tenant, dispatched, replicate_mock):
    response = await client.post(f"{GENAI}/jobs", json=CONCEPT)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["estimated_cost"] == "0.0030"
    assert body["currency"] == "USD"
    assert body["can_cancel"] is True
    assert body["price"]["unit"] == "per_output"
    assert dispatched["submit"] == [uuid.UUID(body["id"])]
    assert replicate_mock.calls.call_count == 0


async def test_create_job_not_connected_409(client, dispatched):
    response = await client.post(f"{GENAI}/jobs", json=CONCEPT)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "not_connected"


async def test_create_job_validation_422(client, connected_tenant):
    response = await client.post(
        f"{GENAI}/jobs", json={"capability": "concept_image", "inputs": {}}
    )
    assert response.status_code == 422
    response = await client.post(f"{GENAI}/jobs", json={"inputs": {}})
    assert response.status_code == 422


async def test_create_job_target_404(client, connected_tenant, db_session):
    foreign = await idea_in(db_session, await other_tenant(db_session))
    response = await client.post(
        f"{GENAI}/jobs", json={**CONCEPT, "target": {"type": "idea", "id": str(foreign.id)}}
    )
    assert response.status_code == 404


async def test_create_job_budget_409(client, db_session, test_tenant, replicate_mock):
    await connect(db_session, test_tenant, monthly_budget_usd="0.00")
    response = await client.post(f"{GENAI}/jobs", json=CONCEPT)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "budget_exceeded"
    assert replicate_mock.calls.call_count == 0


async def test_create_job_concurrency_409(client, db_session, connected_tenant, dispatched):
    from app.config import get_settings

    limit = get_settings().genai_max_concurrent_jobs
    for status in (["queued", "running"] * limit)[:limit]:
        await make_output_job(db_session, connected_tenant, status=status)
    await make_output_job(db_session, connected_tenant, status="succeeded")  # not counted
    response = await client.post(f"{GENAI}/jobs", json=CONCEPT)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "concurrency_limit"
    assert dispatched["submit"] == []
    total = await db_session.scalar(select(func.count(GenerationJob.id)))
    assert total == limit + 1  # nothing recorded for the refused request


async def test_create_job_queue_unavailable_503(
    client, db_session, connected_tenant, monkeypatch, replicate_mock
):
    import app.tasks.genai as tasks

    def broker_down(job_id, tenant_id, **kw):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(tasks, "dispatch_submit", broker_down)
    response = await client.post(f"{GENAI}/jobs", json=CONCEPT)
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "queue_unavailable"
    job = await db_session.scalar(select(GenerationJob))
    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "queue_unavailable"
    assert job.cost == Decimal("0")
    assert job.completed_at is not None
    assert replicate_mock.calls.call_count == 0


async def test_viewer_cannot_generate(as_role, connected_tenant, dispatched):
    async with as_role(UserRole.VIEWER) as viewer:
        response = await viewer.post(f"{GENAI}/jobs", json=CONCEPT)
        assert response.status_code == 403
        assert (await viewer.get(f"{GENAI}/jobs")).status_code == 200
    assert dispatched["submit"] == []


async def test_member_can_generate(as_role, connected_tenant, dispatched):
    async with as_role(UserRole.MEMBER) as member:
        assert (await member.post(f"{GENAI}/jobs", json=CONCEPT)).status_code == 201


async def test_list_and_get_jobs(client, db_session, connected_tenant):
    idea = await idea_in(db_session, connected_tenant)
    job, asset = await make_output_job(
        db_session, connected_tenant, target_type="idea", target_id=idea.id
    )
    await make_output_job(db_session, connected_tenant)
    response = await client.get(
        f"{GENAI}/jobs", params={"target_type": "idea", "target_id": str(idea.id)}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    detail = (await client.get(f"{GENAI}/jobs/{job.id}")).json()
    assert detail["model_version_ran"] == "ab" * 32
    assert detail["outputs"][0]["id"] == str(asset.id)
    assert detail["outputs"][0]["file_path"].endswith(f"/assets/{asset.id}/file")
    assert detail["can_cancel"] is False
    assert (await client.get(f"{GENAI}/jobs/{uuid.uuid4()}")).status_code == 404


async def test_jobs_never_cross_tenants(client, db_session, connected_tenant):
    foreign_job, foreign_asset = await make_output_job(db_session, await other_tenant(db_session))
    assert (await client.get(f"{GENAI}/jobs/{foreign_job.id}")).status_code == 404
    assert (await client.get(f"{GENAI}/assets/{foreign_asset.id}/file")).status_code == 404
    assert (await client.post(f"{GENAI}/jobs/{foreign_job.id}/cancel")).status_code == 404
    assert (await client.get(f"{GENAI}/jobs")).json()["total"] == 0


async def test_cancel_job(client, connected_tenant, replicate_mock):
    job_id = (await client.post(f"{GENAI}/jobs", json=CONCEPT)).json()["id"]
    response = await client.post(f"{GENAI}/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "canceled"
    again = await client.post(f"{GENAI}/jobs/{job_id}/cancel")
    assert again.status_code == 409


# ============================================
# Files
# ============================================


async def test_jobs_listed_newest_first_and_paged(client, db_session, connected_tenant):
    """F2: FR-014, US5 AS1: newest first, skip and limit, filters checked."""
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    ids = []
    for day, capability in enumerate(["concept_image", "upscale", "concept_image"]):
        job, _ = await make_output_job(db_session, connected_tenant, capability=capability)
        job.created_at = base + timedelta(days=day)
        ids.append(str(job.id))
    await db_session.commit()
    listed = (await client.get(f"{GENAI}/jobs")).json()
    assert [j["id"] for j in listed["items"]] == ids[::-1]
    assert listed["total"] == 3
    page = (await client.get(f"{GENAI}/jobs", params={"skip": 1, "limit": 1})).json()
    assert [j["id"] for j in page["items"]] == [ids[1]]
    assert page["total"] == 3
    upscales = (await client.get(f"{GENAI}/jobs", params={"capability": "upscale"})).json()
    assert [j["id"] for j in upscales["items"]] == [ids[1]]
    for params in (
        {"limit": 101},
        {"limit": 0},
        {"skip": -1},
        {"capability": "video"},
        {"target_type": "order"},
    ):
        assert (await client.get(f"{GENAI}/jobs", params=params)).status_code == 422, params


async def test_upload_over_ten_megabytes_is_refused(client, connected_tenant):
    from app.api.v1.genai import MAX_UPLOAD_BYTES

    big = png_bytes() + b"\0" * (MAX_UPLOAD_BYTES + 1)
    response = await client.post(f"{GENAI}/uploads", files={"file": ("big.png", big, "image/png")})
    assert response.status_code == 422
    assert "10 MB" in response.text


async def test_upload_input(client, connected_tenant):
    response = await client.post(
        f"{GENAI}/uploads", files={"file": ("in.png", png_bytes(), "image/png")}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "upload" and body["ai_generated"] is False
    file = await client.get(body["file_path"].replace("/api/v1/genai", GENAI))
    assert file.status_code == 200
    assert file.headers["content-type"] == "image/png"
    assert "private" in file.headers["cache-control"]


async def test_upload_rejects_non_image(client, connected_tenant):
    response = await client.post(
        f"{GENAI}/uploads", files={"file": ("a.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 422


async def test_asset_file_thumb_and_auth(
    client, unauthenticated_client, db_session, connected_tenant
):
    _, asset = await make_output_job(db_session, connected_tenant)
    thumb = await client.get(f"{GENAI}/assets/{asset.id}/file", params={"variant": "thumb"})
    assert thumb.status_code == 200
    with signed_out():
        anonymous = await unauthenticated_client.get(f"{GENAI}/assets/{asset.id}/file")
    assert anonymous.status_code == 401


# ============================================
# Adoption
# ============================================


async def test_adopt_into_idea(client, db_session, connected_tenant):
    idea = await idea_in(db_session, connected_tenant)
    job, asset = await make_output_job(
        db_session, connected_tenant, target_type="idea", target_id=idea.id
    )
    response = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt", json={"target": {"type": "idea", "id": str(idea.id)}}
    )
    assert response.status_code == 201, response.text
    entry = await db_session.get(IdeaEntry, uuid.UUID(response.json()["idea_entry_id"]))
    assert entry.kind == "generation"
    assert entry.generation_job_id == job.id
    assert entry.image_url.startswith("/uploads/")
    again = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt", json={"target": {"type": "idea", "id": str(idea.id)}}
    )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "already_adopted"


async def test_adopt_mesh_into_idea_has_no_image(client, db_session, connected_tenant):
    idea = await idea_in(db_session, connected_tenant)
    _, asset = await make_output_job(
        db_session, connected_tenant, capability="image_to_3d", kind="mesh"
    )
    response = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt", json={"target": {"type": "idea", "id": str(idea.id)}}
    )
    assert response.status_code == 201
    entry = await db_session.get(IdeaEntry, uuid.UUID(response.json()["idea_entry_id"]))
    assert entry.image_url is None
    assert "3D" in entry.body


async def test_adopt_into_product_appends_ai_image(
    client, db_session, connected_tenant, test_product
):
    _, asset = await make_output_job(db_session, connected_tenant, capability="lifestyle_scene")
    response = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt",
        json={"target": {"type": "product", "id": str(test_product.id)}, "alt_text": "On a desk"},
    )
    assert response.status_code == 201, response.text
    image = await db_session.get(ProductImage, uuid.UUID(response.json()["product_image_id"]))
    assert image.origin == "ai"
    assert image.is_primary is False
    assert image.alt_text == "On a desk"


@pytest.mark.parametrize("target_type", ["product", "idea"])
async def test_adopted_upscale_keeps_its_resolution(
    client, db_session, connected_tenant, test_product, genai_storage, target_type
):
    """T108: an upscale is not shrunk back to the 800 px a hand upload gets (FR-001)."""
    from io import BytesIO

    from PIL import Image

    from app.models.idea import IdeaEntry
    from app.services.image_storage import get_image_storage
    from tests.utils.ideas import idea_in

    _, asset = await make_output_job(
        db_session, connected_tenant, capability="upscale", content=png_bytes(1600, 1200)
    )
    owner_id = (
        test_product.id
        if target_type == "product"
        else (await idea_in(db_session, connected_tenant)).id
    )
    response = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt",
        json={"target": {"type": target_type, "id": str(owner_id)}},
    )
    assert response.status_code == 201, response.text
    if target_type == "product":
        row = await db_session.get(ProductImage, uuid.UUID(response.json()["product_image_id"]))
    else:
        row = await db_session.get(IdeaEntry, uuid.UUID(response.json()["idea_entry_id"]))
    content, _ = await get_image_storage().get_image(row.image_url)
    assert Image.open(BytesIO(content)).size == (1600, 1200)
    thumb, _ = await get_image_storage().get_image(row.thumbnail_url)
    assert max(Image.open(BytesIO(thumb)).size) <= 300


async def test_concept_into_product_needs_confirmation(
    client, db_session, connected_tenant, test_product, test_user
):
    _, asset = await make_output_job(db_session, connected_tenant, capability="concept_image")
    asset_id = asset.id
    target = {"type": "product", "id": str(test_product.id)}
    refused = await client.post(f"{GENAI}/assets/{asset_id}/adopt", json={"target": target})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "needs_confirmation"
    count = await db_session.scalar(
        select(func.count(ProductImage.id)).where(ProductImage.origin == "ai")
    )
    assert count == 0
    # The refusal rolled the shared test session back; reload what the next request reuses.
    for obj in (connected_tenant, test_user):
        await db_session.refresh(obj)
    confirmed = await client.post(
        f"{GENAI}/assets/{asset_id}/adopt", json={"target": target, "confirm_not_real_item": True}
    )
    assert confirmed.status_code == 201
    adoption = await db_session.scalar(select(GenAIAdoption))
    assert adoption.warning_confirmed is True


async def test_mesh_cannot_become_product_image(client, db_session, connected_tenant, test_product):
    _, asset = await make_output_job(
        db_session, connected_tenant, capability="image_to_3d", kind="mesh"
    )
    response = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt",
        json={
            "target": {"type": "product", "id": str(test_product.id)},
            "confirm_not_real_item": True,
        },
    )
    assert response.status_code == 422


async def test_adopt_unfinished_or_foreign(client, db_session, connected_tenant):
    idea = await idea_in(db_session, connected_tenant)
    _, running = await make_output_job(db_session, connected_tenant, status="running")
    target = {"target": {"type": "idea", "id": str(idea.id)}}
    assert (await client.post(f"{GENAI}/assets/{running.id}/adopt", json=target)).status_code == 409
    _, foreign = await make_output_job(db_session, await other_tenant(db_session))
    assert (await client.post(f"{GENAI}/assets/{foreign.id}/adopt", json=target)).status_code == 404
    _, own = await make_output_job(db_session, connected_tenant)
    no_target = await client.post(
        f"{GENAI}/assets/{own.id}/adopt", json={"target": {"type": "none"}}
    )
    assert no_target.status_code == 422


async def test_viewer_cannot_adopt(as_role, db_session, connected_tenant):
    idea = await idea_in(db_session, connected_tenant)
    _, asset = await make_output_job(db_session, connected_tenant)
    async with as_role(UserRole.VIEWER) as viewer:
        response = await viewer.post(
            f"{GENAI}/assets/{asset.id}/adopt",
            json={"target": {"type": "idea", "id": str(idea.id)}},
        )
    assert response.status_code == 403


# ============================================
# Settings (admin)
# ============================================


async def test_settings_never_return_the_token(client):
    response = await client.put(SETTINGS, json={"api_token": FAKE_TOKEN, "monthly_budget": "25.5"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_configured"] is True
    assert body["token_source"] == "tenant"
    assert body["monthly_budget"] == "25.50"
    assert body["currency"] == "USD"
    assert FAKE_TOKEN not in response.text
    assert FAKE_TOKEN not in (await client.get(SETTINGS)).text


async def test_settings_remove_token_and_budget(client, db_session, test_tenant):
    await client.put(SETTINGS, json={"api_token": FAKE_TOKEN, "monthly_budget": "10"})
    body = (await client.put(SETTINGS, json={"api_token": "", "clear_budget": True})).json()
    assert body["is_configured"] is False
    assert body["monthly_budget"] is None


async def test_settings_422_never_echoes_a_token(client):
    """T077: a refused body is not repeated back (FR-021, SC-006)."""
    long_token = "r8_" + "A" * 230
    too_long = await client.put(SETTINGS, json={"api_token": long_token})
    assert too_long.status_code == 422
    assert "r8_" not in too_long.text
    assert too_long.json()["detail"][0]["loc"] == ["body", "api_token"]
    wrong_key = await client.put(SETTINGS, json={"token": "r8_WrongKeyToken000000000000"})
    assert wrong_key.status_code == 422
    assert "r8_" not in wrong_key.text
    not_json = await client.put(
        SETTINGS, content=b"r8_NotJson", headers={"content-type": "application/json"}
    )
    assert not_json.status_code == 422
    assert "r8_" not in not_json.text


async def test_settings_per_second_override_run_time(client):
    """T076: a per-second override keeps its run time; one out of range is refused."""
    override = {
        "model_ref": "someone/editor",
        "model_version": "official",
        "price_unit": "per_second",
        "price_usd": "0.0014",
        "typical_seconds": 20,
    }
    good = await client.put(SETTINGS, json={"model_overrides": {"image_edit": override}})
    assert good.status_code == 200, good.text
    assert good.json()["model_overrides"]["image_edit"]["typical_seconds"] == 20
    bad = await client.put(
        SETTINGS, json={"model_overrides": {"image_edit": {**override, "typical_seconds": 0}}}
    )
    assert bad.status_code == 422


@pytest.mark.parametrize("version", ["", "   "])
async def test_settings_override_version_cannot_be_blank(client, version):
    """F1: a blank version would run a community model unpinned (FR-002)."""
    response = await client.put(
        SETTINGS,
        json={"model_overrides": {"upscale": {"model_ref": "a/b", "model_version": version}}},
    )
    assert response.status_code == 422


async def test_settings_overrides_must_pin(client):
    bad = await client.put(
        SETTINGS,
        json={"model_overrides": {"upscale": {"model_ref": "a/b", "model_version": "latest"}}},
    )
    assert bad.status_code == 422
    unknown = await client.put(
        SETTINGS,
        json={"model_overrides": {"video": {"model_ref": "a/b", "model_version": "official"}}},
    )
    assert unknown.status_code == 422
    good = await client.put(
        SETTINGS,
        json={
            "model_overrides": {
                "upscale": {
                    "model_ref": "a/b",
                    "model_version": "f" * 64,
                    "price_unit": "per_run",
                    "price_usd": "0.02",
                }
            }
        },
    )
    assert good.status_code == 200
    caps = (await client.get(f"{GENAI}/capabilities")).json()["capabilities"]
    upscale = next(c for c in caps if c["capability"] == "upscale")
    assert upscale["overridden"] is True and upscale["model_ref"] == "a/b"


async def test_settings_cannot_set_platform_permission(client):
    response = await client.put(SETTINGS, json={"platform_token_allowed": True})
    assert response.status_code == 422


async def test_connection_test(client, connected_tenant, replicate_mock):
    response = await client.post(f"{SETTINGS}/test")
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Connected to Replicate",
        "account": "shop-owner",
        "token_source": "tenant",
    }


async def test_connection_test_bad_token(client, connected_tenant, replicate_mock):
    replicate_mock.get(f"{provider_url()}/account").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid token."})
    )
    body = (await client.post(f"{SETTINGS}/test")).json()
    assert body["success"] is False
    assert FAKE_TOKEN not in json.dumps(body)


async def test_usage_by_month(client, db_session, connected_tenant):
    await make_output_job(db_session, connected_tenant)
    job = await db_session.scalar(select(GenerationJob))
    job.cost = Decimal("0.0420")
    await db_session.commit()
    body = (await client.get(f"{SETTINGS}/usage", params={"months": 2})).json()
    assert body["currency"] == "USD"
    assert len(body["months"]) == 2
    assert body["months"][0]["cost"] == "0.0420"
    assert body["months"][0]["jobs"] == 1


async def test_settings_admin_only(as_role):
    async with as_role(UserRole.MEMBER) as member:
        assert (await member.get(SETTINGS)).status_code == 403
        assert (await member.put(SETTINGS, json={"monthly_budget": "1"})).status_code == 403
        # G2/T080: the role check comes before the body (403, not 422).
        assert (await member.put(SETTINGS, json={"api_token": "x" * 300})).status_code == 403


async def test_usage_and_connection_test_admin_only(as_role):
    async with as_role(UserRole.MEMBER) as member:
        assert (await member.get(f"{SETTINGS}/usage")).status_code == 403
        # The role check comes before the range check on ``months``.
        assert (await member.get(f"{SETTINGS}/usage", params={"months": 0})).status_code == 403
        assert (await member.post(f"{SETTINGS}/test")).status_code == 403


@pytest.mark.parametrize("months", [0, 25, -1, "six"])
async def test_usage_months_out_of_range_422(client, months):
    response = await client.get(f"{SETTINGS}/usage", params={"months": months})
    assert response.status_code == 422


async def test_usage_months_bounds_accepted(client):
    for months in (1, 24):
        response = await client.get(f"{SETTINGS}/usage", params={"months": months})
        assert response.status_code == 200
        assert len(response.json()["months"]) == months


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"inputs": {"prompt": "x"}}, None),  # no capability
        ({"capability": "", "inputs": {"prompt": "x"}}, None),
        ({"capability": "x" * 41, "inputs": {"prompt": "x"}}, None),
        ({"capability": "video", "inputs": {"prompt": "x"}}, "input_invalid"),
        ({"capability": "concept_image", "inputs": {}}, "input_invalid"),
        ({"capability": "concept_image", "inputs": {"prompt": ""}}, "input_invalid"),
        ({"capability": "concept_image", "inputs": {"prompt": "x" * 2001}}, "input_invalid"),
        ({"capability": "concept_image", "inputs": {"prompt": "x", "count": 99}}, "input_invalid"),
        ({"capability": "concept_image", "inputs": "a clip"}, None),
    ],
)
async def test_estimate_validation_422(client, connected_tenant, body, code):
    response = await client.post(f"{GENAI}/estimate", json=body)
    assert response.status_code == 422
    if code is not None:
        assert response.json()["detail"]["code"] == code


async def test_settings_needs_sign_in_before_body(unauthenticated_client):
    response = await unauthenticated_client.put(SETTINGS, json={"token": "r8_Stranger0000"})
    assert response.status_code == 401


_ANY = "00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"{GENAI}/estimate"),
        ("POST", f"{GENAI}/jobs"),
        ("GET", f"{GENAI}/jobs"),
        ("GET", f"{GENAI}/jobs/{_ANY}"),
        ("POST", f"{GENAI}/jobs/{_ANY}/cancel"),
        ("POST", f"{GENAI}/uploads"),
        ("POST", f"{GENAI}/assets/{_ANY}/adopt"),
        ("GET", SETTINGS),
        ("POST", f"{SETTINGS}/test"),
        ("GET", f"{SETTINGS}/usage"),
        ("GET", f"/api/v1/platform/tenants/{_ANY}/genai"),
        ("PUT", f"/api/v1/platform/tenants/{_ANY}/genai"),
    ],
)
async def test_every_genai_route_needs_sign_in(unauthenticated_client, method, path):
    """F1: each authenticated genai route answers 401 to a stranger."""
    response = await unauthenticated_client.request(method, path, json={})
    assert response.status_code == 401, (method, path, response.text)


# ============================================
# Platform switch (platform admin)
# ============================================


async def test_platform_switch_requires_platform_admin(client, test_tenant):
    response = await client.put(
        f"/api/v1/platform/tenants/{test_tenant.id}/genai", json={"platform_token_allowed": True}
    )
    assert response.status_code in (401, 403)


async def test_platform_switch_audited(client, db_session, test_tenant, test_user):
    from app.auth.dependencies import get_platform_admin, get_platform_admin_db
    from app.main import app
    from app.models.platform_admin import PlatformAdminAuditLog

    async def admin():
        return test_user

    async def admin_db():
        yield db_session

    app.dependency_overrides[get_platform_admin] = admin
    app.dependency_overrides[get_platform_admin_db] = admin_db
    url = f"/api/v1/platform/tenants/{test_tenant.id}/genai"
    response = await client.put(url, json={"platform_token_allowed": True})
    assert response.status_code == 200
    assert response.json()["platform_token_allowed"] is True
    log = await db_session.scalar(select(PlatformAdminAuditLog))
    assert log.action == "genai_platform_token"
    assert log.action_metadata == {"before": False, "after": True}
    assert (await client.get(f"/api/v1/platform/tenants/{uuid.uuid4()}/genai")).status_code == 404
    bad = await client.put(url, json={"platform_token_allowed": "sometimes"})
    assert bad.status_code == 422


# ============================================
# Webhook
# ============================================


async def _running(client, db_session, tenant, replicate_mock):
    job_id = uuid.UUID((await client.post(f"{GENAI}/jobs", json=CONCEPT)).json()["id"])
    replicate_mock.post(f"{provider_url()}/predictions").mock(
        return_value=httpx.Response(201, json=prediction())
    )
    await runner.submit_job(db_session, tenant, job_id)
    return job_id


def _hook(tenant_id, job_id):
    return f"{GENAI}/webhooks/replicate/{tenant_id}/{job_id}"


async def test_webhook_completes_job(
    client, unauthenticated_client, db_session, connected_tenant, replicate_mock
):
    job_id = await _running(client, db_session, connected_tenant, replicate_mock)
    body = json.dumps(
        prediction(status="succeeded", output=["https://replicate.delivery/xezq/out/1.png"])
    ).encode()
    with signed_out():
        response = await unauthenticated_client.post(
            _hook(connected_tenant.id, job_id), content=body, headers=signed_headers(body)
        )
        assert response.status_code == 204, response.text
        again = await unauthenticated_client.post(
            _hook(connected_tenant.id, job_id), content=body, headers=signed_headers(body)
        )
        assert again.status_code == 204
    job = await db_session.get(GenerationJob, job_id, populate_existing=True)
    assert job.status == "succeeded"
    assert len(job.outputs) == 1


async def test_webhook_bad_signature_changes_nothing(
    client, unauthenticated_client, db_session, connected_tenant, replicate_mock
):
    job_id = await _running(client, db_session, connected_tenant, replicate_mock)
    tenant_id = connected_tenant.id
    body = json.dumps(prediction(status="succeeded", output=["https://x/1.png"])).encode()
    other = "whsec_" + "b3RoZXItc2VjcmV0LWZvci10ZXN0"
    with signed_out():
        response = await unauthenticated_client.post(
            _hook(tenant_id, job_id), content=body, headers=signed_headers(body, other)
        )
        unsigned = await unauthenticated_client.post(_hook(tenant_id, job_id), content=body)
    assert response.status_code == 401
    assert unsigned.status_code == 401
    job = await db_session.get(GenerationJob, job_id, populate_existing=True)
    assert job.status == "running"


async def test_webhook_unknown_job_or_mismatch(
    client, unauthenticated_client, db_session, connected_tenant, replicate_mock
):
    job_id = await _running(client, db_session, connected_tenant, replicate_mock)
    tenant_id = connected_tenant.id
    body = json.dumps(prediction(pid="someone-else", status="succeeded")).encode()
    with signed_out():
        mismatch = await unauthenticated_client.post(
            _hook(tenant_id, job_id), content=body, headers=signed_headers(body)
        )
        unknown = await unauthenticated_client.post(
            _hook(tenant_id, uuid.uuid4()), content=body, headers=signed_headers(body)
        )
    assert mismatch.status_code == 404
    assert unknown.status_code == 404


async def test_webhook_secret_is_cached_encrypted(
    client, unauthenticated_client, db_session, connected_tenant, replicate_mock
):
    job_id = await _running(client, db_session, connected_tenant, replicate_mock)
    body = json.dumps(prediction(status="processing")).encode()
    with signed_out():
        await unauthenticated_client.post(
            _hook(connected_tenant.id, job_id), content=body, headers=signed_headers(body)
        )
    await db_session.refresh(connected_tenant)
    config = connected_tenant.settings["replicate"]
    assert config["webhook_secret_encrypted"]
    assert FAKE_SECRET not in json.dumps(connected_tenant.settings)


# ============================================
# Token never logged; e2e fake closed by default
# ============================================


async def test_token_never_logged_through_a_job(
    client, db_session, connected_tenant, replicate_mock, caplog
):
    caplog.set_level(logging.DEBUG)
    job_id = await _running(client, db_session, connected_tenant, replicate_mock)
    replicate_mock.get(f"{provider_url()}/predictions/pred-1").mock(
        return_value=httpx.Response(401, json={"detail": f"bad token {FAKE_TOKEN}"})
    )
    await runner.poll_job(db_session, connected_tenant, job_id)
    job = await db_session.get(GenerationJob, job_id, populate_existing=True)
    assert job.status == "failed"
    assert FAKE_TOKEN not in (job.error or "")
    assert FAKE_TOKEN not in caplog.text


async def test_e2e_fake_closed_without_hooks(client):
    response = await client.get(f"{GENAI}/e2e-fake/account")
    assert response.status_code == 404


async def test_e2e_fake_status_says_where_jobs_go(client, monkeypatch):
    """T071: the e2e suite runs only when jobs go to the fake, never to Replicate."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "e2e_test_hooks_enabled", True)
    monkeypatch.setattr(settings, "genai_provider_base_url", "https://api.replicate.com/v1")
    response = await client.get(f"{GENAI}/e2e-fake/status")
    assert response.status_code == 200
    assert response.json() == {"provider_is_fake": False}
    monkeypatch.setattr(
        settings, "genai_provider_base_url", "http://localhost:8008/api/v1/genai/e2e-fake/"
    )
    response = await client.get(f"{GENAI}/e2e-fake/status")
    assert response.json() == {"provider_is_fake": True}


async def test_e2e_fake_status_closed_without_hooks(client):
    response = await client.get(f"{GENAI}/e2e-fake/status")
    assert response.status_code == 404


async def test_product_image_origin_defaults_to_photo(db_session, test_product):
    image = ProductImage(
        tenant_id=test_product.tenant_id,
        product_id=test_product.id,
        image_url="/uploads/products/x.png",
        display_order=9,
    )
    db_session.add(image)
    await db_session.commit()
    await db_session.refresh(image)
    assert image.origin == "photo"


@pytest.mark.parametrize("origin", ["scan"])
async def test_product_image_origin_checked(db_session, test_product, origin):
    from sqlalchemy.exc import IntegrityError

    db_session.add(
        ProductImage(
            tenant_id=test_product.tenant_id,
            product_id=test_product.id,
            image_url="/uploads/products/y.png",
            origin=origin,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


# ============================================
# Convergence (findings F1, F4, F5, F10, F11)
# ============================================


async def test_capabilities_report_input_rules(client):
    response = await client.get(f"{GENAI}/capabilities")
    assert response.status_code == 200
    by_name = {c["capability"]: c for c in response.json()["capabilities"]}
    concept = by_name["concept_image"]
    # F1: the no-reference model and price are shown, references up to 4 are offered
    assert concept["model_ref"] == "black-forest-labs/flux-schnell"
    assert concept["price"]["amount_usd"] == "0.003"
    assert concept["max_inputs"] == 4
    # F5: the rules each screen needs, from the service's own validation
    assert concept["inputs"]["prompt"] == {"required": True, "max_length": 2000}
    assert concept["inputs"]["input_assets"] == {"required": False, "min": 0, "max": 4}
    assert concept["inputs"]["count"]["max"] == 4
    assert concept["inputs"]["count"]["max_with_inputs"] == 1
    assert by_name["upscale"]["inputs"]["factor"]["values"] == [2, 4]
    assert by_name["lifestyle_scene"]["inputs"]["scene"]["required"] is True
    assert by_name["image_to_3d"]["inputs"]["input_assets"] == {
        "required": True, "min": 1, "max": 4,
    }  # fmt: skip
    for capability in by_name.values():
        assert capability["inputs"], capability["capability"]
        assert capability["max_inputs"] == capability["inputs"]["input_assets"]["max"]


async def test_concept_accepts_the_offered_references(client, connected_tenant, dispatched):
    uploads = []
    for color in ("red", "green", "blue", "white", "black"):
        response = await client.post(
            f"{GENAI}/uploads", files={"file": ("r.png", png_bytes(color=color), "image/png")}
        )
        uploads.append({"type": "asset", "id": response.json()["id"]})
    four = {
        "capability": "concept_image",
        "inputs": {"prompt": "a hook", "input_assets": uploads[:4]},
    }
    response = await client.post(f"{GENAI}/jobs", json=four)
    assert response.status_code == 201, response.text
    assert response.json()["model_ref"] == "google/nano-banana"
    five = {"capability": "concept_image", "inputs": {"prompt": "a hook", "input_assets": uploads}}
    assert (await client.post(f"{GENAI}/jobs", json=five)).status_code == 422


def _image(fmt: str) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (32, 24), color="teal").save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.mark.parametrize(
    "fmt,content_type", [("GIF", "image/gif"), ("BMP", "image/bmp"), ("TIFF", "image/tiff")]
)
async def test_upload_refuses_other_image_types(client, connected_tenant, fmt, content_type):
    response = await client.post(
        f"{GENAI}/uploads", files={"file": (f"in.{fmt.lower()}", _image(fmt), content_type)}
    )
    assert response.status_code == 422
    assert "JPEG, PNG and WebP" in response.json()["detail"]["message"]


async def test_upload_type_comes_from_the_file(client, connected_tenant):
    """A GIF declared as PNG is still refused; a JPEG and a WebP are accepted as they are."""
    disguised = await client.post(
        f"{GENAI}/uploads", files={"file": ("in.png", _image("GIF"), "image/png")}
    )
    assert disguised.status_code == 422
    for fmt, content_type in (("JPEG", "image/jpeg"), ("WEBP", "image/webp")):
        response = await client.post(
            f"{GENAI}/uploads", files={"file": ("in", _image(fmt), "application/octet-stream")}
        )
        assert response.status_code == 201, response.text
        assert response.json()["content_type"] == content_type


async def test_list_jobs_filters_by_status(client, db_session, connected_tenant):
    done, _ = await make_output_job(db_session, connected_tenant)
    failed, _ = await make_output_job(db_session, connected_tenant, status="failed")
    response = await client.get(f"{GENAI}/jobs", params={"status": "failed"})
    assert response.status_code == 200
    assert [j["id"] for j in response.json()["items"]] == [str(failed.id)]
    assert response.json()["total"] == 1
    succeeded = (await client.get(f"{GENAI}/jobs", params={"status": "succeeded"})).json()
    assert [j["id"] for j in succeeded["items"]] == [str(done.id)]
    assert (await client.get(f"{GENAI}/jobs", params={"status": "bogus"})).status_code == 422


async def test_viewer_cannot_cancel_or_upload(as_role, db_session, connected_tenant):
    job, _ = await make_output_job(db_session, connected_tenant, status="running")
    async with as_role(UserRole.VIEWER) as viewer:
        cancel = await viewer.post(f"{GENAI}/jobs/{job.id}/cancel")
        upload = await viewer.post(
            f"{GENAI}/uploads", files={"file": ("in.png", png_bytes(), "image/png")}
        )
    assert cancel.status_code == 403
    assert upload.status_code == 403
    job = await db_session.get(GenerationJob, job.id, populate_existing=True)
    assert job.status == "running"


async def test_webhook_for_another_tenants_job_changes_nothing(
    client, unauthenticated_client, db_session, connected_tenant, replicate_mock
):
    tenant_id = connected_tenant.id
    job_id = await _running(client, db_session, connected_tenant, replicate_mock)
    other = await connect(db_session, await other_tenant(db_session))
    other_id = other.id
    foreign_job, _ = await make_output_job(db_session, other, status="running")
    foreign_id = foreign_job.id
    body = json.dumps(
        prediction(status="succeeded", output=["https://replicate.delivery/xezq/out/1.png"])
    ).encode()
    with signed_out():
        # this tenant's job named under the other tenant, and the reverse
        crossed = await unauthenticated_client.post(
            _hook(other_id, job_id), content=body, headers=signed_headers(body)
        )
        reverse = await unauthenticated_client.post(
            _hook(tenant_id, foreign_id), content=body, headers=signed_headers(body)
        )
    assert crossed.status_code == 404
    assert reverse.status_code == 404
    job = await db_session.get(GenerationJob, job_id, populate_existing=True)
    assert job.status == "running" and job.outputs == []
    foreign = await db_session.get(GenerationJob, foreign_id, populate_existing=True)
    assert foreign.status == "running"


@pytest.mark.parametrize("target_type", ["idea", "product"])
async def test_adopt_into_a_deleted_target(
    client, db_session, connected_tenant, test_product, target_type
):
    _, asset = await make_output_job(db_session, connected_tenant, capability="upscale")
    if target_type == "idea":
        target = await idea_in(db_session, connected_tenant)
    else:
        target = test_product
    target_id = target.id
    await db_session.delete(target)
    await db_session.commit()
    response = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt",
        json={"target": {"type": target_type, "id": str(target_id)}},
    )
    assert response.status_code == 404
    assert await db_session.scalar(select(func.count(GenAIAdoption.id))) == 0


async def test_unmocked_provider_call_fails():
    """F4: without ``replicate_mock`` the provider points at a fake host and nothing leaves."""
    import respx

    from app.services.genai.providers import get_provider
    from tests.utils.genai import UNROUTABLE_PROVIDER

    provider = get_provider("replicate", FAKE_TOKEN)
    try:
        assert provider._base == UNROUTABLE_PROVIDER
        with pytest.raises(respx.models.AllMockedAssertionError):
            await provider.account()
        with pytest.raises(respx.models.AllMockedAssertionError):
            await httpx.AsyncClient().get("https://api.replicate.com/v1/account")
    finally:
        await provider.aclose()
