"""A model's realised unit cost is derived from its runs, never stored (task T255).

The rolling average this replaces was rounded at every completed run and fed
back as the next step's input, so the figure drifted with the order runs
happened to complete in (Constitution IV), and it was a stored copy of what
the per-run records already said (Constitution V).
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production_run import ProductionRun, ProductionRunItem
from app.services.production_run import average_unit_cost, realised_unit_costs


async def _run(
    db: AsyncSession,
    tenant_id,
    model_id,
    unit_cost: str,
    units: int,
    *,
    status: str = "completed",
    day: int = 1,
) -> None:
    run = ProductionRun(
        id=uuid4(),
        tenant_id=tenant_id,
        run_number=f"RUC-{uuid4().hex[:8]}",
        started_at=datetime(2026, 10, day, tzinfo=timezone.utc),
        completed_at=datetime(2026, 10, day, 12, tzinfo=timezone.utc)
        if status == "completed"
        else None,
        status=status,
    )
    db.add(run)
    await db.flush()
    db.add(
        ProductionRunItem(
            id=uuid4(),
            production_run_id=run.id,
            model_id=model_id,
            quantity=units,
            successful_quantity=units,
            failed_quantity=0,
            actual_cost_per_unit=Decimal(unit_cost),
        )
    )
    await db.flush()


class TestTheAverageIsOneUnroundedChain:
    def test_it_weights_each_run_by_its_successful_units(self) -> None:
        # (1.2345 * 3 + 1.1111 * 7 + 0.9999 * 1) / 11 = 12.4811 / 11
        outcomes = [(Decimal("1.2345"), 3), (Decimal("1.1111"), 7), (Decimal("0.9999"), 1)]
        assert average_unit_cost(outcomes) == Decimal("12.4811") / Decimal("11")

    def test_it_does_not_depend_on_the_order_runs_completed_in(self) -> None:
        outcomes = [(Decimal("1.2345"), 3), (Decimal("1.1111"), 7), (Decimal("0.9999"), 1)]
        assert average_unit_cost(outcomes) == average_unit_cost(list(reversed(outcomes)))

    def test_no_successful_units_means_no_figure_not_zero(self) -> None:
        assert average_unit_cost([]) is None
        assert average_unit_cost([(Decimal("1.00"), 0)]) is None


class TestItIsDerivedFromCompletedRuns:
    async def test_a_hand_computed_multi_run_average(
        self, db_session: AsyncSession, test_tenant, test_model
    ) -> None:
        await _run(db_session, test_tenant.id, test_model.id, "1.2345", 3, day=1)
        await _run(db_session, test_tenant.id, test_model.id, "1.1111", 7, day=2)
        await _run(db_session, test_tenant.id, test_model.id, "0.9999", 1, day=3)
        await db_session.commit()

        realised = (await realised_unit_costs(db_session, test_tenant.id, [test_model.id]))[
            test_model.id
        ]

        assert realised.average == Decimal("12.4811") / Decimal("11")
        assert realised.units == 11
        assert realised.last_completed_at is not None
        assert realised.last_completed_at.day == 3

    async def test_a_run_still_in_progress_does_not_count(
        self, db_session: AsyncSession, test_tenant, test_model
    ) -> None:
        await _run(db_session, test_tenant.id, test_model.id, "2.0000", 4)
        await _run(db_session, test_tenant.id, test_model.id, "9.0000", 4, status="in_progress")
        await db_session.commit()

        realised = await realised_unit_costs(db_session, test_tenant.id, [test_model.id])

        assert realised[test_model.id].average == Decimal("2.0000")

    async def test_another_tenants_runs_are_never_read(
        self, db_session: AsyncSession, test_tenant, test_model
    ) -> None:
        await _run(db_session, test_tenant.id, test_model.id, "2.0000", 4)
        await db_session.commit()

        assert await realised_unit_costs(db_session, uuid4(), [test_model.id]) == {}

    async def test_a_model_with_no_runs_has_no_entry(
        self, db_session: AsyncSession, test_tenant, test_model
    ) -> None:
        assert await realised_unit_costs(db_session, test_tenant.id, [test_model.id]) == {}
