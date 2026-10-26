"""Measure a large model file after its upload returned (T037, research D3).

Files over ``INLINE_MEASURE_BYTES`` are stored with ``measurement_status =
'pending'`` and measured here, so the upload stays fast (SC-007). The work is
:func:`measure_pending`, which the tests call with their own session; the task
only opens a session with the tenant's RLS context and calls it.

Idempotent: a file whose status is no longer ``pending`` is left alone, so a
redelivered task writes nothing twice. The measurement reaches a model or
product only where it has no dimensions -- an operator's entry still wins
(FR-003).
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import select

from app.tasks.celery_app import celery_app

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


async def measure_pending(
    db: "AsyncSession", tenant: "Tenant", model_file_id: UUID
) -> Optional[str]:
    """Measure one pending file of this tenant; returns its final status, or None."""
    from app.models.model import Model
    from app.models.model_file import ModelFile
    from app.services import mesh_bounds
    from app.services.item_dimensions import apply_measurement, record_measurement
    from app.services.model_file_service import ModelFileService, ModelFileStorageError

    model_file = (
        await db.execute(
            select(ModelFile).where(ModelFile.id == model_file_id, ModelFile.tenant_id == tenant.id)
        )
    ).scalar_one_or_none()
    if model_file is None:
        logger.warning(f"Mesh measurement: file {model_file_id} not found for tenant {tenant.id}")
        return None
    if model_file.measurement_status != "pending":
        return model_file.measurement_status

    try:
        content, _, _ = await ModelFileService(db=db, tenant=tenant).get_file_content(model_file.id)
        extension = "." + model_file.original_filename.rsplit(".", 1)[-1].lower()
        measurement = mesh_bounds.measure(content, extension)
    except (ModelFileStorageError, OSError) as exc:
        logger.warning(f"Mesh measurement: could not read file {model_file.id}: {exc}")
        measurement = mesh_bounds.Measurement(
            overall=None, note="Could not read the stored file", status="failed"
        )
    if measurement is None:
        measurement = mesh_bounds.Measurement(overall=None, note="Not a mesh file", status="failed")

    record_measurement(model_file, measurement)
    model = await db.get(Model, model_file.model_id)
    if model is not None and model.tenant_id == tenant.id:
        await apply_measurement(db, tenant, model, model_file)
    await db.commit()
    logger.info(f"Measured file {model_file.id}: {model_file.measurement_status}")
    return model_file.measurement_status


async def _run(tenant_id: UUID, model_file_id: UUID) -> Optional[str]:
    from app.core.rls import set_rls_context
    from app.database import async_session_maker
    from app.models.tenant import Tenant

    async with async_session_maker() as db:
        await set_rls_context(db, tenant_id=tenant_id)
        tenant = (
            await db.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            logger.warning(f"Mesh measurement names a tenant that is gone: {tenant_id}")
            return None
        return await measure_pending(db, tenant, model_file_id)


@celery_app.task(name="mesh_measure.measure_model_file", bind=True, max_retries=0)
def measure_model_file(self, tenant_id: str, model_file_id: str) -> Optional[str]:
    """Celery entry point; a failure is recorded on the file, not retried."""
    return asyncio.run(_run(UUID(str(tenant_id)), UUID(str(model_file_id))))


__all__ = ["measure_model_file", "measure_pending"]
