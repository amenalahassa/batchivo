"""Building model files in tests: every file belongs to a version (spec 004)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_file_version import ModelFileVersion


async def active_version_id(
    db: AsyncSession, tenant_id: uuid.UUID, model_id: uuid.UUID
) -> uuid.UUID:
    """The model's active version, creating version 1 (active) when it has none."""
    existing = (
        await db.execute(
            select(ModelFileVersion).where(
                ModelFileVersion.model_id == model_id, ModelFileVersion.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing.id
    version = ModelFileVersion(
        tenant_id=tenant_id, model_id=model_id, sequence=1, label="1", is_active=True
    )
    db.add(version)
    await db.flush()
    return version.id
