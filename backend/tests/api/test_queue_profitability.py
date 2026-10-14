"""Ordering the queue by what each job earns per machine-hour (T117, FR-043).

The judgement this ranking exists to make possible: a printer running a job
that earns CA$0.40 an hour instead of one that earns CA$2.40 has cost the shop
two pounds an hour, and no margin percentage reveals that -- both jobs can show
a healthy margin.

What is pinned here is as much about restraint as about ordering:

- **Priority still wins.** It is the operator's own decision (FR-002), and an
  economic figure must not override "this one is urgent".
- **A job with no figure sorts last with a reason**, never as though it earned
  nothing. "Nobody timed this print" and "this loses money" are opposite facts,
  and ranking them together buries the one that can be fixed.
- **The arithmetic is the engine's.** The queue asks the same margin path a
  pricing screen asks, so the two cannot disagree (Constitution III).
"""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio

from app.core import clock
from app.models.fee_rule import FeeRule
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.print_job import JobPriority, JobStatus, PrintJob
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.models.spool import Spool
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.services.print_queue_service import PrintQueueService

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world(db_session, test_tenant, test_filament_type):
    """Two printable products: a quick one and a slow one at the same price.

    Same price, same material, same labor -- the slow one simply occupies a
    machine for four times as long. Under a margin ranking they are nearly
    indistinguishable; under this one they are not.
    """
    db_session.add(
        TenantPricingPolicy(
            id=uuid4(),
            tenant_id=test_tenant.id,
            print_labor_rate=Decimal("25.00"),
            finishing_labor_rate=Decimal("25.00"),
            overhead_method="per_machine_hour",
            overhead_monthly_pool=Decimal("180.00"),
            expected_monthly_machine_hours=Decimal("600"),
            electricity_rate_per_kwh=Decimal("0.13"),
            default_machine_rate_per_hour=Decimal("0.23235"),
            margin_basis="customer_total",
            effective_from=clock.today() - timedelta(days=30),
        )
    )

    spool = Spool(
        id=uuid4(),
        tenant_id=test_tenant.id,
        filament_type_id=test_filament_type.id,
        spool_id=f"QUEUE-{uuid4().hex[:6]}",
        initial_weight=Decimal("1000"),
        current_weight=Decimal("900"),
        purchase_price=Decimal("31.00"),
        unusable_remainder_grams=Decimal("25"),
        is_active=True,
        is_labeled=True,
    )
    db_session.add(spool)
    await db_session.flush()

    channel = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Queue Marketplace",
        platform_type="etsy",
        monthly_cost=Decimal("0"),
        currency_code="CAD",
        tax_remitter="marketplace",
        expected_discount_pct=Decimal("0"),
        expected_refund_pct=Decimal("0"),
        is_active=True,
    )
    db_session.add(channel)
    await db_session.flush()

    db_session.add(
        FeeRule(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sales_channel_id=channel.id,
            name="transaction",
            basis="item_subtotal",
            rate_pct=Decimal("6.5"),
            fixed_amount=Decimal("0.30"),
            sort_order=10,
            applies_from=clock.today() - timedelta(days=90),
        )
    )

    products: dict[str, Product] = {}
    for label, minutes in (("quick", 150), ("slow", 600)):
        model = Model(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sku=f"QUEUE-MODEL-{label}-{uuid4().hex[:6]}",
            name=f"{label} part",
            print_time_minutes=minutes,
            prints_per_plate=1,
            waste_grams=Decimal("3"),
            expected_yield=Decimal("0.92"),
            failure_mode="per_part",
            labor_hours_per_item=Decimal("0.25"),
            is_active=True,
        )
        db_session.add(model)
        await db_session.flush()
        db_session.add(
            ModelMaterial(
                id=uuid4(),
                model_id=model.id,
                spool_id=spool.id,
                weight_grams=Decimal("142"),
                cost_per_gram=spool.cost_per_gram,
            )
        )

        product = Product(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sku=f"QUEUE-PROD-{label}-{uuid4().hex[:6]}",
            name=f"{label} product",
            packaging_cost=Decimal("0.92"),
            packaging_quantity=1,
            units_in_stock=5,
            is_active=True,
        )
        db_session.add(product)
        await db_session.flush()
        db_session.add(
            ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1)
        )
        db_session.add(
            ProductPricing(
                id=uuid4(),
                product_id=product.id,
                sales_channel_id=channel.id,
                list_price=Decimal("64.99"),
                valid_from=clock.today() - timedelta(days=10),
            )
        )
        products[label] = product

    await db_session.commit()
    return {"channel": channel, "products": products}


async def queue_job(db_session, test_tenant, *, product=None, model_id=None, priority=None):
    job = PrintJob(
        id=uuid4(),
        tenant_id=test_tenant.id,
        product_id=product.id if product is not None else None,
        model_id=model_id,
        quantity=1,
        priority=priority or JobPriority.NORMAL,
        status=JobStatus.PENDING,
    )
    db_session.add(job)
    await db_session.commit()
    return job


def service(db_session, test_tenant) -> PrintQueueService:
    return PrintQueueService(db_session, test_tenant)


class TestOrderingByEarningsPerMachineHour:
    async def test_the_quick_job_outranks_the_slow_one(
        self, db_session, test_tenant, world
    ) -> None:
        # Same price and nearly the same margin; four times the machine time.
        slow = await queue_job(db_session, test_tenant, product=world["products"]["slow"])
        quick = await queue_job(db_session, test_tenant, product=world["products"]["quick"])

        ranking = await service(db_session, test_tenant).profitability_ranking()

        assert [entry.job.id for entry in ranking] == [quick.id, slow.id]

    async def test_arrival_order_does_not_decide_it(self, db_session, test_tenant, world) -> None:
        # The slow job was queued first. Under the queue's default order it
        # would print first, which is the behaviour this ranking replaces.
        await queue_job(db_session, test_tenant, product=world["products"]["slow"])
        await queue_job(db_session, test_tenant, product=world["products"]["quick"])

        ranking = await service(db_session, test_tenant).profitability_ranking()

        assert ranking[0].profit_per_machine_hour > ranking[1].profit_per_machine_hour

    async def test_each_entry_reports_the_figure_it_was_ranked_on(
        self, db_session, test_tenant, world
    ) -> None:
        # A ranking an operator cannot check is one they have to trust.
        await queue_job(db_session, test_tenant, product=world["products"]["quick"])

        entry = (await service(db_session, test_tenant).profitability_ranking())[0]

        assert entry.profit_per_machine_hour is not None
        assert entry.machine_hours == Decimal("2.5")
        assert entry.margin_pct is not None

    async def test_the_figure_matches_the_margin_path(self, db_session, test_tenant, world) -> None:
        # Constitution III, asserted rather than assumed: the queue must report
        # what the margin engine reports at that price.
        from app.services import fee_engine
        from app.services.cost_resolution import cost_load_options, product_cost_breakdown
        from app.services.costing import CostingService
        from app.services.pricing_policy import resolve_cost_policy
        from sqlalchemy import select

        await queue_job(db_session, test_tenant, product=world["products"]["quick"])
        entry = (await service(db_session, test_tenant).profitability_ranking())[0]

        product = (
            await db_session.execute(
                select(Product)
                .where(Product.id == world["products"]["quick"].id)
                .options(*cost_load_options())
            )
        ).scalar_one()
        policy = await resolve_cost_policy(db_session, test_tenant)
        breakdown = await product_cost_breakdown(db_session, test_tenant, product, policy=policy)
        channel = world["channel"]
        context, treatment = fee_engine.exclusive_context(item_subtotal=Decimal("64.99"))
        expected = CostingService.margin(
            context=context,
            make_cost=breakdown.total_make_cost,
            channel=channel,
            fees=fee_engine.compute(
                channel, context, clock.today(), rules=list(channel.fee_rules or [])
            ),
            policy=policy,
            tax=treatment,
            machine_hours=breakdown.machine_hours,
        )

        assert entry.profit_per_machine_hour == expected.profit_per_machine_hour


class TestWhatTheRankingRefusesToDecide:
    async def test_priority_still_comes_first(self, db_session, test_tenant, world) -> None:
        # FR-002: somebody marked this urgent. An economic figure does not
        # overrule a person's decision about their own shop.
        urgent_slow = await queue_job(
            db_session,
            test_tenant,
            product=world["products"]["slow"],
            priority=JobPriority.URGENT,
        )
        await queue_job(db_session, test_tenant, product=world["products"]["quick"])

        ranking = await service(db_session, test_tenant).profitability_ranking()

        assert ranking[0].job.id == urgent_slow.id

    async def test_a_job_with_no_figure_sorts_last(
        self, db_session, test_tenant, world, test_model
    ) -> None:
        await queue_job(db_session, test_tenant, model_id=test_model.id)
        priced = await queue_job(db_session, test_tenant, product=world["products"]["slow"])

        ranking = await service(db_session, test_tenant).profitability_ranking()

        assert ranking[0].job.id == priced.id
        assert ranking[-1].profit_per_machine_hour is None

    async def test_it_says_why_a_job_has_no_figure(
        self, db_session, test_tenant, world, test_model
    ) -> None:
        # "Nobody priced this" is fixable; "this loses money" is a decision.
        # Ranking them alike would bury the first.
        await queue_job(db_session, test_tenant, model_id=test_model.id)

        entry = (await service(db_session, test_tenant).profitability_ranking())[0]

        assert entry.profit_per_machine_hour is None
        assert "model" in (entry.reason or "")

    async def test_an_unpriced_product_says_so(
        self, db_session, test_tenant, world, test_product
    ) -> None:
        await queue_job(db_session, test_tenant, product=test_product)

        entry = (await service(db_session, test_tenant).profitability_ranking())[0]

        assert entry.profit_per_machine_hour is None
        assert "price" in (entry.reason or "")

    async def test_it_leaves_the_jobs_alone(self, db_session, test_tenant, world) -> None:
        # A ranking is a read. Writing a rank onto the job would turn a view
        # into a decision nobody made.
        job = await queue_job(db_session, test_tenant, product=world["products"]["slow"])
        before = (job.priority, job.status)

        await service(db_session, test_tenant).profitability_ranking()

        assert (job.priority, job.status) == before

    async def test_only_pending_jobs_are_ranked_by_default(
        self, db_session, test_tenant, world
    ) -> None:
        # A finished job is not a choice about what to print next.
        done = await queue_job(db_session, test_tenant, product=world["products"]["quick"])
        done.status = JobStatus.COMPLETED
        db_session.add(done)
        await db_session.commit()
        pending = await queue_job(db_session, test_tenant, product=world["products"]["slow"])

        ranking = await service(db_session, test_tenant).profitability_ranking()

        assert [entry.job.id for entry in ranking] == [pending.id]

    async def test_an_empty_queue_ranks_nothing(self, db_session, test_tenant, world) -> None:
        assert await service(db_session, test_tenant).profitability_ranking() == []

    async def test_another_tenants_jobs_are_not_ranked(
        self, db_session, test_tenant, world
    ) -> None:
        from app.models.tenant import Tenant

        other = Tenant(
            id=uuid4(),
            name="Other",
            slug=f"other-{uuid4().hex[:8]}",
            settings={},
        )
        db_session.add(other)
        await db_session.commit()
        db_session.add(
            PrintJob(
                id=uuid4(),
                tenant_id=other.id,
                quantity=1,
                priority=JobPriority.URGENT,
                status=JobStatus.PENDING,
            )
        )
        await db_session.commit()
        mine = await queue_job(db_session, test_tenant, product=world["products"]["quick"])

        ranking = await service(db_session, test_tenant).profitability_ranking()

        assert [entry.job.id for entry in ranking] == [mine.id]
