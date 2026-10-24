"""The HTTP face of the operator-write provenance rule (task T229).

Every console route that writes a cost input calls
:func:`record_operator_origins` with the fields that moved. It records each
one's origin through :func:`app.services.provenance.record_operator_write` and
turns the refusal to type over an observed figure into a ``409``.

Why 409 rather than 403: the operator has the role, and the figure is the
obstacle. A 403 would read as "ask an admin", which would not help -- an
observed figure is refreshed from its source (FR-004). The route's own write
is rolled back with it, so a refused body leaves nothing half-applied.
"""

import uuid
from datetime import date
from typing import Iterable, Mapping, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant
from app.models.user import User
from app.services.provenance import (
    ProvenanceNotEditable,
    changed_fields,
    record_operator_write,
    refuse_overwriting_observed,
)


async def refuse_observed_or_409(
    db: AsyncSession,
    tenant: Tenant,
    *,
    entity_type: str,
    entity: object,
    changes: Mapping[str, object],
) -> list[str]:
    """Return the registered fields ``changes`` would move, or ``409`` first.

    Called *before* a route applies its changes, so a refused body never
    reaches the row. Returns the fields to pass to
    :func:`record_operator_origins` once the write has happened.
    """
    fields = changed_fields(entity_type, entity, changes)
    if entity is None or not fields:
        return fields
    try:
        await refuse_overwriting_observed(
            db,
            tenant,
            entity_type=entity_type,
            entity_id=getattr(entity, "id"),
            fields=fields,
        )
    except ProvenanceNotEditable as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return fields


async def record_operator_origins(
    db: AsyncSession,
    tenant: Tenant,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    fields: Iterable[str],
    user: Optional[User],
    role: Optional[str] = None,
    as_of: Optional[date] = None,
) -> list[str]:
    """Record the origin of each field a person just wrote, or ``409``."""
    try:
        return await record_operator_write(
            db,
            tenant,
            entity_type=entity_type,
            entity_id=entity_id,
            fields=fields,
            user_id=user.id if user is not None else None,
            role=role,
            as_of=as_of,
        )
    except ProvenanceNotEditable as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
