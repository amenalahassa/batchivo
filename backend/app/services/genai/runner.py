"""Submit, poll, complete, cancel and sweep generation jobs (research R6, R7).

These are the steps the Celery tasks (``app.tasks.genai``) and the provider
webhook call. Each step is short and idempotent: completion locks the job row
and only acts on a job that is still running, so a webhook and a poll that
report the same prediction complete it once (FR-011).

Outputs are copied into Batchivo storage before a job is marked succeeded: the
provider deletes them after about an hour (FR-009, SC-003).
"""

import logging
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.generation_job import GenAIAsset, GenerationJob
from app.models.tenant import Tenant
from app.services.genai import catalog, credentials
from app.services.genai.base import (
    CANCELED,
    FAILED,
    SUCCEEDED,
    GenAIProvider,
    ProviderError,
    ProviderPrediction,
)
from app.services.genai.capabilities import Capability
from app.services.genai.costs import GenAICostService
from app.services.genai.logging import redact
from app.services.genai.providers import get_provider
from app.services.genai.storage import (
    MAX_IMAGE_BYTES,
    MAX_MESH_BYTES,
    GenAIFileStore,
    GenAIStorageError,
)

logger = logging.getLogger(__name__)

MAX_SUBMIT_ATTEMPTS = 3
MAX_POLL_DELAY = 30.0
STALE_POLL = timedelta(minutes=2)
STALE_QUEUED = timedelta(minutes=10)

_costs = GenAICostService()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def poll_delay(poll_count: int) -> float:
    """Seconds before the next poll: 2 s growing by half each time, capped at 30 s."""
    return min(2.0 * (1.5 ** max(poll_count, 0)), MAX_POLL_DELAY)


def make_provider(name: str, token: str) -> GenAIProvider:
    """The provider adapter for a job (a seam the tests may replace)."""
    return get_provider(name, token)


def job_config(job: GenerationJob, tenant: Tenant) -> catalog.CapabilityConfig:
    """The config a job runs with: the mapping of its capability, its own recorded model."""
    capability = Capability(job.capability)
    has_refs = bool((job.inputs or {}).get("input_assets"))
    base = catalog.resolve(capability, None, has_references=has_refs)
    return replace(base, model_ref=job.model_ref, model_version=job.model_version)


def webhook_url(job: GenerationJob) -> Optional[str]:
    base = get_settings().genai_webhook_base_url.strip().rstrip("/")
    if not base:
        return None
    prefix = get_settings().api_v1_prefix
    return f"{base}{prefix}/genai/webhooks/replicate/{job.tenant_id}/{job.id}"


async def _locked(db: AsyncSession, tenant: Tenant, job_id: uuid.UUID) -> Optional[GenerationJob]:
    return await db.scalar(
        select(GenerationJob)
        .where(GenerationJob.id == job_id, GenerationJob.tenant_id == tenant.id)
        .with_for_update(of=GenerationJob)
        .execution_options(populate_existing=True)
    )


def _provider_for(tenant: Tenant, job: GenerationJob) -> Optional[GenAIProvider]:
    resolved = credentials.resolve(tenant)
    if not resolved.token:
        return None
    return make_provider(job.provider, resolved.token)


async def _delete_provider_files(
    urls: list[str],
    provider: Optional[GenAIProvider],
    tenant: Optional[Tenant],
    job: GenerationJob,
) -> None:
    """Delete input files uploaded to the provider, best effort (R7 step 5, R10).

    A failure is logged and never changes the job: it has already ended.
    """
    urls = [u for u in urls or [] if u and not u.startswith("data:")]
    if not urls:
        return
    own = provider is None
    try:
        if own:
            provider = _provider_for(tenant, job) if tenant is not None else None
            if provider is None:
                return
        for url in urls:
            try:
                await provider.delete_input(url)
            except Exception as exc:  # noqa: BLE001 - best effort, the job has ended
                logger.warning(
                    f"Could not delete an input file of job {job.id} at the provider: "
                    f"{type(exc).__name__}"
                )
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.warning(f"Could not clean up the provider files of job {job.id}: {exc}")
    finally:
        if own and provider is not None:
            await provider.aclose()


async def _job_ended(
    db: AsyncSession,
    job: GenerationJob,
    *,
    tenant: Optional[Tenant] = None,
    provider: Optional[GenAIProvider] = None,
) -> None:
    """Housekeeping once a job reached a final state (already committed)."""
    urls = list(job.provider_files or [])
    if not urls:
        return
    if tenant is None and provider is None:
        tenant = await db.scalar(select(Tenant).where(Tenant.id == job.tenant_id))
    await _delete_provider_files(urls, provider, tenant, job)


async def fail_job(
    db: AsyncSession,
    job: GenerationJob,
    reason: str,
    code: str,
    prediction: Optional[ProviderPrediction] = None,
    *,
    provider: Optional[GenAIProvider] = None,
) -> GenerationJob:
    """End a job as failed with a readable reason (never containing a token)."""
    job.status = "failed"
    job.error = redact(reason)[:2000]
    job.error_code = code
    job.completed_at = _now()
    job.cost, job.cost_provenance = _costs.final(job, prediction, 0)
    await db.commit()
    logger.info(f"Generation job {job.id} failed ({code})")
    await _job_ended(db, job, provider=provider)
    return job


def time_limit_text(seconds: int) -> str:
    """A time limit in words: "10 minutes", "1 hour", "90 seconds"."""
    if seconds >= 3600 and seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours > 1 else ''}"
    if seconds >= 60 and seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes > 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"


# ---------------------------------------------------------------------- submit


async def submit_job(
    db: AsyncSession, tenant: Tenant, job_id: uuid.UUID, attempt: int = 1
) -> Optional[float]:
    """Send a queued job to its provider.

    Returns the delay before the first poll, ``-1.0`` to retry the submission
    (a transient error, attempts left), or ``None`` when nothing more is to do.
    """
    job = await _locked(db, tenant, job_id)
    if job is None or job.status != "queued":
        return None
    provider = _provider_for(tenant, job)
    if provider is None:
        await fail_job(db, job, "Replicate is not connected for this shop", "not_connected")
        return None
    config = job_config(job, tenant)
    files = GenAIFileStore()
    urls: list[str] = []
    submitted = False
    try:
        for asset_id in (job.inputs or {}).get("input_assets") or []:
            asset = await db.scalar(
                select(GenAIAsset).where(
                    GenAIAsset.id == uuid.UUID(str(asset_id)), GenAIAsset.tenant_id == tenant.id
                )
            )
            if asset is None:
                await fail_job(db, job, "An input image no longer exists", "input_missing")
                return None
            content = await files.get(asset.storage_url)
            urls.append(
                await provider.upload_input(
                    content, asset.content_type, asset.original_filename or "input.png"
                )
            )
        payload = catalog.build_provider_input(
            config, SimpleNamespace(**(job.inputs or {})), urls, job.seed
        )
        prediction = await provider.submit(config.version_spec, payload, webhook_url(job))
        submitted = True
    except GenAIStorageError as exc:
        await fail_job(db, job, f"An input image could not be read: {exc.message}", "input_missing")
        return None
    except ProviderError as exc:
        if exc.transient and attempt < MAX_SUBMIT_ATTEMPTS:
            logger.warning(f"Submitting job {job.id} failed (attempt {attempt}): {exc}")
            await db.rollback()
            return -1.0
        await fail_job(db, job, str(exc), exc.code)
        return None
    finally:
        if not submitted:
            # Nothing will run on the files uploaded for this attempt: remove them now.
            await _delete_provider_files(urls, provider, None, job)
        await provider.aclose()

    now = _now()
    job.external_id = prediction.id
    job.provider_files = [u for u in urls if not u.startswith("data:")] or None
    if not config.pinnable and prediction.version:
        job.model_version_ran = str(prediction.version)[:100]
    elif config.pinnable:
        job.model_version_ran = config.model_version
    job.status = "running"
    job.submitted_at = now
    job.started_at = now
    job.deadline_at = now + timedelta(seconds=config.time_limit_s)
    await db.commit()
    logger.info(f"Submitted generation job {job.id} as prediction {prediction.id}")
    if prediction.is_terminal:
        await complete_job(db, tenant, job.id, prediction)
        return None
    return poll_delay(0)


# ---------------------------------------------------------------------- poll


async def poll_job(db: AsyncSession, tenant: Tenant, job_id: uuid.UUID) -> Optional[float]:
    """Check a running job; returns the next delay, or ``None`` when it has ended."""
    job = await db.scalar(
        select(GenerationJob)
        .where(GenerationJob.id == job_id, GenerationJob.tenant_id == tenant.id)
        .execution_options(populate_existing=True)
    )
    if job is None or job.status != "running" or not job.external_id:
        return None
    deadline = _aware(job.deadline_at)
    if deadline is not None and _now() >= deadline:
        await timeout_job(db, tenant, job)
        return None
    provider = _provider_for(tenant, job)
    if provider is None:
        await fail_job(db, job, "Replicate is not connected for this shop", "not_connected")
        return None
    try:
        prediction = await provider.get(job.external_id)
    except ProviderError as exc:
        await provider.aclose()
        if exc.transient:
            job.poll_count += 1
            job.last_polled_at = _now()
            await db.commit()
            return poll_delay(job.poll_count)
        await fail_job(db, job, str(exc), exc.code)
        return None
    if prediction.is_terminal:
        await complete_job(db, tenant, job.id, prediction, provider=provider)
        await provider.aclose()
        return None
    await provider.aclose()
    job.poll_count += 1
    job.last_polled_at = _now()
    await db.commit()
    return poll_delay(job.poll_count)


# ---------------------------------------------------------------------- complete


async def complete_job(
    db: AsyncSession,
    tenant: Tenant,
    job_id: uuid.UUID,
    prediction: ProviderPrediction,
    *,
    provider: Optional[GenAIProvider] = None,
) -> Optional[GenerationJob]:
    """Record a terminal prediction on a running job, once (FR-011)."""
    job = await _locked(db, tenant, job_id)
    if job is None or job.status != "running":
        await db.rollback()
        return job
    if prediction.status == CANCELED:
        job.status = "canceled"
        job.error = job.error or "Canceled at the provider"
        job.error_code = job.error_code or "canceled"
        job.completed_at = _now()
        job.cost, job.cost_provenance = _costs.final(job, prediction, 0)
        await db.commit()
        await _job_ended(db, job, tenant=tenant, provider=provider)
        return job
    if prediction.status == FAILED:
        return await fail_job(
            db, job, prediction.error or "The provider reported a failure", "provider_error",
            prediction, provider=provider,
        )  # fmt: skip
    if prediction.status != SUCCEEDED:
        await db.rollback()
        return job

    config = job_config(job, tenant)
    # Never more outputs than were asked for, estimated and checked against the
    # budget: a model returning extra images is not charged for them (R3, SC-002).
    requested = int((job.inputs or {}).get("count") or 1)
    urls = catalog.extract_output_urls(config, prediction.output)[:requested]
    if not urls:
        return await fail_job(
            db, job, "The provider returned no output", "no_output", prediction, provider=provider
        )
    own_provider = provider is None
    if own_provider:
        provider = _provider_for(tenant, job)
        if provider is None:
            return await fail_job(
                db, job, "Replicate is not connected", "not_connected", prediction
            )
    files = GenAIFileStore()
    stored: list[dict] = []
    try:
        for position, url in enumerate(urls):
            limit = MAX_MESH_BYTES if config.output_kind == "mesh" else MAX_IMAGE_BYTES
            content, content_type = await provider.download(url, limit)
            if config.output_kind == "mesh":
                saved = await files.save_mesh(content, str(job.id))
            else:
                saved = await files.save_image(content, content_type, str(job.id))
            saved["position"] = position
            stored.append(saved)
    except (ProviderError, GenAIStorageError) as exc:
        for saved in stored:
            await files.delete(saved["url"])
            await files.delete(saved.get("thumbnail_url"))
        return await fail_job(
            db,
            job,
            f"The result could not be saved: {exc}",
            "download_failed",
            prediction,
            provider=provider,
        )
    finally:
        if own_provider and provider is not None:
            await provider.aclose()

    for saved in stored:
        db.add(
            GenAIAsset(
                tenant_id=tenant.id,
                job_id=job.id,
                source="output",
                kind=config.output_kind,
                storage_url=saved["url"],
                thumbnail_url=saved.get("thumbnail_url"),
                content_type=saved["content_type"],
                file_size=saved["file_size"],
                width=saved.get("width"),
                height=saved.get("height"),
                original_filename=f"{job.capability}-{saved['position'] + 1}"
                + (".glb" if config.output_kind == "mesh" else ""),
                position=saved["position"],
                ai_generated=True,
                created_by_user_id=job.requested_by_user_id,
            )
        )
    job.status = "succeeded"
    job.completed_at = _now()
    job.cost, job.cost_provenance = _costs.final(job, prediction, len(stored))
    await db.commit()
    logger.info(f"Generation job {job.id} succeeded with {len(stored)} output(s)")
    await _job_ended(db, job, tenant=tenant)
    return job


# ---------------------------------------------------------------------- cancel / timeout


async def _cancel_at_provider(tenant: Tenant, job: GenerationJob) -> Optional[ProviderPrediction]:
    if not job.external_id:
        return None
    provider = _provider_for(tenant, job)
    if provider is None:
        return None
    try:
        await provider.cancel(job.external_id)
        try:
            return await provider.get(job.external_id)
        except ProviderError:
            return None
    except ProviderError as exc:
        logger.warning(f"Could not cancel prediction of job {job.id} at the provider: {exc}")
        return None
    finally:
        await provider.aclose()


async def cancel_job(
    db: AsyncSession, tenant: Tenant, job: GenerationJob, reason: str
) -> GenerationJob:
    """Cancel a queued or running job; a provider failure does not stop the local cancel."""
    if job.status not in ("queued", "running"):
        return job  # a final state never changes, and the provider is not asked
    seen_external_id = job.external_id
    prediction = await _cancel_at_provider(tenant, job)
    job = await _locked(db, tenant, job.id) or job
    if job.status not in ("queued", "running"):
        await db.rollback()
        return job
    if job.external_id and job.external_id != seen_external_id:
        # The submission reached the provider while we were deciding: cancel it there too.
        prediction = await _cancel_at_provider(tenant, job)
    job.status = "canceled"
    job.error = reason
    job.error_code = "canceled_by_user"
    job.completed_at = _now()
    job.cost, job.cost_provenance = _costs.final(job, prediction, 0)
    await db.commit()
    logger.info(f"Generation job {job.id} canceled")
    await _job_ended(db, job, tenant=tenant)
    return job


async def timeout_job(db: AsyncSession, tenant: Tenant, job: GenerationJob) -> GenerationJob:
    """A job past its time limit: cancel it at the provider and record a timeout (FR-013)."""
    if job.status != "running":
        return job
    prediction = await _cancel_at_provider(tenant, job)
    job = await _locked(db, tenant, job.id) or job
    if job.status != "running":
        await db.rollback()
        return job
    limit = job_config(job, tenant).time_limit_s
    return await fail_job(
        db,
        job,
        f"Took longer than {time_limit_text(limit)}: the generation was stopped at its time limit.",
        "timeout",
        prediction,
    )


# ---------------------------------------------------------------------- sweep


async def sweep_tenant(db: AsyncSession, tenant: Tenant, now: Optional[datetime] = None) -> dict:
    """Catch jobs whose task chain broke: stale queued, unpolled running, past deadline."""
    now = now or _now()
    result = {"failed_queued": 0, "timed_out": 0, "to_poll": []}
    jobs = list(
        await db.scalars(
            select(GenerationJob).where(
                GenerationJob.tenant_id == tenant.id,
                GenerationJob.status.in_(("queued", "running")),
            )
        )
    )
    for job in jobs:
        created = _aware(job.created_at) or now
        if job.status == "queued":
            if now - created > STALE_QUEUED:
                await fail_job(db, job, "The job was never picked up by a worker", "stale")
                result["failed_queued"] += 1
            continue
        deadline = _aware(job.deadline_at)
        if deadline is not None and now >= deadline:
            await timeout_job(db, tenant, job)
            result["timed_out"] += 1
            continue
        last = _aware(job.last_polled_at) or _aware(job.submitted_at) or created
        if now - last > STALE_POLL:
            result["to_poll"].append(job.id)
    return result


__all__ = [
    "cancel_job",
    "complete_job",
    "fail_job",
    "job_config",
    "make_provider",
    "poll_delay",
    "poll_job",
    "submit_job",
    "sweep_tenant",
    "time_limit_text",
    "timeout_job",
    "webhook_url",
]
