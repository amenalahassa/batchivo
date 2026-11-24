"""Creating a model: the one implementation the models route and idea conversion share.

Moved out of ``api/v1/models.py`` without behaviour change (spec 007, research
R3) so converting an idea creates its model exactly as the models screen does,
inside the caller's transaction: this module flushes, it never commits.
"""

import logging
import uuid
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provenance_http import record_operator_origins, refuse_observed_or_409
from app.auth.dependencies import MONETARY_ROLES, role_in_tenant
from app.models.model import Model
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.model import ModelCreate

logger = logging.getLogger(__name__)

#: Per-item overrides of a tenant rate. `labor_rate_override` replaces the
#: tenant's labour rate for this item and `overhead_percentage` its overhead
#: percentage, so both are monetary policy (FR-007a) -- the owner or admin only,
#: on every path that writes them (task T217).
POLICY_OVERRIDE_FIELDS: frozenset[str] = frozenset({"labor_rate_override", "overhead_percentage"})


async def authorise_model_write(
    db: AsyncSession,
    tenant: Tenant,
    user: User,
    model: Optional[Model],
    changes: dict,
) -> tuple[list[str], Optional[str]]:
    """Check a write to a model's cost inputs, before anything is applied.

    Returns the registered inputs that move, and the caller's role, so the
    route can record each figure's origin once the write is made (FR-001,
    task T229). Refuses with a ``403`` a non-administrator moving a per-item
    rate or percentage (FR-007a, task T217), and with a ``409`` anyone typing
    over an observed figure (FR-004).
    """
    role = await role_in_tenant(db, user.id, tenant.id)
    fields = await refuse_observed_or_409(
        db, tenant, entity_type="model", entity=model, changes=changes
    )
    overrides = sorted(set(fields) & POLICY_OVERRIDE_FIELDS)
    if overrides and role not in MONETARY_ROLES:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Setting an item's {' and '.join(overrides)} overrides the tenant's "
                f"rate and requires the owner or admin role"
            ),
        )
    return fields, role


async def create_model(
    db: AsyncSession,
    tenant: Tenant,
    user: User,
    model_data: ModelCreate,
    *,
    source_idea_id: Optional[uuid.UUID] = None,
) -> Model:
    """
    Create a model for the tenant and record its operator-entered figures.

    SKU must be unique per tenant (400 otherwise). Flushes; the caller commits.
    ``source_idea_id`` is set only by idea conversion; clients cannot send it.
    """
    existing = await db.execute(
        select(Model).where(
            Model.tenant_id == tenant.id,
            Model.sku == model_data.sku,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model with SKU '{model_data.sku}' already exists",
        )

    fields, role = await authorise_model_write(
        db, tenant, user, None, model_data.model_dump(exclude_unset=True)
    )

    model = Model(
        tenant_id=tenant.id,
        source_idea_id=source_idea_id,
        **model_data.model_dump(),
    )

    db.add(model)
    await db.flush()
    # The figures the body named are this person's measurement or, for a
    # per-item rate, their decision -- not assumptions (FR-001, task T229).
    await record_operator_origins(
        db, tenant, entity_type="model", entity_id=model.id, fields=fields, user=user, role=role
    )
    return model
