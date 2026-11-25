"""Backfill cost analysis for existing completed production runs.

Records cost_per_gram_actual, successful_weight_grams, model_weight_grams and
actual_cost_per_unit for completed runs that have none yet -- through
`ProductionRunService.backfill_run_actuals`, the same arithmetic completing a
run uses (task T237). This script used to carry a third copy of the
weight-times-rate sum; a figure computed two ways is two figures.
"""

import asyncio

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.database import async_session_maker
from app.models.production_run import ProductionRun
from app.models.tenant import Tenant
from app.services.production_run import ProductionRunService


async def main() -> None:
    """Main backfill function."""
    print("Starting cost analysis backfill...")

    async with async_session_maker() as db:
        result = await db.execute(
            select(ProductionRun)
            .options(
                selectinload(ProductionRun.items),
                selectinload(ProductionRun.materials),
                selectinload(ProductionRun.plates),
            )
            .where(
                and_(
                    ProductionRun.status == "completed",
                    ProductionRun.cost_per_gram_actual.is_(None),
                )
            )
            .order_by(ProductionRun.completed_at.desc())
        )
        runs = result.scalars().all()
        print(f"Found {len(runs)} completed runs without cost analysis")

        tenants: dict = {}
        updated_count = 0
        for run in runs:
            if run.tenant_id not in tenants:
                tenants[run.tenant_id] = await db.get(Tenant, run.tenant_id)
            service = ProductionRunService(db, tenants[run.tenant_id])
            try:
                if await service.backfill_run_actuals(run):
                    updated_count += 1
                    print(
                        f"  Updated {run.run_number}: cost_per_gram={run.cost_per_gram_actual}, "
                        f"successful_weight={run.successful_weight_grams}g"
                    )
                else:
                    print(f"  Skipping {run.run_number}: no material cost or no successful output")
            except Exception as e:
                print(f"  Error processing {run.run_number}: {e}")

        await db.commit()
        print(f"\nBackfill complete: {updated_count} runs updated")


if __name__ == "__main__":
    asyncio.run(main())
