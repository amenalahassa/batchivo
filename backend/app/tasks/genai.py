"""The worker side of generation jobs (spec 008, research R6).

Thin on purpose: each task opens a session scoped to the job's tenant and calls
one step of :mod:`app.services.genai.runner`, where the tests reach the logic
without a broker. Steps are short and chained by countdown, so a 30-minute
image-to-3D job never holds a worker; ``genai.sweep`` (beat, every 5 minutes)
picks up a chain that a broker restart broke.

``dispatch_submit`` / ``dispatch_poll`` are the seams the request path and the
runner use. With ``GENAI_RUN_INLINE`` (development and e2e only, refused in
production by ``Settings.genai_inline``) they run the same steps as asyncio
tasks in the API process instead.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Optional
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.tasks.celery_app import celery_app
from app.tasks.runner import run_in_task_loop

logger = logging.getLogger(__name__)

_inline_tasks: set[asyncio.Task] = set()


async def _with_tenant(tenant_id: UUID, work: Callable) -> Optional[object]:
    from app.core.rls import set_rls_context
    from app.database import async_session_maker
    from app.models.tenant import Tenant

    async with async_session_maker() as db:
        await set_rls_context(db, tenant_id=tenant_id)
        tenant = await db.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if tenant is None:
            logger.warning(f"Generation step names a tenant that is gone: {tenant_id}")
            return None
        return await work(db, tenant)


async def run_submit(job_id: UUID, tenant_id: UUID, attempt: int = 1) -> Optional[float]:
    from app.services.genai import runner

    delay = await _with_tenant(
        tenant_id, lambda db, tenant: runner.submit_job(db, tenant, job_id, attempt)
    )
    if delay is None:
        return None
    if delay < 0:
        dispatch_submit(job_id, tenant_id, attempt=attempt + 1, delay=5.0 * attempt)
    else:
        dispatch_poll(job_id, tenant_id, delay)
    return delay


async def run_poll(job_id: UUID, tenant_id: UUID) -> Optional[float]:
    from app.services.genai import runner

    delay = await _with_tenant(tenant_id, lambda db, tenant: runner.poll_job(db, tenant, job_id))
    if delay is not None:
        dispatch_poll(job_id, tenant_id, delay)
    return delay


async def run_sweep() -> int:
    """Sweep every active tenant; returns how many jobs it acted on."""
    from app.database import async_session_maker
    from app.models.tenant import Tenant
    from app.services.genai import runner

    async with async_session_maker() as db:
        tenant_ids = list(await db.scalars(select(Tenant.id).where(Tenant.is_active.is_(True))))
    acted = 0
    for tenant_id in tenant_ids:
        result = await _with_tenant(tenant_id, lambda db, tenant: runner.sweep_tenant(db, tenant))
        if not result:
            continue
        acted += result["failed_queued"] + result["timed_out"] + len(result["to_poll"])
        for job_id in result["to_poll"]:
            dispatch_poll(job_id, tenant_id, 0)
    return acted


@celery_app.task(name="genai.submit", bind=True, max_retries=0)
def submit_task(self, job_id: str, tenant_id: str, attempt: int = 1) -> Optional[float]:
    return run_in_task_loop(run_submit(UUID(str(job_id)), UUID(str(tenant_id)), attempt))


@celery_app.task(name="genai.poll", bind=True, max_retries=0)
def poll_task(self, job_id: str, tenant_id: str) -> Optional[float]:
    return run_in_task_loop(run_poll(UUID(str(job_id)), UUID(str(tenant_id))))


@celery_app.task(name="genai.sweep", bind=True, max_retries=0)
def sweep_task(self) -> int:
    return run_in_task_loop(run_sweep())


def _inline(work: Awaitable, delay: float) -> None:
    async def later() -> None:
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            await work
        except Exception as exc:  # noqa: BLE001 - logged; the sweep catches a broken chain
            logger.error(f"Inline generation step failed: {type(exc).__name__}: {exc}")

    task = asyncio.get_running_loop().create_task(later())
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)


def dispatch_submit(
    job_id: UUID, tenant_id: UUID, *, attempt: int = 1, delay: float = 0.0
) -> Optional[str]:
    """Hand a job's submission to a worker. Raises whatever the broker raises."""
    if get_settings().genai_inline:
        _inline(run_submit(job_id, tenant_id, attempt), delay)
        return None
    result = submit_task.apply_async(
        args=[str(job_id), str(tenant_id), attempt], countdown=delay or None
    )
    return getattr(result, "id", None)


def dispatch_poll(job_id: UUID, tenant_id: UUID, delay: float) -> Optional[str]:
    """Schedule the next poll of a running job."""
    if get_settings().genai_inline:
        _inline(run_poll(job_id, tenant_id), delay)
        return None
    try:
        result = poll_task.apply_async(args=[str(job_id), str(tenant_id)], countdown=delay or None)
    except Exception as exc:  # noqa: BLE001 - the sweep re-polls a job whose chain broke
        logger.warning(f"Could not schedule the next poll of job {job_id}: {exc}")
        return None
    return getattr(result, "id", None)


__all__ = [
    "dispatch_poll",
    "dispatch_submit",
    "poll_task",
    "run_poll",
    "run_submit",
    "run_sweep",
    "submit_task",
    "sweep_task",
]
