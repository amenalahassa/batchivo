"""The periodic sweep that raises a realised-margin alert (task T134).

FR-042: "the operator MUST be alerted when a product's realised margin
diverges from plan beyond a threshold they set". An endpoint alone does not
alert anybody -- it answers a question somebody thought to ask. This sweep is
what notices without being asked.

US7 scenario 3 fixes what the alert must say: not that a product
underperformed, but **which lines moved**. A shortfall whose cause is named is
a decision the operator can make this afternoon; one that is not sends them
through three screens to find out whether it was the fee schedule or the
filament.

## Where the alert goes

The specification left the destination open -- "in-app, email, or both" -- and
it is both (task T172).

* **In-app**: the console reads the same findings from
  ``GET /reconciliation/margin-divergence``.
* **Email**: :func:`deliver` sends one message per tenant to the owners and
  admins of that tenant, through ``email_service``. A log line alone was not a
  destination: FR-042 requires the operator be *alerted*, and a warning in a
  worker's log alerts nobody. The operator sets ``margin_alert_threshold_pct``
  on the pricing-policy screen and must hear about the consequence.

Every finding is still logged as well, whatever happens to the email, because
a sweep whose delivery failed must leave a trace that it found something.

What this module must never grow is a *second* comparison of realised against
planned -- `margin_alert` owns that one (Constitution III). It chooses a
destination and phrases a line; it computes nothing.

## What it never does

It writes nothing. No snapshot moves (FR-038), no estimate is revised -- a
revision is ``variance_service``'s proposal for an operator to accept
(FR-042b) -- and no price changes. Telemetry proposes; it does not reprice.
"""

import asyncio
import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from sqlalchemy import select

from app.core import clock
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.tenant import Tenant
    from app.services.margin_alert import MarginDivergence

logger = logging.getLogger(__name__)

#: How far back a sweep looks. A quarter is long enough that a slow-selling
#: product still has lines to judge, and short enough that the operator is
#: being told about the schedule in force rather than last year's.
DEFAULT_LOOKBACK_DAYS = 90


def describe(divergence: "MarginDivergence") -> str:
    """One line an operator can act on.

    The movements are the point. "GOLD-01 realised 22.1% against 35.3%
    planned" tells them something is wrong; adding "fees +1.80, material
    +0.42" tells them where to look.
    """
    name = divergence.product_name or str(divergence.product_id)
    moved = ", ".join(f"{movement.key} {movement.delta:+}" for movement in divergence.movements)
    return (
        f"{name}: realised {divergence.realised_margin_pct}% against "
        f"{divergence.planned_margin_pct}% planned "
        f"({divergence.divergence_points:+} points, threshold "
        f"{divergence.threshold_points})"
        + (f" -- moved: {moved}" if moved else " -- no cost line moved; check the revenue")
    )


async def recipients(db: "AsyncSession", tenant: "Tenant") -> list[str]:
    """Who hears about a divergence: this tenant's owners and admins.

    A margin is monetary policy, so the alert goes to the roles that can act on
    it. A member who cannot change a price would be told about a problem they
    cannot fix, and a viewer is read-only by definition.

    Addresses are de-duplicated and ordered, so a tenant with one person in two
    roles gets one email and the set is stable between runs.
    """
    from app.models.user import User, UserRole, UserTenant

    rows = await db.execute(
        select(User.email)
        .join(UserTenant, UserTenant.user_id == User.id)
        .where(
            UserTenant.tenant_id == tenant.id,
            UserTenant.role.in_([UserRole.OWNER, UserRole.ADMIN]),
            User.is_active.is_(True),
        )
    )
    return sorted({email for (email,) in rows.all() if email})


async def deliver(
    db: "AsyncSession",
    tenant: "Tenant",
    found: list["MarginDivergence"],
    *,
    since: Optional[date] = None,
) -> int:
    """Email the findings to this tenant's operators. Returns messages sent.

    Delivery failure is reported and swallowed: the sweep's job is to notice,
    and a tenant whose email bounced must not stop the next tenant from being
    told. The findings are in the log either way.
    """
    if not found:
        return 0

    from app.services.email_service import get_email_service

    service = get_email_service()
    if not service.is_configured:
        logger.info(
            "Email is not configured, so %d margin divergence finding(s) for tenant %s "
            "were logged and not sent",
            len(found),
            tenant.id,
        )
        return 0

    addresses = await recipients(db, tenant)
    if not addresses:
        logger.warning(
            "Tenant %s has no active owner or admin to alert about %d margin divergence finding(s)",
            tenant.id,
            len(found),
        )
        return 0

    lines = [describe(divergence) for divergence in found]
    sent = 0
    for address in addresses:
        try:
            if await service.send_margin_divergence_alert(
                address, lines, since=since.isoformat() if since else None
            ):
                sent += 1
        except Exception:  # pragma: no cover - one address must not stop the rest
            logger.error("Could not alert %s about a margin divergence", address, exc_info=True)
    return sent


async def sweep_tenant(
    db: "AsyncSession",
    tenant: "Tenant",
    *,
    since: Optional[date] = None,
) -> list["MarginDivergence"]:
    """Find, log and deliver this tenant's diverging lines.

    Returns them so a caller can do something further with them. Logging
    happens whatever delivery does, so a finding is never lost to a bounced
    email (FR-042, US7 scenario 3).
    """
    from app.services.margin_alert import alerting_products

    if since is None:
        since = clock.today() - timedelta(days=DEFAULT_LOOKBACK_DAYS)

    found = await alerting_products(db, tenant, since=since)
    for divergence in found:
        # Warning, not error: a divergence is a fact about the business, not a
        # malfunction. It is the operator's to act on, and a log at error level
        # would train them to ignore it.
        logger.warning("Realised margin diverges from plan -- %s", describe(divergence))

    if not found:
        logger.info(
            "No realised margin diverges beyond the threshold for tenant %s since %s",
            tenant.id,
            since,
        )
        return found

    await deliver(db, tenant, found, since=since)
    return found


async def _sweep_all(tenant_id: Optional[UUID] = None) -> int:
    """Sweep one tenant, or every active one. Returns the alert count."""
    from app.database import async_session_maker
    from app.models.tenant import Tenant

    total = 0
    async with async_session_maker() as db:
        query = select(Tenant)
        if tenant_id is not None:
            query = query.where(Tenant.id == tenant_id)
        else:
            query = query.where(Tenant.is_active.is_(True))

        for tenant in (await db.execute(query)).scalars().all():
            try:
                total += len(await sweep_tenant(db, tenant))
            except Exception:  # pragma: no cover - one tenant must not stop the rest
                logger.error("Margin alert sweep failed for tenant %s", tenant.id, exc_info=True)
    return total


@celery_app.task(name="margin_alerts.sweep", bind=True, max_retries=0)
def sweep_margin_alerts_task(self: Any, tenant_id: Optional[str] = None) -> int:
    """Celery entry point for the periodic sweep.

    ``max_retries=0``: the sweep is read-only and runs again on the schedule,
    so a retry would only duplicate the warnings an operator has already read.
    """
    return asyncio.run(_sweep_all(UUID(str(tenant_id)) if tenant_id else None))


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "deliver",
    "describe",
    "recipients",
    "sweep_margin_alerts_task",
    "sweep_tenant",
]
