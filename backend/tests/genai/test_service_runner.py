"""GenAIService and the runner steps, end to end on the database (Replicate mocked)."""

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from app.models.generation_job import GenAIAsset, GenerationJob
from app.services.genai import runner
from app.services.genai.errors import (
    BudgetExceeded,
    ConcurrencyLimit,
    InputInvalid,
    NotCancellable,
    NotConnected,
    NotFound,
    QueueUnavailable,
)
from app.services.genai.service import GenAIService, JobRequest
from tests.utils.genai import DELIVERY, connect, png_bytes, prediction, provider_url
from tests.utils.ideas import entry_in, idea_in, other_tenant

CONCEPT = JobRequest("concept_image", {"prompt": "a cable clip", "count": 2})


def _service(db, tenant, user=None):
    return GenAIService(db, tenant, user)


async def _count(db, model=GenerationJob):
    return await db.scalar(select(func.count(model.id)))


def _predictions(mock, **responses):
    """Mock POST /predictions and GET /predictions/pred-1 with given bodies."""
    submit = mock.post(f"{provider_url()}/predictions").mock(
        return_value=httpx.Response(201, json=responses.get("submit", prediction()))
    )
    get = mock.get(f"{provider_url()}/predictions/pred-1")
    if "get" in responses:
        get.mock(side_effect=[httpx.Response(200, json=b) for b in responses["get"]])
    cancel = mock.post(f"{provider_url()}/predictions/pred-1/cancel").mock(
        return_value=httpx.Response(200, json=prediction(status="canceled"))
    )
    return submit, get, cancel


# ============================================
# Creating a job
# ============================================


async def test_create_needs_a_token(db_session, test_tenant, replicate_mock, dispatched):
    with pytest.raises(NotConnected):
        await _service(db_session, test_tenant).create_job(CONCEPT)
    assert await _count(db_session) == 0
    assert replicate_mock.calls.call_count == 0
    assert dispatched["submit"] == []


async def test_create_records_everything_once(
    db_session, connected_tenant, test_user, replicate_mock, dispatched
):
    job = await _service(db_session, connected_tenant, test_user).create_job(CONCEPT)
    assert job.status == "queued"
    assert job.capability == "concept_image"
    assert job.model_ref == "black-forest-labs/flux-schnell"
    assert job.model_version == "official"
    assert job.estimated_cost == Decimal("0.0060")
    assert job.price_snapshot["amount_usd"] == "0.003"
    assert job.inputs["prompt"] == "a cable clip"
    assert job.seed >= 0
    assert job.requested_by_user_id == test_user.id
    assert dispatched["submit"] == [job.id]
    assert replicate_mock.calls.call_count == 0  # submission happens in the worker


async def test_create_validates_inputs(db_session, connected_tenant):
    with pytest.raises(InputInvalid):
        await _service(db_session, connected_tenant).create_job(
            JobRequest("concept_image", {"prompt": ""})
        )
    with pytest.raises(InputInvalid):
        await _service(db_session, connected_tenant).create_job(JobRequest("video", {}))


async def test_budget_refusal_reaches_no_provider(
    db_session, test_tenant, replicate_mock, dispatched
):
    tenant = await connect(db_session, test_tenant, monthly_budget_usd="0.0100")
    db_session.add(
        GenerationJob(
            tenant_id=tenant.id, capability="upscale", provider="replicate", model_ref="m",
            model_version="official", inputs={}, seed=1, status="succeeded",
            estimated_cost=Decimal("0.0080"), cost=Decimal("0.0080"), cost_provenance="computed",
            price_snapshot={},
        )
    )  # fmt: skip
    await db_session.commit()
    with pytest.raises(BudgetExceeded) as err:
        await _service(db_session, tenant).create_job(CONCEPT)
    assert "$0.0100" in err.value.message
    assert await _count(db_session) == 1
    assert replicate_mock.calls.call_count == 0
    assert dispatched["submit"] == []


async def test_estimate_reports_budget(db_session, test_tenant):
    tenant = await connect(db_session, test_tenant, monthly_budget_usd="0.005")
    estimate = await _service(db_session, tenant).estimate(CONCEPT)
    assert estimate.estimated_cost == Decimal("0.0060")
    assert estimate.month_to_date == Decimal("0")
    assert estimate.would_exceed_budget is True


async def test_concurrency_limit(db_session, connected_tenant, replicate_mock, dispatched):
    service = _service(db_session, connected_tenant)
    for _ in range(3):
        await service.create_job(CONCEPT)
    with pytest.raises(ConcurrencyLimit):
        await service.create_job(CONCEPT)
    assert await _count(db_session) == 3
    assert replicate_mock.calls.call_count == 0


async def test_queue_unavailable_fails_the_job(db_session, connected_tenant, monkeypatch):
    import app.tasks.genai as tasks

    def broken(*args, **kwargs):
        raise ConnectionError("redis down")

    monkeypatch.setattr(tasks, "dispatch_submit", broken)
    with pytest.raises(QueueUnavailable):
        await _service(db_session, connected_tenant).create_job(CONCEPT)
    job = await db_session.scalar(select(GenerationJob))
    assert job.status == "failed"
    assert job.error_code == "queue_unavailable"
    assert job.cost == Decimal("0")


async def test_target_must_belong_to_tenant(db_session, connected_tenant):
    foreign = await idea_in(db_session, await other_tenant(db_session))
    with pytest.raises(NotFound):
        await _service(db_session, connected_tenant).create_job(
            JobRequest("concept_image", {"prompt": "x"}, "idea", foreign.id)
        )
    own = await idea_in(db_session, connected_tenant)
    job = await _service(db_session, connected_tenant).create_job(
        JobRequest("concept_image", {"prompt": "x"}, "idea", own.id)
    )
    assert (job.target_type, job.target_id) == ("idea", own.id)


async def test_input_assets_are_tenant_scoped(db_session, connected_tenant, genai_storage):
    other = await other_tenant(db_session)
    foreign_asset = await GenAIService(db_session, other).upload_input(
        png_bytes(), "image/png", "x.png"
    )
    with pytest.raises(NotFound):
        await _service(db_session, connected_tenant).create_job(
            JobRequest(
                "background_remove",
                {"input_assets": [{"type": "asset", "id": str(foreign_asset.id)}]},
            )
        )
    assert await _count(db_session) == 0


async def test_idea_entry_image_is_imported(db_session, connected_tenant, genai_storage):
    from app.services.image_storage import get_image_storage

    stored = await get_image_storage().save_image(
        png_bytes(), "image/png", str(connected_tenant.id), "in.png", owner_type="ideas"
    )
    url = stored["image_url"]
    idea = await idea_in(db_session, connected_tenant)
    entry = await entry_in(db_session, idea, kind="image", image_url=url)
    job = await _service(db_session, connected_tenant).create_job(
        JobRequest(
            "background_remove", {"input_assets": [{"type": "idea_entry", "id": str(entry.id)}]}
        )
    )
    [asset_id] = job.inputs["input_assets"]
    asset = await db_session.get(GenAIAsset, uuid.UUID(asset_id))
    assert asset.source == "upload"
    assert asset.tenant_id == connected_tenant.id


async def test_cancel_finished_job_refused(db_session, connected_tenant):
    job = await _service(db_session, connected_tenant).create_job(CONCEPT)
    job.status = "succeeded"
    await db_session.commit()
    with pytest.raises(NotCancellable):
        await _service(db_session, connected_tenant).cancel_job(job.id)


async def test_cancel_queued_job_without_provider_call(
    db_session, connected_tenant, replicate_mock
):
    job = await _service(db_session, connected_tenant).create_job(CONCEPT)
    job = await _service(db_session, connected_tenant).cancel_job(job.id)
    assert job.status == "canceled"
    assert job.cost == Decimal("0")
    assert replicate_mock.calls.call_count == 0


# ============================================
# Submit, poll, complete
# ============================================


async def _queued(db, tenant, request=CONCEPT):
    return await GenAIService(db, tenant).create_job(request)


async def test_submit_then_poll_to_success(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    outputs = [f"{DELIVERY}/1.png", f"{DELIVERY}/2.png"]
    submit, _, _ = _predictions(
        replicate_mock,
        submit=prediction(status="starting", version="d" * 64),
        get=[
            prediction(status="processing"),
            prediction(status="succeeded", output=outputs, predict_time=1.2),
        ],
    )
    assert await runner.submit_job(db_session, connected_tenant, job.id) == 2.0
    sent = json.loads(submit.calls.last.request.content)
    assert sent["version"] == "black-forest-labs/flux-schnell"
    assert sent["input"]["num_outputs"] == 2
    assert sent["input"]["prompt"] == "a cable clip"
    await db_session.refresh(job)
    assert job.status == "running"
    assert job.external_id == "pred-1"
    assert job.model_version_ran == "d" * 64
    assert job.deadline_at is not None

    assert await runner.poll_job(db_session, connected_tenant, job.id) == 3.0
    assert await runner.poll_job(db_session, connected_tenant, job.id) is None
    await db_session.refresh(job)
    assert job.status == "succeeded"
    assert job.cost == Decimal("0.0060")
    assert job.cost_provenance == "computed"
    assets = list(await db_session.scalars(select(GenAIAsset).where(GenAIAsset.job_id == job.id)))
    assert sorted(a.position for a in assets) == [0, 1]
    assert all(a.ai_generated and a.kind == "image" for a in assets)
    assert all(a.storage_url.startswith("/uploads/generations/") for a in assets)


async def test_pinned_model_records_its_own_version(db_session, connected_tenant, replicate_mock):
    asset = await GenAIService(db_session, connected_tenant).upload_input(
        png_bytes(), "image/png", "in.png"
    )
    job = await _queued(
        db_session,
        connected_tenant,
        JobRequest("upscale", {"input_assets": [{"type": "asset", "id": str(asset.id)}]}),
    )
    submit, _, _ = _predictions(replicate_mock, submit=prediction(version="z" * 64))
    await runner.submit_job(db_session, connected_tenant, job.id)
    sent = json.loads(submit.calls.last.request.content)
    assert sent["version"] == f"nightmareai/real-esrgan:{job.model_version}"
    assert any(str(v).startswith("data:image/png;base64,") for v in sent["input"].values())
    await db_session.refresh(job)
    assert job.model_version_ran == job.model_version


async def test_submit_transient_retries_then_fails(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    job_id = job.id
    replicate_mock.post(f"{provider_url()}/predictions").mock(return_value=httpx.Response(503))
    assert await runner.submit_job(db_session, connected_tenant, job_id, attempt=1) == -1.0
    job = await db_session.get(GenerationJob, job_id, populate_existing=True)
    assert job.status == "queued"
    await db_session.refresh(connected_tenant)
    assert await runner.submit_job(db_session, connected_tenant, job_id, attempt=3) is None
    job = await db_session.get(GenerationJob, job_id, populate_existing=True)
    assert job.status == "failed"
    assert job.error_code == "provider_unavailable"
    assert job.cost == Decimal("0")


async def test_submit_auth_error_fails_readably(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    replicate_mock.post(f"{provider_url()}/predictions").mock(
        return_value=httpx.Response(401, json={"detail": "Invalid token."})
    )
    assert await runner.submit_job(db_session, connected_tenant, job.id) is None
    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "auth"
    assert "Invalid token" in job.error


async def test_provider_failure_is_recorded(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    _predictions(replicate_mock, get=[prediction(status="failed", error="NSFW content")])
    await runner.submit_job(db_session, connected_tenant, job.id)
    assert await runner.poll_job(db_session, connected_tenant, job.id) is None
    await db_session.refresh(job)
    assert (job.status, job.error_code, job.error) == ("failed", "provider_error", "NSFW content")
    assert job.cost == Decimal("0")


async def test_download_failure_fails_and_stores_nothing(
    db_session, connected_tenant, replicate_mock
):
    job = await _queued(db_session, connected_tenant)
    replicate_mock.get("https://gone.replicate.delivery/gone.png").mock(
        return_value=httpx.Response(404)
    )
    _predictions(
        replicate_mock,
        get=[
            prediction(
                status="succeeded",
                output=[f"{DELIVERY}/ok.png", "https://gone.replicate.delivery/gone.png"],
            )
        ],
    )
    await runner.submit_job(db_session, connected_tenant, job.id)
    await runner.poll_job(db_session, connected_tenant, job.id)
    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.error_code == "download_failed"
    assert await _count(db_session, GenAIAsset) == 0


async def test_completion_happens_once(db_session, connected_tenant, replicate_mock):
    from app.services.genai.replicate import parse_prediction

    job = await _queued(db_session, connected_tenant, JobRequest("concept_image", {"prompt": "x"}))
    _predictions(replicate_mock)
    await runner.submit_job(db_session, connected_tenant, job.id)
    done = parse_prediction(prediction(status="succeeded", output=[f"{DELIVERY}/1.png"]))
    await runner.complete_job(db_session, connected_tenant, job.id, done)
    await runner.complete_job(db_session, connected_tenant, job.id, done)
    assert await _count(db_session, GenAIAsset) == 1
    await db_session.refresh(job)
    assert job.cost == Decimal("0.0030")


async def test_image_to_3d_stores_a_mesh(db_session, connected_tenant, replicate_mock):
    asset = await GenAIService(db_session, connected_tenant).upload_input(
        png_bytes(), "image/png", "in.png"
    )
    job = await _queued(
        db_session,
        connected_tenant,
        JobRequest("image_to_3d", {"input_assets": [{"type": "asset", "id": str(asset.id)}]}),
    )
    _predictions(
        replicate_mock,
        get=[
            prediction(
                status="succeeded",
                output={"model_file": f"{DELIVERY}/m.glb", "color_video": f"{DELIVERY}/v.mp4"},
                predict_time=40,
            )
        ],
    )
    await runner.submit_job(db_session, connected_tenant, job.id)
    await runner.poll_job(db_session, connected_tenant, job.id)
    await db_session.refresh(job)
    assert job.status == "succeeded"
    assert job.cost == Decimal("0.0560")
    [mesh] = list(await db_session.scalars(select(GenAIAsset).where(GenAIAsset.job_id == job.id)))
    assert mesh.kind == "mesh"
    assert mesh.content_type == "model/gltf-binary"


async def test_timeout_cancels_at_provider(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    _, get, cancel = _predictions(
        replicate_mock, get=[prediction(status="canceled", predict_time=3)]
    )
    await runner.submit_job(db_session, connected_tenant, job.id)
    job.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()
    assert await runner.poll_job(db_session, connected_tenant, job.id) is None
    await db_session.refresh(job)
    assert cancel.called
    assert (job.status, job.error_code) == ("failed", "timeout")


async def test_cancel_running_job_cancels_at_provider(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    _, _, cancel = _predictions(replicate_mock, get=[prediction(status="canceled")])
    await runner.submit_job(db_session, connected_tenant, job.id)
    job = await GenAIService(db_session, connected_tenant).cancel_job(job.id)
    assert cancel.called
    assert job.status == "canceled"
    assert job.cost == Decimal("0")


async def test_cancel_survives_provider_error(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    _predictions(replicate_mock)
    replicate_mock.post(f"{provider_url()}/predictions/pred-1/cancel").mock(
        return_value=httpx.Response(500)
    )
    await runner.submit_job(db_session, connected_tenant, job.id)
    job = await GenAIService(db_session, connected_tenant).cancel_job(job.id)
    assert job.status == "canceled"


async def test_sweep_catches_broken_chains(db_session, connected_tenant, replicate_mock):
    stale = await _queued(db_session, connected_tenant)
    running = await _queued(db_session, connected_tenant)
    _predictions(replicate_mock)
    await runner.submit_job(db_session, connected_tenant, running.id)
    stale.created_at = datetime.now(timezone.utc) - timedelta(minutes=11)
    await db_session.commit()
    later = datetime.now(timezone.utc) + timedelta(minutes=3)
    result = await runner.sweep_tenant(db_session, connected_tenant, now=later)
    assert result["failed_queued"] == 1
    assert result["to_poll"] == [running.id]
    await db_session.refresh(stale)
    assert (stale.status, stale.error_code) == ("failed", "stale")


async def test_job_of_disconnected_tenant_fails(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    connected_tenant.settings = {}
    await db_session.commit()
    assert await runner.submit_job(db_session, connected_tenant, job.id) is None
    await db_session.refresh(job)
    assert job.error_code == "not_connected"
    assert replicate_mock.calls.call_count == 0


async def test_sweep_times_out_past_deadline(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    _predictions(replicate_mock, get=[prediction(status="canceled")])
    await runner.submit_job(db_session, connected_tenant, job.id)
    later = datetime.now(timezone.utc) + timedelta(minutes=11)
    result = await runner.sweep_tenant(db_session, connected_tenant, now=later)
    assert result["timed_out"] == 1
    await db_session.refresh(job)
    assert job.error_code == "timeout"


async def test_unreadable_provider_answer_is_transient(
    db_session, connected_tenant, replicate_mock
):
    job = await _queued(db_session, connected_tenant)
    _predictions(replicate_mock)
    replicate_mock.get(f"{provider_url()}/predictions/pred-1").mock(
        return_value=httpx.Response(200, content=b"<html>")
    )
    await runner.submit_job(db_session, connected_tenant, job.id)
    assert await runner.poll_job(db_session, connected_tenant, job.id) == 3.0
    await db_session.refresh(job)
    assert job.status == "running"


# ============================================
# Provider input files (R7 step 5, finding F7)
# ============================================


def _large_png() -> bytes:
    """A PNG over the data-URI limit, so it goes through the provider's Files API."""
    import os
    from io import BytesIO

    from PIL import Image

    from app.services.genai.replicate import DATA_URI_MAX_BYTES

    buffer = BytesIO()
    Image.frombytes("RGB", (400, 400), os.urandom(400 * 400 * 3)).save(buffer, format="PNG")
    content = buffer.getvalue()
    assert len(content) > DATA_URI_MAX_BYTES
    return content


async def _large_input_job(db, tenant):
    asset = await GenAIService(db, tenant).upload_input(_large_png(), "image/png", "big.png")
    return await _queued(
        db,
        tenant,
        JobRequest("upscale", {"input_assets": [{"type": "asset", "id": str(asset.id)}]}),
    )


def _file_deletes(mock):
    return [c for c in mock.calls if c.request.method == "DELETE"]


async def test_uploaded_input_deleted_after_success(db_session, connected_tenant, replicate_mock):
    job = await _large_input_job(db_session, connected_tenant)
    _predictions(replicate_mock, get=[prediction(status="succeeded", output=f"{DELIVERY}/1.png")])
    await runner.submit_job(db_session, connected_tenant, job.id)
    await db_session.refresh(job)
    assert job.provider_files == [f"{provider_url()}/files/file1"]
    assert _file_deletes(replicate_mock) == []
    await runner.poll_job(db_session, connected_tenant, job.id)
    await db_session.refresh(job)
    assert job.status == "succeeded"
    [delete] = _file_deletes(replicate_mock)
    assert str(delete.request.url) == f"{provider_url()}/files/file1"


async def test_uploaded_input_deleted_after_failure_and_cancel(
    db_session, connected_tenant, replicate_mock
):
    failed = await _large_input_job(db_session, connected_tenant)
    _predictions(replicate_mock, get=[prediction(status="failed", error="bad")])
    await runner.submit_job(db_session, connected_tenant, failed.id)
    await runner.poll_job(db_session, connected_tenant, failed.id)
    await db_session.refresh(failed)
    assert failed.status == "failed"
    assert len(_file_deletes(replicate_mock)) == 1

    canceled = await _large_input_job(db_session, connected_tenant)
    replicate_mock.get(f"{provider_url()}/predictions/pred-1").mock(
        return_value=httpx.Response(200, json=prediction(status="canceled"))
    )
    await runner.submit_job(db_session, connected_tenant, canceled.id)
    canceled = await GenAIService(db_session, connected_tenant).cancel_job(canceled.id)
    assert canceled.status == "canceled"
    assert len(_file_deletes(replicate_mock)) == 2


async def test_uploaded_input_deleted_when_submit_fails(
    db_session, connected_tenant, replicate_mock
):
    job = await _large_input_job(db_session, connected_tenant)
    replicate_mock.post(f"{provider_url()}/predictions").mock(
        return_value=httpx.Response(422, json={"detail": "bad input"})
    )
    assert await runner.submit_job(db_session, connected_tenant, job.id) is None
    await db_session.refresh(job)
    assert job.status == "failed"
    assert len(_file_deletes(replicate_mock)) == 1


async def test_input_delete_failure_never_fails_the_job(
    db_session, connected_tenant, replicate_mock
):
    job = await _large_input_job(db_session, connected_tenant)
    replicate_mock.delete(url__startswith=f"{provider_url()}/files/").mock(
        return_value=httpx.Response(500)
    )
    _predictions(replicate_mock, get=[prediction(status="succeeded", output=f"{DELIVERY}/1.png")])
    await runner.submit_job(db_session, connected_tenant, job.id)
    await runner.poll_job(db_session, connected_tenant, job.id)
    await db_session.refresh(job)
    assert job.status == "succeeded"
    assert len(_file_deletes(replicate_mock)) == 1


async def test_data_uri_inputs_need_no_delete(db_session, connected_tenant, replicate_mock):
    asset = await GenAIService(db_session, connected_tenant).upload_input(
        png_bytes(), "image/png", "in.png"
    )
    job = await _queued(
        db_session,
        connected_tenant,
        JobRequest("upscale", {"input_assets": [{"type": "asset", "id": str(asset.id)}]}),
    )
    _predictions(replicate_mock, get=[prediction(status="succeeded", output=f"{DELIVERY}/1.png")])
    await runner.submit_job(db_session, connected_tenant, job.id)
    await runner.poll_job(db_session, connected_tenant, job.id)
    await db_session.refresh(job)
    assert job.status == "succeeded"
    assert job.provider_files is None
    assert _file_deletes(replicate_mock) == []


# ============================================
# Time limit reason (finding F12)
# ============================================


def test_time_limit_text():
    assert runner.time_limit_text(600) == "10 minutes"
    assert runner.time_limit_text(1800) == "30 minutes"
    assert runner.time_limit_text(3600) == "1 hour"
    assert runner.time_limit_text(60) == "1 minute"
    assert runner.time_limit_text(90) == "90 seconds"


async def test_timeout_reason_states_the_time_limit(db_session, connected_tenant, replicate_mock):
    job = await _queued(db_session, connected_tenant)
    _predictions(replicate_mock, get=[prediction(status="canceled")])
    await runner.submit_job(db_session, connected_tenant, job.id)
    job.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()
    await runner.poll_job(db_session, connected_tenant, job.id)
    await db_session.refresh(job)
    assert job.error_code == "timeout"
    assert job.error.startswith("Took longer than 10 minutes")
    assert "concept_image" not in job.error


# ============================================
# Final states never change (finding F11)
# ============================================


@pytest.mark.parametrize("final", ["succeeded", "failed", "canceled"])
async def test_final_job_is_immutable(db_session, connected_tenant, replicate_mock, final):
    from app.services.genai.replicate import parse_prediction

    job = await _queued(db_session, connected_tenant, JobRequest("concept_image", {"prompt": "x"}))
    job_id = job.id
    _predictions(
        replicate_mock,
        get=[prediction(status="succeeded", output=[f"{DELIVERY}/1.png"], predict_time=1)],
    )
    await runner.submit_job(db_session, connected_tenant, job_id)
    if final == "succeeded":
        await runner.poll_job(db_session, connected_tenant, job_id)
    elif final == "failed":
        job = await db_session.get(GenerationJob, job_id, populate_existing=True)
        await runner.fail_job(db_session, job, "broken", "provider_error")
    else:
        await GenAIService(db_session, connected_tenant).cancel_job(job_id)

    async def reload():
        return await db_session.get(GenerationJob, job_id, populate_existing=True)

    job = await reload()
    assert job.status == final

    def snapshot(j):
        return (j.status, j.cost, j.cost_provenance, j.error, j.error_code, j.completed_at)

    before = snapshot(job)
    outputs = await _count(db_session, GenAIAsset)

    other = parse_prediction(
        prediction(status="succeeded", output=[f"{DELIVERY}/2.png"], predict_time=99)
    )
    tenant = connected_tenant

    async def fresh_tenant():
        # each late step may end in a rollback, which expires the loaded tenant
        await db_session.refresh(tenant)
        return tenant

    await runner.complete_job(db_session, await fresh_tenant(), job_id, other)
    failed_report = parse_prediction(prediction(status="failed"))
    await runner.complete_job(db_session, await fresh_tenant(), job_id, failed_report)
    assert await runner.poll_job(db_session, await fresh_tenant(), job_id) is None
    await runner.cancel_job(db_session, await fresh_tenant(), await reload(), "late cancel")
    await runner.timeout_job(db_session, await fresh_tenant(), await reload())
    with pytest.raises(NotCancellable):
        await GenAIService(db_session, await fresh_tenant()).cancel_job(job_id)

    assert snapshot(await reload()) == before
    assert await _count(db_session, GenAIAsset) == outputs


# ============================================
# No orphan files after a download failure (finding F11)
# ============================================


async def test_download_failure_leaves_no_files(
    db_session, connected_tenant, replicate_mock, genai_storage
):
    from pathlib import Path

    job = await _queued(db_session, connected_tenant)
    replicate_mock.get("https://gone.replicate.delivery/gone.png").mock(
        return_value=httpx.Response(404)
    )
    outputs = [f"{DELIVERY}/a.png", "https://gone.replicate.delivery/gone.png"]
    _predictions(replicate_mock, get=[prediction(status="succeeded", output=outputs)])
    await runner.submit_job(db_session, connected_tenant, job.id)
    await runner.poll_job(db_session, connected_tenant, job.id)
    await db_session.refresh(job)
    assert job.error_code == "download_failed"
    job_dir = Path(genai_storage.base_path) / "generations" / str(job.id)
    assert not job_dir.exists() or [p for p in job_dir.rglob("*") if p.is_file()] == []


async def test_cancel_racing_a_submission_cancels_at_provider(
    db_session, connected_tenant, replicate_mock
):
    """T069: the cancel decided before the submission stored its prediction id."""
    from types import SimpleNamespace

    job = await _queued(db_session, connected_tenant)
    job_id = job.id
    _, _, cancel = _predictions(replicate_mock, get=[prediction(status="canceled")])
    seen_before_submit = SimpleNamespace(id=job_id, status="queued", external_id=None)
    await runner.submit_job(db_session, connected_tenant, job_id)
    job = await runner.cancel_job(db_session, connected_tenant, seen_before_submit, "stop")
    assert cancel.called
    assert job.status == "canceled"


async def test_extra_outputs_are_neither_stored_nor_charged(
    db_session, connected_tenant, replicate_mock
):
    """F3: a model returning more images than asked stores and charges only those asked."""
    job = await _queued(db_session, connected_tenant)  # count 2
    outputs = [f"{DELIVERY}/1.png", f"{DELIVERY}/2.png", f"{DELIVERY}/3.png"]
    _predictions(replicate_mock, get=[prediction(status="succeeded", output=outputs)])
    await runner.submit_job(db_session, connected_tenant, job.id)
    await runner.poll_job(db_session, connected_tenant, job.id)
    await db_session.refresh(job)
    assert job.status == "succeeded"
    assert await _count(db_session, GenAIAsset) == 2
    assert job.cost == Decimal("0.0060")  # 2 x 0.003, not 3


# ============================================
# Write-once fields never change (finding F2 of round 10, FR-007, T015)
# ============================================

WRITE_ONCE = (
    "capability",
    "provider",
    "model_ref",
    "model_version",
    "inputs",
    "seed",
    "target_type",
    "target_id",
    "estimated_cost",
    "price_snapshot",
    "requested_by_user_id",
    "shows_real_item",
)


def _write_once(job: GenerationJob) -> dict:
    return {name: getattr(job, name) for name in WRITE_ONCE}


@pytest.mark.parametrize("end", ["succeeded", "canceled", "timeout"])
async def test_write_once_fields_never_change(
    db_session, connected_tenant, test_user, replicate_mock, end
):
    job = await _service(db_session, connected_tenant, test_user).create_job(CONCEPT)
    job_id = job.id
    created = _write_once(job)

    # The tenant picks another model after the job was made: the job keeps its own.
    await connect(
        db_session,
        connected_tenant,
        model_overrides={
            "concept_image": {
                "model_ref": "someone/other-model",
                "model_version": "e" * 64,
                "price_unit": "per_image",
                "price_usd": "0.0500",
            }
        },
    )

    async def reload():
        return await db_session.get(GenerationJob, job_id, populate_existing=True)

    submit, _, _ = _predictions(
        replicate_mock,
        submit=prediction(status="starting", version="d" * 64),
        get=[
            prediction(status="processing"),
            prediction(status="succeeded", output=[f"{DELIVERY}/1.png"], predict_time=1),
            prediction(status="canceled", predict_time=1),
        ],
    )
    await runner.submit_job(db_session, connected_tenant, job_id)
    assert json.loads(submit.calls.last.request.content)["version"] == created["model_ref"]
    job = await reload()
    assert _write_once(job) == created
    assert job.model_version_ran == "d" * 64

    if end == "succeeded":
        assert await runner.poll_job(db_session, connected_tenant, job_id) == 3.0
        assert await runner.poll_job(db_session, connected_tenant, job_id) is None
    elif end == "canceled":
        await GenAIService(db_session, connected_tenant).cancel_job(job_id)
    else:
        job.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db_session.commit()
        await runner.poll_job(db_session, connected_tenant, job_id)

    job = await reload()
    assert job.status == {"timeout": "failed"}.get(end, end)
    assert _write_once(job) == created
    assert job.model_version_ran == "d" * 64


# ============================================
# Every input reference, within this tenant only (round 11 F1/F2, FR-032, T105, T106)
# ============================================

EDIT_INPUT = "background_remove"


def _one_input(kind: str, ref_id) -> JobRequest:
    return JobRequest(EDIT_INPUT, {"input_assets": [{"type": kind, "id": str(ref_id)}]})


async def _stored(owner_type: str, owner_id) -> str:
    from app.services.image_storage import get_image_storage

    stored = await get_image_storage().save_image(
        png_bytes(), "image/png", str(owner_id), "in.png", owner_type=owner_type
    )
    return stored["image_url"]


async def _no_input_was_kept(db) -> None:
    await db.rollback()
    assert await _count(db) == 0
    assert await _count(db, GenAIAsset) == 0


async def test_model_image_of_the_model_itself_is_imported(
    db_session, connected_tenant, test_model, genai_storage
):
    test_model.image_url = await _stored("products", test_model.id)
    await db_session.commit()
    job = await _service(db_session, connected_tenant).create_job(
        _one_input("model_image", test_model.id)
    )
    [asset_id] = job.inputs["input_assets"]
    asset = await db_session.get(GenAIAsset, uuid.UUID(asset_id))
    assert (asset.source, asset.tenant_id) == ("upload", connected_tenant.id)
    assert job.shows_real_item is True


@pytest.mark.parametrize(
    "path",
    [
        "foreign",  # another owner's stored image, e.g. another shop's product photo
        "/uploads/../secret.png",
        "/uploads/products/{model}/../../{other}/in.png",
        "https://example.com/clip.png",
    ],
)
async def test_model_image_must_be_its_own_stored_file(
    db_session, connected_tenant, test_model, genai_storage, path
):
    """T105: `Model.image_url` is free text; only the model's own stored file is read."""
    other = uuid.uuid4()
    if path == "foreign":
        url = await _stored("products", other)
    else:
        url = path.format(model=test_model.id, other=other)
    test_model.image_url = url
    await db_session.commit()
    with pytest.raises(InputInvalid):
        await _service(db_session, connected_tenant).create_job(
            _one_input("model_image", test_model.id)
        )
    await _no_input_was_kept(db_session)


async def test_model_without_image_or_of_another_tenant_is_not_found(
    db_session, connected_tenant, test_model
):
    test_model.image_url = None
    await db_session.commit()
    with pytest.raises(NotFound):
        await _service(db_session, connected_tenant).create_job(
            _one_input("model_image", test_model.id)
        )
    with pytest.raises(NotFound):
        await _service(db_session, connected_tenant).create_job(
            _one_input("model_image", uuid.uuid4())
        )
    await _no_input_was_kept(db_session)


async def test_model_of_another_tenant_is_not_found(db_session, connected_tenant, genai_storage):
    """T110: a real foreign model, with its own stored image, is never read."""
    from decimal import Decimal

    from app.models.model import Model

    other = await other_tenant(db_session)
    foreign = Model(
        id=uuid.uuid4(),
        tenant_id=other.id,
        sku="FOREIGN-001",
        name="Foreign model",
        print_time_minutes=60,
        labor_hours=Decimal("0.25"),
        is_active=True,
    )
    foreign.image_url = await _stored("products", foreign.id)
    db_session.add(foreign)
    await db_session.commit()
    before = {p for p in genai_storage.base_path.rglob("*") if p.is_file()}
    with pytest.raises(NotFound):
        await _service(db_session, connected_tenant).create_job(
            _one_input("model_image", foreign.id)
        )
    assert {p for p in genai_storage.base_path.rglob("*") if p.is_file()} == before
    await _no_input_was_kept(db_session)


async def test_inputs_of_another_tenant_are_not_found(
    db_session, connected_tenant, test_product, genai_storage
):
    from app.models.product_image import ProductImage

    other = await other_tenant(db_session)
    foreign_idea = await idea_in(db_session, other)
    foreign_entry = await entry_in(
        db_session, foreign_idea, kind="image", image_url=await _stored("ideas", other.id)
    )
    foreign_image = ProductImage(
        tenant_id=other.id,
        product_id=test_product.id,
        image_url=await _stored("products", test_product.id),
        display_order=0,
    )
    db_session.add(foreign_image)
    await db_session.commit()
    for kind, ref_id in (("idea_entry", foreign_entry.id), ("product_image", foreign_image.id)):
        with pytest.raises(NotFound):
            await _service(db_session, connected_tenant).create_job(_one_input(kind, ref_id))
    await _no_input_was_kept(db_session)


# An image entry always has its image (CHECK ck_idea_entries_image): an entry without one is
# not found as an input, and a note that carries one is still not an image.
@pytest.mark.parametrize("with_image,error", [(False, NotFound), (True, InputInvalid)])
async def test_idea_entry_must_be_an_image(
    db_session, connected_tenant, genai_storage, with_image, error
):
    idea = await idea_in(db_session, connected_tenant)
    url = await _stored("ideas", connected_tenant.id) if with_image else None
    entry = await entry_in(db_session, idea, kind="note", image_url=url)
    with pytest.raises(error):
        await _service(db_session, connected_tenant).create_job(_one_input("idea_entry", entry.id))
    await _no_input_was_kept(db_session)


async def test_a_mesh_is_not_an_image_input(db_session, connected_tenant, genai_storage):
    from tests.utils.genai import make_output_job

    _, mesh = await make_output_job(
        db_session, connected_tenant, capability="image_to_3d", kind="mesh"
    )
    jobs = await _count(db_session)
    with pytest.raises(InputInvalid, match="Only images"):
        await _service(db_session, connected_tenant).create_job(_one_input("asset", mesh.id))
    await db_session.rollback()
    assert await _count(db_session) == jobs


async def test_a_source_missing_from_storage_is_not_found(
    db_session, connected_tenant, genai_storage
):
    idea = await idea_in(db_session, connected_tenant)
    entry = await entry_in(
        db_session, idea, kind="image", image_url=f"/uploads/ideas/{uuid.uuid4()}/gone.png"
    )
    with pytest.raises(NotFound):
        await _service(db_session, connected_tenant).create_job(_one_input("idea_entry", entry.id))
    await _no_input_was_kept(db_session)


async def test_a_failing_second_input_removes_the_first_import(
    db_session, connected_tenant, genai_storage
):
    idea = await idea_in(db_session, connected_tenant)
    entry = await entry_in(
        db_session, idea, kind="image", image_url=await _stored("ideas", connected_tenant.id)
    )
    before = {p for p in genai_storage.base_path.rglob("*") if p.is_file()}
    with pytest.raises(NotFound):
        await _service(db_session, connected_tenant).create_job(
            JobRequest(
                "concept_image",
                {
                    "prompt": "a visor clip",
                    "input_assets": [
                        {"type": "idea_entry", "id": str(entry.id)},
                        {"type": "asset", "id": str(uuid.uuid4())},
                    ],
                },
            )
        )
    after = {p for p in genai_storage.base_path.rglob("*") if p.is_file()}
    assert after == before  # the imported copy and its thumbnail are gone
    await _no_input_was_kept(db_session)
