"""Row-level security context on a database session.

The policies read two settings: `app.current_tenant_id`, which every tenant
table's policy compares with `tenant_id`, and `app.current_user_id`, which the
`user_tenants` policy also admits, so a user can find their own memberships
before a tenant is chosen (bug rls-unscoped-routes, option a).

Both used to be issued as `SET LOCAL`, which lasts one transaction: a handler
that committed and kept working, or carried on after a rollback, silently lost
its scope and saw no rows. Here the values are recorded on the session and an
`after_begin` listener re-applies them at the start of **every** transaction,
so the scope is a property of the session, not of whichever transaction was
open when it was set.

Everything here is a no-op while `rls_enabled` is off (the development default),
where application-level `tenant_id` filters are the second belt.
"""

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger(__name__)

TENANT_SETTING = "app.current_tenant_id"
USER_SETTING = "app.current_user_id"

_INFO_KEY = "rls_context"
_SET = text("SELECT set_config(:name, :value, true)")


def _enabled() -> bool:
    return bool(get_settings().rls_enabled)


async def set_rls_context(
    session: AsyncSession,
    *,
    tenant_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
) -> None:
    """Scope `session` to a tenant and/or a user, from now until it closes.

    Applied to the open transaction at once, and to every later one by the
    `after_begin` listener below. Passing only one of the two leaves the other
    as it was.
    """
    if not _enabled():
        return
    context: dict[str, str] = session.sync_session.info.setdefault(_INFO_KEY, {})
    changes = {}
    if tenant_id is not None:
        changes[TENANT_SETTING] = str(tenant_id)
    if user_id is not None:
        changes[USER_SETTING] = str(user_id)
    context.update(changes)
    if session.in_transaction():
        for name, value in changes.items():
            await session.execute(_SET, {"name": name, "value": value})
    logger.debug(f"RLS context set: {changes}")


def rls_context(session: AsyncSession) -> dict[str, str]:
    """What the session is scoped to, for tests and diagnostics."""
    return dict(session.sync_session.info.get(_INFO_KEY, {}))


@event.listens_for(Session, "after_begin")
def _reapply_rls_context(session: Session, transaction: Any, connection: Any) -> None:
    for name, value in session.info.get(_INFO_KEY, {}).items():
        connection.execute(_SET, {"name": name, "value": value})
