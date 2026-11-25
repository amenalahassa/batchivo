"""The one place a generation cost is computed (spec 008 FR-025, research R4).

Replicate reports no monetary cost on a prediction. A cost is therefore the
price recorded on the job (its ``price_snapshot``, written once) applied to
what the provider reports: the number of outputs, or ``predict_time`` seconds.
Everything is ``Decimal`` in US dollars (clarification Q1); amounts are
quantised to 4 places only when stored, never in between (constitution IV).
Routes and screens show these figures; they never multiply anything.
"""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_job import ACTIVE_STATUSES, GenerationJob
from app.services.genai.base import ProviderPrediction
from app.services.genai.catalog import CapabilityConfig

STORED = Decimal("0.0001")
ZERO = Decimal("0")


def quantize(amount: Decimal) -> Decimal:
    """An amount as stored: 4 decimal places, half-up."""
    return amount.quantize(STORED, rounding=ROUND_HALF_UP)


def month_start(now: Optional[datetime] = None) -> datetime:
    """The first instant of the current calendar month, UTC."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class GenAICostService:
    """Estimates before submission, final costs after completion, month-to-date usage."""

    @staticmethod
    def _price(snapshot: dict) -> tuple[str, Decimal, int]:
        return (
            str(snapshot.get("unit", "per_run")),
            Decimal(str(snapshot.get("amount_usd", "0"))),
            int(snapshot.get("typical_seconds") or 0),
        )

    def estimate(self, config: CapabilityConfig, count: int) -> Decimal:
        """What a job is expected to cost, before it is submitted."""
        return self.estimate_from_snapshot(config.price.snapshot(), count)

    def estimate_from_snapshot(self, snapshot: dict, count: int) -> Decimal:
        unit, amount, typical = self._price(snapshot)
        if unit == "per_output":
            return quantize(amount * Decimal(max(count, 1)))
        if unit == "per_second":
            return quantize(amount * Decimal(typical))
        return quantize(amount)

    def final(
        self, job: GenerationJob, prediction: Optional[ProviderPrediction], outputs: int
    ) -> tuple[Decimal, str]:
        """The job's cost and its provenance once it has ended.

        ``computed``: the recorded price applied to what the provider reported.
        ``estimated``: nothing to apply it to, so the estimate stands. A job that
        never reached the provider costs nothing.
        """
        if job.submitted_at is None or job.external_id is None:
            return ZERO, "computed"
        unit, amount, _ = self._price(job.price_snapshot or {})
        if unit == "per_output":
            if prediction is not None and prediction.status == "succeeded":
                return quantize(amount * Decimal(outputs)), "computed"
            if prediction is not None and prediction.status in ("failed", "canceled"):
                return ZERO, "computed"
        elif unit == "per_second":
            if prediction is not None and prediction.predict_time is not None:
                seconds = Decimal(str(prediction.predict_time))
                return quantize(amount * seconds), "computed"
        else:
            if prediction is not None:
                return quantize(amount), "computed"
        return quantize(job.estimated_cost or ZERO), "estimated"

    async def month_to_date(
        self, db: AsyncSession, tenant_id: UUID, now: Optional[datetime] = None
    ) -> tuple[Decimal, int]:
        """This UTC month's spend (final costs, plus estimates of active jobs) and job count."""
        start = month_start(now)
        spend = func.coalesce(
            func.sum(
                func.coalesce(GenerationJob.cost, GenerationJob.estimated_cost),
            ),
            0,
        )
        row = (
            await db.execute(
                select(spend, func.count(GenerationJob.id)).where(
                    GenerationJob.tenant_id == tenant_id,
                    GenerationJob.created_at >= start,
                    or_(
                        GenerationJob.status.in_(ACTIVE_STATUSES),
                        GenerationJob.cost.is_not(None),
                    ),
                )
            )
        ).one()
        jobs = (
            await db.execute(
                select(func.count(GenerationJob.id)).where(
                    and_(GenerationJob.tenant_id == tenant_id, GenerationJob.created_at >= start)
                )
            )
        ).scalar_one()
        return quantize(Decimal(str(row[0] or 0))), int(jobs)

    async def usage_by_month(
        self, db: AsyncSession, tenant_id: UUID, months: int
    ) -> list[dict[str, Any]]:
        """Spend and job count for each of the last ``months`` calendar months, newest first."""
        start = month_start()
        out: list[dict[str, Any]] = []
        cursor = start
        for _ in range(max(1, months)):
            nxt = (
                cursor.replace(year=cursor.year + 1, month=1)
                if cursor.month == 12
                else cursor.replace(month=cursor.month + 1)
            )
            row = (
                await db.execute(
                    select(
                        func.coalesce(
                            func.sum(
                                func.coalesce(GenerationJob.cost, GenerationJob.estimated_cost)
                            ),
                            0,
                        ),
                        func.count(GenerationJob.id),
                    ).where(
                        GenerationJob.tenant_id == tenant_id,
                        GenerationJob.created_at >= cursor,
                        GenerationJob.created_at < nxt,
                        or_(
                            GenerationJob.status.in_(ACTIVE_STATUSES),
                            GenerationJob.cost.is_not(None),
                        ),
                    )
                )
            ).one()
            out.append(
                {
                    "month": cursor.strftime("%Y-%m"),
                    "cost": quantize(Decimal(str(row[0] or 0))),
                    "jobs": int(row[1] or 0),
                }
            )
            cursor = (
                cursor.replace(year=cursor.year - 1, month=12)
                if cursor.month == 1
                else cursor.replace(month=cursor.month - 1)
            )
        return out


__all__ = ["GenAICostService", "month_start", "quantize"]
