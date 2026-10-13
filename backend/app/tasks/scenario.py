"""The worker side of a catalogue-wide scenario.

Thin on purpose. The task opens a session, loads the tenant and calls
:func:`app.services.scenario_service.execute_run`; every decision about what a
scenario does lives in the service, where the test suite can reach it without
a broker. A task that contained the logic would be logic only an integration
environment could exercise.

:func:`dispatch_run` is the seam the request path uses. It is a module-level
function rather than ``task.delay`` inlined into the endpoint so that the
endpoint has one thing to patch in tests and one place to catch a broker that
cannot be reached.
"""

import asyncio
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy import select

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run(run_id: UUID, tenant_id: UUID) -> Optional[str]:
    """Execute one scenario in its own session, and report its final state."""
    from app.database import async_session_maker
    from app.models.tenant import Tenant
    from app.services.scenario_service import execute_run

    async with async_session_maker() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            # Nothing to do and nothing to record: the row the state would be
            # written to belongs to a tenant that no longer exists.
            logger.warning(f"Scenario run {run_id} names a tenant that is gone")
            return None
        run = await execute_run(db, tenant, run_id)
        return run.state


@celery_app.task(name="scenario.run", bind=True, max_retries=0)
def run_scenario_task(self, run_id: str, tenant_id: str) -> Optional[str]:
    """Celery entry point.

    ``max_retries=0`` deliberately. A failed run is recorded on the row with
    its reason (FR-044b), and an automatic retry would either restate that
    reason or -- worse -- succeed quietly after an operator had already read
    the failure. Re-running is the operator's call, which is a new request.
    """
    return asyncio.run(_run(UUID(str(run_id)), UUID(str(tenant_id))))


def dispatch_run(run_id: UUID, tenant_id: UUID) -> Optional[str]:
    """Hand a queued run to a worker, returning the task id.

    Raises whatever the broker raises. The caller turns that into a failed run
    with a reason, because a request that returns 202 while nothing was queued
    is the hanging job FR-044b forbids.
    """
    result = run_scenario_task.apply_async(args=[str(run_id), str(tenant_id)])
    return getattr(result, "id", None)


__all__ = ["dispatch_run", "run_scenario_task"]
