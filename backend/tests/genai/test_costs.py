"""Month-to-date spend and monthly usage (spec 008, T012, R4, R5, SC-002; T089).

Queried straight from the database: other tenants never count, a month is a
UTC calendar month, an active job counts at its estimate, an ended job at its
recorded cost (0 for one that never reached the provider), and every amount
is a ``Decimal``.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_job import GenerationJob
from app.models.tenant import Tenant
from app.services.genai.costs import GenAICostService, month_start
from tests.utils.ideas import other_tenant

NOW = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
MARCH = datetime(2026, 3, 1, tzinfo=timezone.utc)


async def _job(
    db: AsyncSession,
    tenant: Tenant,
    created_at: datetime,
    *,
    status: str = "succeeded",
    estimate: str = "0.0100",
    cost: Optional[str] = None,
    submitted: bool = True,
) -> GenerationJob:
    job = GenerationJob(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        capability="concept_image",
        provider="replicate",
        model_ref="owner/model",
        model_version="official",
        inputs={"prompt": "a clip"},
        seed=7,
        status=status,
        external_id="pred-1" if submitted else None,
        submitted_at=created_at if submitted else None,
        estimated_cost=Decimal(estimate),
        cost=None if cost is None else Decimal(cost),
        cost_provenance=None if cost is None else "computed",
        price_snapshot={"unit": "per_output", "amount_usd": "0.01"},
        created_at=created_at,
    )
    db.add(job)
    await db.commit()
    return job


# ============================================
# month_to_date
# ============================================


async def test_month_to_date_counts_each_kind_of_job(db_session: AsyncSession, test_tenant: Tenant):
    at = MARCH + timedelta(days=2)
    await _job(db_session, test_tenant, at, status="succeeded", cost="0.0420")
    await _job(db_session, test_tenant, at, status="queued", estimate="0.0300")
    await _job(db_session, test_tenant, at, status="running", estimate="0.0050")
    # Failed before it reached the provider: the runner records a cost of 0.
    await _job(
        db_session, test_tenant, at, status="failed", estimate="0.5000", cost="0", submitted=False
    )

    spend, jobs = await GenAICostService().month_to_date(db_session, test_tenant.id, now=NOW)

    assert spend == Decimal("0.0770")
    assert isinstance(spend, Decimal)
    assert jobs == 4


async def test_month_to_date_excludes_other_tenants(db_session: AsyncSession, test_tenant: Tenant):
    other = await other_tenant(db_session)
    at = MARCH + timedelta(days=1)
    await _job(db_session, other, at, cost="9.0000")
    await _job(db_session, other, at, status="queued", estimate="5.0000")
    await _job(db_session, test_tenant, at, cost="0.0100")

    spend, jobs = await GenAICostService().month_to_date(db_session, test_tenant.id, now=NOW)

    assert (spend, jobs) == (Decimal("0.0100"), 1)


async def test_month_to_date_starts_at_midnight_utc(db_session: AsyncSession, test_tenant: Tenant):
    # The last second of February (UTC) is last month; the first of March counts.
    await _job(db_session, test_tenant, MARCH - timedelta(seconds=1), cost="1.0000")
    await _job(db_session, test_tenant, MARCH, cost="0.2500")
    # 00:30 on 1 March in UTC+2 is still February in UTC.
    plus_two = timezone(timedelta(hours=2))
    await _job(db_session, test_tenant, datetime(2026, 3, 1, 0, 30, tzinfo=plus_two), cost="2.0000")

    spend, jobs = await GenAICostService().month_to_date(db_session, test_tenant.id, now=NOW)

    assert (spend, jobs) == (Decimal("0.2500"), 1)


async def test_month_to_date_when_nothing_ran(db_session: AsyncSession, test_tenant: Tenant):
    spend, jobs = await GenAICostService().month_to_date(db_session, test_tenant.id, now=NOW)
    assert (spend, jobs) == (Decimal("0"), 0)
    assert isinstance(spend, Decimal)


def test_month_start_is_utc():
    plus_two = timezone(timedelta(hours=2))
    assert month_start(datetime(2026, 3, 1, 1, 0, tzinfo=plus_two)) == datetime(
        2026, 2, 1, tzinfo=timezone.utc
    )
    assert month_start(NOW) == MARCH


# ============================================
# usage_by_month
# ============================================


async def test_usage_by_month(db_session: AsyncSession, test_tenant: Tenant):
    # usage_by_month reads the clock: build the months around the real one.
    this_month = month_start()
    last_month = month_start(this_month - timedelta(seconds=1))
    other = await other_tenant(db_session)

    await _job(db_session, test_tenant, this_month, cost="0.0420")
    await _job(db_session, test_tenant, this_month, status="running", estimate="0.0300")
    await _job(db_session, test_tenant, this_month, status="failed", cost="0", submitted=False)
    await _job(db_session, test_tenant, this_month - timedelta(seconds=1), cost="1.5000")
    await _job(db_session, test_tenant, last_month, cost="0.5000")
    await _job(db_session, other, this_month, cost="7.0000")

    rows = await GenAICostService().usage_by_month(db_session, test_tenant.id, 3)

    assert [r["month"] for r in rows] == [
        this_month.strftime("%Y-%m"),
        last_month.strftime("%Y-%m"),
        month_start(last_month - timedelta(seconds=1)).strftime("%Y-%m"),
    ]
    assert [(r["cost"], r["jobs"]) for r in rows] == [
        (Decimal("0.0720"), 3),
        (Decimal("2.0000"), 2),
        (Decimal("0"), 0),
    ]
    assert all(isinstance(r["cost"], Decimal) for r in rows)


async def test_usage_by_month_at_least_one_month(db_session: AsyncSession, test_tenant: Tenant):
    rows = await GenAICostService().usage_by_month(db_session, test_tenant.id, 0)
    assert len(rows) == 1 and rows[0]["cost"] == Decimal("0")
