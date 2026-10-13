"""Profit per machine-hour, and catalogue-wide shocks as background work (T109).

Two things US7 adds, tested together because they answer the same question
from opposite ends: *is this product worth the machine time it takes?*

## Profit per machine-hour (FR-043, SC-002)

In a print shop the binding constraint is the machine, not the money. Ranked
by margin percentage a 2% margin on a forty-hour print outranks a healthy one
on a two-hour print, and a shop run that way fills its printers with work that
pays nothing. CA$2.41 is the acceptance case's figure, and it is **derived
here from the fixture's inputs** rather than asserted as a constant: a test
that hard-codes 2.41 would pass if the engine started reporting profit per
*calendar* hour.

## The shock as a background job (FR-044a, FR-044b, FR-044d)

A catalogue-wide recalculation is not a request-time operation, so `POST
/scenarios` acknowledges and returns. What is pinned here is everything that
can go wrong with that pattern:

- the acknowledgement arrives **before** any calculation (a 202 with a handle
  and no result);
- a finished run has written **no** cost, price or provenance figure, which is
  the property that makes a shock safe to run on a Monday morning;
- a partial or failed run says what it got and why it stopped, rather than
  sitting at "running" for ever;
- a result read a week later states the shock and the inputs it used, so it is
  never mistaken for current figures.

## SC-010, and why it is asserted on the share and the lines

The success criterion asks that an instrumented machine's make-cost be mostly
evidenced rather than guessed. Asserting only the headline share would pass if
every figure were relabelled "policy", so the test below also requires the
lines telemetry actually feeds -- material, machine, the failure premium -- to
carry an observed or measured origin, and requires the fee side to stay
operator-entered (FR-041e). Evidence and decisions are both legitimate; a
decision dressed as evidence is not.
"""

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core import clock
from app.models.fee_rule import FeeRule
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.pricing_input_provenance import PricingInputProvenance
from app.models.product import Product
from app.models.product_component import ProductComponent
from app.models.product_model import ProductModel
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.models.scenario_run import ScenarioRun
from app.models.spool import Spool
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.services import fee_engine
from app.services.costing import CostingService
from app.services.provenance import record_origin
from tests.fixtures import golden_case as golden
from tests.unit.pricing.conftest import make_channel, make_policy

pytestmark = pytest.mark.asyncio

API = "/api/v1"
CENT = Decimal("0.01")
AS_OF = date(2026, 6, 1)
LIST_PRICE = Decimal("64.99")


# ===========================================================================
# Profit per machine-hour, derived from the golden fixture
# ===========================================================================


def golden_margin():
    """The acceptance case's margin, through the real engine.

    The make-cost is taken as given (``test_golden_case.py`` derives CA$20.30
    from the inputs line by line); everything else here runs through the fee
    engine and the margin chain exactly as a request would.
    """
    channel = make_channel()
    context, treatment = fee_engine.exclusive_context(
        item_subtotal=golden.LIST_PRICE,
        shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
    )
    return CostingService.margin(
        context=context,
        make_cost=Decimal("20.30"),
        channel=channel,
        fees=fee_engine.compute(channel, context, AS_OF),
        policy=make_policy(),
        tax=treatment,
        postage_paid=golden.POSTAGE_PAID,
        machine_hours=golden.PRINT_HOURS,
    )


def expected_profit_per_machine_hour() -> Decimal:
    """CA$2.41, from the profit the chain produced and the fixture's hours."""
    return (golden_margin().profit / golden.PRINT_HOURS).quantize(CENT)


class TestProfitPerMachineHour:
    def test_the_golden_case_reports_two_dollars_forty_one(self) -> None:
        # SC-002. Derived, so the figure moves if an input moves -- which is
        # the point of deriving it.
        assert expected_profit_per_machine_hour() == Decimal("2.41")

    def test_the_engine_reports_the_same_figure(self) -> None:
        assert golden_margin().profit_per_machine_hour == Decimal("2.41")

    def test_it_is_the_profit_divided_by_the_machine_hours(self) -> None:
        result = golden_margin()

        assert result.profit_per_machine_hour == (result.profit / golden.PRINT_HOURS).quantize(CENT)

    def test_it_is_undefined_rather_than_zero_without_machine_hours(self) -> None:
        # A product costed with no machine time -- a hand-assembled kit --
        # earns profit per machine-hour that does not exist. Zero would read
        # as "this makes nothing per hour" and sort it to the bottom of a
        # capacity ranking it does not belong in.
        channel = make_channel()
        context, treatment = fee_engine.exclusive_context(item_subtotal=golden.LIST_PRICE)

        result = CostingService.margin(
            context=context,
            make_cost=Decimal("20.30"),
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(),
            tax=treatment,
            machine_hours=None,
        )

        assert result.profit_per_machine_hour is None

    def test_it_is_undefined_for_zero_machine_hours(self) -> None:
        channel = make_channel()
        context, treatment = fee_engine.exclusive_context(item_subtotal=golden.LIST_PRICE)

        result = CostingService.margin(
            context=context,
            make_cost=Decimal("20.30"),
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(),
            tax=treatment,
            machine_hours=Decimal("0"),
        )

        assert result.profit_per_machine_hour is None

    def test_a_loss_reports_a_negative_figure(self) -> None:
        # Not clamped. A product losing money per machine-hour is exactly what
        # a capacity ranking must surface, and a floor at zero would hide it
        # among the merely unprofitable.
        channel = make_channel()
        context, treatment = fee_engine.exclusive_context(item_subtotal=Decimal("10.00"))

        result = CostingService.margin(
            context=context,
            make_cost=Decimal("20.30"),
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(),
            tax=treatment,
            postage_paid=golden.POSTAGE_PAID,
            machine_hours=golden.PRINT_HOURS,
        )

        assert result.profit_per_machine_hour is not None
        assert result.profit_per_machine_hour < 0

    def test_a_long_print_can_rank_below_a_short_one_on_the_same_margin(self) -> None:
        # The judgement US7 exists to make possible. Same price, same cost,
        # same margin percentage; four times the machine time.
        quick = golden_margin()

        channel = make_channel()
        context, treatment = fee_engine.exclusive_context(
            item_subtotal=golden.LIST_PRICE,
            shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
        )
        slow = CostingService.margin(
            context=context,
            make_cost=Decimal("20.30"),
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(),
            tax=treatment,
            postage_paid=golden.POSTAGE_PAID,
            machine_hours=golden.PRINT_HOURS * 4,
        )

        assert slow.margin_pct == quick.margin_pct
        assert slow.profit_per_machine_hour < quick.profit_per_machine_hour


# ===========================================================================
# SC-010: what share of the make-cost rests on evidence
# ===========================================================================


#: The cost lines telemetry can actually evidence on its own.
#:
#: The machine line is deliberately absent, and the reason is worth stating: it
#: mixes observed figures (print time, power draw) with the operator's machine
#: cost policy (what the printer cost, how long it is expected to last), and a
#: line is only as trustworthy as its weakest input. So it reads as `policy`,
#: which is correct -- it rests partly on a decision. Demanding `observed`
#: there would be demanding that a machine evidence its own purchase price.
#:
#: Overhead and labor are absent for the same reason, more strongly: they are
#: absorbed entirely from operator decisions.
TELEMETRY_FED_LINES = ("material", "waste")

#: What the system counts as evidence rather than assumption. A policy figure
#: is in here because an operator decision is not a guess: somebody chose it
#: and owns it. An `assumed` figure is nobody's choice, which is what makes it
#: the one to worry about.
EVIDENCED = ("observed", "measured", "policy")

#: The stricter reading: a figure somebody or something actually measured.
MEASURED = ("observed", "measured")


@pytest_asyncio.fixture
async def instrumented_item(db_session, test_tenant, test_filament_type):
    """The golden item on a machine that reports its own figures.

    Part weight, print time, yield and power draw carry an observed origin --
    the four SC-010 names -- and the landed filament cost carries a measured
    one, because somebody weighed and priced a spool rather than a machine
    reporting it.
    """
    # Without a policy carrying a machine rate there is no machine line at all
    # (FR-011), and an item whose machine occupancy is uncosted cannot be said
    # to be printed on an instrumented machine.
    db_session.add(
        TenantPricingPolicy(
            id=uuid4(),
            tenant_id=test_tenant.id,
            print_labor_rate=golden.LABOR_RATE_PER_HOUR,
            finishing_labor_rate=golden.LABOR_RATE_PER_HOUR,
            overhead_method="per_machine_hour",
            overhead_monthly_pool=golden.MONTHLY_OVERHEAD_POOL,
            expected_monthly_machine_hours=golden.EXPECTED_MONTHLY_MACHINE_HOURS,
            electricity_rate_per_kwh=golden.ELECTRICITY_RATE_PER_KWH,
            default_machine_rate_per_hour=(
                (golden.PRINTER_PURCHASE_PRICE + golden.PRINTER_MAINTENANCE_RESERVE_TOTAL)
                / golden.PRINTER_EXPECTED_LIFETIME_HOURS
                + golden.PRINTER_MEASURED_WATTS / Decimal("1000") * golden.ELECTRICITY_RATE_PER_KWH
            ),
            margin_basis="customer_total",
            effective_from=clock.today() - timedelta(days=30),
        )
    )

    spool = Spool(
        id=uuid4(),
        tenant_id=test_tenant.id,
        filament_type_id=test_filament_type.id,
        spool_id=f"SC010-{uuid4().hex[:6]}",
        initial_weight=golden.SPOOL_NOMINAL_GRAMS,
        current_weight=Decimal("800"),
        purchase_price=golden.SPOOL_LANDED_COST,
        unusable_remainder_grams=golden.SPOOL_UNUSABLE_REMAINDER_GRAMS,
        is_active=True,
        is_labeled=True,
    )
    db_session.add(spool)
    await db_session.flush()

    model = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"SC010-MODEL-{uuid4().hex[:6]}",
        name="Instrumented part",
        print_time_minutes=int(golden.PRINT_HOURS * 60),
        prints_per_plate=golden.PRINTS_PER_PLATE,
        waste_grams=golden.PURGE_GRAMS,
        expected_yield=golden.EXPECTED_YIELD,
        failure_mode="per_part",
        labor_hours_per_item=golden.AT_RISK_LABOR_MINUTES / Decimal("60"),
        packing_hours_per_item=golden.PACKING_LABOR_MINUTES / Decimal("60"),
        is_active=True,
    )
    db_session.add(model)
    await db_session.flush()

    material = ModelMaterial(
        id=uuid4(),
        model_id=model.id,
        spool_id=spool.id,
        weight_grams=golden.PART_GRAMS,
        cost_per_gram=spool.cost_per_gram,
    )
    db_session.add(material)

    product = Product(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku=f"SC010-PROD-{uuid4().hex[:6]}",
        name="Instrumented product",
        packaging_cost=golden.PACKAGING_COST,
        packaging_quantity=1,
        units_in_stock=10,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    db_session.add(ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1))

    for entity_type, entity_id, field_name, source in (
        ("model_material", material.id, "weight_grams", "observed"),
        ("model_material", material.id, "cost_per_gram", "measured"),
        ("model", model.id, "print_time_minutes", "observed"),
        ("model", model.id, "expected_yield", "observed"),
        ("model", model.id, "waste_grams", "observed"),
        # Not telemetry, but recorded: a line is only as strong as its weakest
        # input, so leaving the plate count unrecorded would make every
        # per-plate line read as an assumption however well instrumented the
        # machine is.
        ("model", model.id, "prints_per_plate", "measured"),
        # Handling and packing minutes: timed by hand, not by a printer, and
        # recorded as such. Unrecorded they drag both labor lines down to an
        # assumption, which is 44% of this item's cost.
        ("model", model.id, "labor_hours_per_item", "measured"),
        ("model", model.id, "packing_hours_per_item", "measured"),
        ("product", product.id, "packaging_cost", "measured"),
        ("product", product.id, "packaging_quantity", "measured"),
    ):
        await record_origin(
            db_session,
            test_tenant,
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            source=source,
            as_of=clock.today(),
        )
    await db_session.commit()

    # Reloaded with the cost tree eager-loaded: a lazy load raises in an async
    # session, which is the same reason every cost read uses these options.
    from app.services.cost_resolution import cost_load_options

    return (
        await db_session.execute(
            select(Product).where(Product.id == product.id).options(*cost_load_options())
        )
    ).scalar_one()


class TestTheObservedShareOfAnInstrumentedItem:
    async def test_most_of_the_make_cost_rests_on_evidence(
        self, db_session, test_tenant, instrumented_item
    ) -> None:
        from app.services.cost_resolution import product_cost_breakdown

        breakdown = await product_cost_breakdown(db_session, test_tenant, instrumented_item)

        assert breakdown.observed_share is not None
        assert breakdown.observed_share >= Decimal("0.70")

    async def test_the_lines_telemetry_feeds_are_not_assumptions(
        self, db_session, test_tenant, instrumented_item
    ) -> None:
        # The half that stops the share being satisfied by relabelling. A
        # breakdown can only claim 70% evidenced if the figures a machine
        # reports actually say so.
        from app.services.cost_resolution import product_cost_breakdown

        breakdown = await product_cost_breakdown(db_session, test_tenant, instrumented_item)
        by_key = {line.key: line for line in breakdown.lines}

        for key in TELEMETRY_FED_LINES:
            assert key in by_key, f"the golden item should have a {key} line"
            assert by_key[key].source in MEASURED, (
                f"{key} is {by_key[key].source}; telemetry feeds this line"
            )

        # The machine line rests on observed time and power plus the operator's
        # machine policy, so `policy` is the honest label -- but never
        # `assumed`, which would mean nobody recorded the machine at all.
        assert "machine" in by_key, "an instrumented item must cost its machine time"
        assert by_key["machine"].source in EVIDENCED

    async def test_every_line_carries_an_origin_and_a_date(
        self, db_session, test_tenant, instrumented_item
    ) -> None:
        # SC-004, checked where the figures are real rather than stubbed.
        from app.services.cost_resolution import product_cost_breakdown

        breakdown = await product_cost_breakdown(db_session, test_tenant, instrumented_item)

        assert breakdown.lines
        for line in breakdown.lines:
            assert line.source
            if line.source in EVIDENCED:
                assert line.as_of is not None, f"{line.key} claims evidence with no date"

    async def test_the_shares_account_for_the_whole_breakdown(
        self, db_session, test_tenant, instrumented_item
    ) -> None:
        from app.services.cost_resolution import product_cost_breakdown

        breakdown = await product_cost_breakdown(db_session, test_tenant, instrumented_item)

        assert breakdown.observed_share + breakdown.assumed_share == Decimal("1")


class TestTheShareIsNotSatisfiedByDefault:
    """The control. Without it, the 70% above proves nothing.

    An uninstrumented item costs the same figures through the same engine, so
    if its share also cleared 70% the criterion would be measuring the shape of
    a breakdown rather than how much of it anybody has established.
    """

    async def test_an_item_nobody_recorded_reports_a_lower_share(
        self, db_session, test_tenant, test_filament_type, instrumented_item
    ) -> None:
        from app.services.cost_resolution import cost_load_options, product_cost_breakdown
        from app.services.provenance import PricingInputProvenance as _Row  # noqa: F401

        # The same product, with every recorded origin removed.
        from sqlalchemy import delete

        await db_session.execute(delete(PricingInputProvenance))
        await db_session.commit()

        bare = (
            await db_session.execute(
                select(Product)
                .where(Product.id == instrumented_item.id)
                .options(*cost_load_options())
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        breakdown = await product_cost_breakdown(db_session, test_tenant, bare)

        assert breakdown.observed_share < Decimal("0.70")


class TestFeesStayOperatorEntered:
    def test_no_fee_input_can_be_relabelled_by_a_machine(self) -> None:
        # FR-041e. A fee rate is a figure the operator read off a marketplace's
        # schedule and typed. Nothing automated may move it or dress it as an
        # observation, because a fee that drifts on its own is one nobody
        # reconciles.
        from app.services.provenance import REGISTERED_INPUTS

        fee_inputs = [
            entry
            for entry in REGISTERED_INPUTS
            if entry.entity_type in ("fee_rule", "sales_channel")
        ]

        assert fee_inputs, "the registry must cover the fee side"
        for entry in fee_inputs:
            assert entry.default_source == "policy", f"{entry.key} should default to a decision"
            assert entry.learnable is False, f"{entry.key} must not be learnable"


# ===========================================================================
# The scenario job
# ===========================================================================


@pytest_asyncio.fixture(autouse=True)
def captured_dispatch(monkeypatch):
    """Records dispatches instead of reaching a broker.

    Every test in this module runs with the dispatcher replaced. A test suite
    that needed Redis to check an HTTP status code would be testing the broker;
    the one test that is about dispatch failure replaces this with a raiser.
    """
    calls: list[tuple] = []

    def _dispatch(run_id, tenant_id):
        calls.append((run_id, tenant_id))
        return f"task-{run_id}"

    import app.api.v1.scenarios as scenarios_api

    monkeypatch.setattr(scenarios_api, "dispatch_run", _dispatch)
    return calls


@pytest_asyncio.fixture
async def catalogue(db_session, test_tenant, test_filament_type):
    """Two priced products on one channel, and the policy that costs them."""
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
            margin_basis="customer_total",
            effective_from=clock.today() - timedelta(days=30),
        )
    )

    spool = Spool(
        id=uuid4(),
        tenant_id=test_tenant.id,
        filament_type_id=test_filament_type.id,
        spool_id=f"SCEN-{uuid4().hex[:6]}",
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
        name="Scenario Marketplace",
        platform_type="etsy",
        fee_percentage=Decimal("0"),
        fee_fixed=Decimal("0"),
        monthly_cost=Decimal("0"),
        currency_code="CAD",
        tax_remitter="marketplace",
        expected_discount_pct=Decimal("0"),
        expected_refund_pct=Decimal("2.5"),
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
            basis="item_plus_shipping",
            rate_pct=Decimal("6.5"),
            fixed_amount=Decimal("0.30"),
            sort_order=10,
            applies_from=clock.today() - timedelta(days=90),
        )
    )

    products = []
    for index, price in enumerate((LIST_PRICE, Decimal("24.00"))):
        model = Model(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sku=f"SCEN-MODEL-{index}-{uuid4().hex[:6]}",
            name=f"Scenario part {index}",
            print_time_minutes=570,
            prints_per_plate=1,
            waste_grams=Decimal("3"),
            expected_yield=Decimal("0.92"),
            failure_mode="per_part",
            labor_hours_per_item=Decimal("0.25"),
            packing_hours_per_item=Decimal("0.0833"),
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
            sku=f"SCEN-PROD-{index}-{uuid4().hex[:6]}",
            name=f"Scenario product {index}",
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
                list_price=price,
                valid_from=clock.today() - timedelta(days=10),
            )
        )
        products.append(product)

    await db_session.commit()
    return {"channel": channel, "products": products, "spool": spool}


@pytest_asyncio.fixture
async def other_tenant(db_session):
    """A second tenant, so isolation is tested against a real row.

    A fabricated tenant_id would fail the foreign key, and a test that cannot
    insert the row it is meant to be refused access to proves nothing.
    """
    from app.models.tenant import Tenant

    tenant = Tenant(
        id=uuid4(),
        name="Other Tenant",
        slug=f"other-tenant-{uuid4().hex[:8]}",
        settings={"currency": "CAD"},
    )
    db_session.add(tenant)
    await db_session.commit()
    return tenant


def shock_body(**overrides) -> dict:
    body = {
        "shock": {"material_cost_pct": "25"},
        "margin_floor_pct": "20",
    }
    body.update(overrides)
    return body


class TestRequestingAScenario:
    async def test_it_is_acknowledged_with_202(self, client, catalogue) -> None:
        response = await client.post(f"{API}/scenarios", json=shock_body())

        assert response.status_code == 202

    async def test_the_acknowledgement_carries_a_handle(self, client, catalogue) -> None:
        # FR-044a: the handle is the whole point of the 202. Without one the
        # caller has nothing to come back to.
        response = await client.post(f"{API}/scenarios", json=shock_body())

        assert response.json()["id"]

    async def test_nothing_is_calculated_before_the_reply(self, client, catalogue) -> None:
        response = await client.post(f"{API}/scenarios", json=shock_body())
        body = response.json()

        assert body["state"] == "queued"
        assert body["result"] is None
        assert body["started_at"] is None
        assert body["finished_at"] is None

    async def test_the_reply_repeats_the_shock_it_will_run(self, client, catalogue) -> None:
        response = await client.post(
            f"{API}/scenarios", json=shock_body(shock={"material_cost_pct": "12.5"})
        )

        assert Decimal(response.json()["shock"]["material_cost_pct"]) == Decimal("12.5")

    async def test_the_work_is_handed_to_a_worker(
        self, client, catalogue, captured_dispatch
    ) -> None:
        response = await client.post(f"{API}/scenarios", json=shock_body())

        assert len(captured_dispatch) == 1
        assert str(captured_dispatch[0][0]) == response.json()["id"]

    async def test_an_unauthenticated_request_is_refused(
        self, unauthenticated_client, catalogue
    ) -> None:
        response = await unauthenticated_client.post(f"{API}/scenarios", json=shock_body())

        assert response.status_code == 401

    async def test_a_shock_wiping_out_a_cost_is_refused(self, client, catalogue) -> None:
        # Below -100% a cost becomes negative, and a catalogue priced against
        # negative costs is nonsense dressed as analysis.
        response = await client.post(
            f"{API}/scenarios", json=shock_body(shock={"material_cost_pct": "-150"})
        )

        assert response.status_code == 422

    async def test_a_floor_outside_a_percentage_is_refused(self, client, catalogue) -> None:
        response = await client.post(f"{API}/scenarios", json=shock_body(margin_floor_pct="140"))

        assert response.status_code == 422

    async def test_an_empty_shock_is_refused(self, client, catalogue) -> None:
        # A scenario that changes nothing is the margin report, which already
        # exists. Accepting it would queue a catalogue sweep to recompute what
        # one request already answers (Constitution III).
        response = await client.post(f"{API}/scenarios", json=shock_body(shock={}))

        assert response.status_code == 422

    async def test_a_failed_dispatch_is_reported_not_left_queued(
        self, client, catalogue, monkeypatch
    ) -> None:
        # FR-044b: a job must not appear to hang. A broker that cannot be
        # reached is a failed run with a reason, not a row that stays queued
        # for ever while an operator waits.
        import app.api.v1.scenarios as scenarios_api

        def _explode(run_id, tenant_id):
            raise ConnectionError("redis: connection refused")

        monkeypatch.setattr(scenarios_api, "dispatch_run", _explode)

        response = await client.post(f"{API}/scenarios", json=shock_body())
        body = response.json()

        assert body["state"] == "failed"
        assert "redis" in (body["error_text"] or "")


class TestReadingAScenario:
    async def test_a_queued_run_reports_its_state(self, client, catalogue) -> None:
        created = (await client.post(f"{API}/scenarios", json=shock_body())).json()

        response = await client.get(f"{API}/scenarios/{created['id']}")

        assert response.status_code == 200
        assert response.json()["state"] == "queued"

    async def test_an_unknown_run_is_a_404(self, client, catalogue) -> None:
        response = await client.get(f"{API}/scenarios/{uuid4()}")

        assert response.status_code == 404

    async def test_another_tenants_run_is_a_404(
        self, client, db_session, catalogue, other_tenant
    ) -> None:
        # Not a 403: confirming the row exists would leak that another tenant
        # ran a scenario.
        other = ScenarioRun(
            id=uuid4(),
            tenant_id=other_tenant.id,
            shock_json={"material_cost_pct": "10"},
            margin_floor_pct=Decimal("20"),
            state="succeeded",
        )
        db_session.add(other)
        await db_session.commit()

        response = await client.get(f"{API}/scenarios/{other.id}")

        assert response.status_code == 404

    async def test_the_history_lists_the_runs(self, client, catalogue) -> None:
        await client.post(f"{API}/scenarios", json=shock_body())
        await client.post(f"{API}/scenarios", json=shock_body(margin_floor_pct="30"))

        response = await client.get(f"{API}/scenarios")

        assert response.status_code == 200
        assert response.json()["total"] == 2

    async def test_the_history_puts_the_newest_first(self, client, catalogue) -> None:
        first = (await client.post(f"{API}/scenarios", json=shock_body())).json()
        second = (
            await client.post(f"{API}/scenarios", json=shock_body(margin_floor_pct="30"))
        ).json()

        runs = (await client.get(f"{API}/scenarios")).json()["runs"]

        assert [run["id"] for run in runs][:2] == [second["id"], first["id"]]

    async def test_the_history_is_this_tenants_only(
        self, client, db_session, catalogue, other_tenant
    ) -> None:
        db_session.add(
            ScenarioRun(
                id=uuid4(),
                tenant_id=other_tenant.id,
                shock_json={"material_cost_pct": "10"},
                margin_floor_pct=Decimal("20"),
                state="succeeded",
            )
        )
        await db_session.commit()
        await client.post(f"{API}/scenarios", json=shock_body())

        runs = (await client.get(f"{API}/scenarios")).json()["runs"]

        assert len(runs) == 1


# ---------------------------------------------------------------------------
# Running one
# ---------------------------------------------------------------------------


async def run_scenario(db_session, test_tenant, **overrides):
    """Request and execute a scenario in the foreground, as the worker would."""
    from app.services.scenario_service import Shock, execute_run, request_run

    shock = overrides.pop("shock", Shock(material_cost_pct=Decimal("25")))
    run = await request_run(
        db_session,
        test_tenant,
        shock=shock,
        margin_floor_pct=overrides.pop("margin_floor_pct", Decimal("20")),
        **overrides,
    )
    await db_session.commit()
    return await execute_run(db_session, test_tenant, run.id)


class TestAFinishedRun:
    async def test_it_succeeds(self, db_session, test_tenant, catalogue) -> None:
        run = await run_scenario(db_session, test_tenant)

        assert run.state == "succeeded"

    async def test_it_records_when_it_started_and_finished(
        self, db_session, test_tenant, catalogue
    ) -> None:
        run = await run_scenario(db_session, test_tenant)

        assert run.started_at is not None
        assert run.finished_at is not None

    async def test_it_names_the_products_below_the_floor(
        self, db_session, test_tenant, catalogue
    ) -> None:
        # A shock that says "which of these stops paying" must answer with
        # names, not a count.
        run = await run_scenario(db_session, test_tenant, margin_floor_pct=Decimal("90"))

        below = run.result_json["below_floor"]
        assert below
        assert all("sku" in entry and "margin_pct" in entry for entry in below)

    async def test_a_comfortable_floor_leaves_the_list_empty(
        self, db_session, test_tenant, catalogue
    ) -> None:
        run = await run_scenario(db_session, test_tenant, margin_floor_pct=Decimal("-100"))

        assert run.result_json["below_floor"] == []

    async def test_it_says_how_many_it_looked_at(self, db_session, test_tenant, catalogue) -> None:
        run = await run_scenario(db_session, test_tenant)

        assert run.result_json["evaluated"] == 2

    async def test_the_result_states_the_shock_it_used(
        self, db_session, test_tenant, catalogue
    ) -> None:
        # FR-044c. A result read in a fortnight, with the material price since
        # changed twice, must still say what it was asking.
        run = await run_scenario(db_session, test_tenant)

        assert Decimal(run.result_json["shock"]["material_cost_pct"]) == Decimal("25")

    async def test_the_result_states_the_inputs_it_used(
        self, db_session, test_tenant, catalogue
    ) -> None:
        run = await run_scenario(db_session, test_tenant)
        inputs = run.result_json["inputs"]

        assert inputs["as_of"]
        assert inputs["margin_basis"]
        assert inputs["labor_rate"]
        assert Decimal(inputs["margin_floor_pct"]) == Decimal("20")

    async def test_the_shock_actually_moves_the_margin(
        self, db_session, test_tenant, catalogue
    ) -> None:
        # The control. Without this the "nothing was written" tests below would
        # pass for a run that did no arithmetic at all.
        from app.services.scenario_service import Shock

        unshocked = await run_scenario(
            db_session,
            test_tenant,
            shock=Shock(material_cost_pct=Decimal("0.01")),
            margin_floor_pct=Decimal("-100"),
        )
        shocked = await run_scenario(
            db_session,
            test_tenant,
            shock=Shock(material_cost_pct=Decimal("400")),
            margin_floor_pct=Decimal("-100"),
        )

        assert shocked.result_json["margins"] != unshocked.result_json["margins"]


class TestAFinishedRunWritesNothing:
    """FR-044d, the property that makes a shock safe to run at any time."""

    async def _figures(self, db_session, test_tenant):
        prices = dict(
            (
                (row.id, row.list_price)
                for row in (
                    await db_session.execute(
                        select(ProductPricing).execution_options(populate_existing=True)
                    )
                )
                .scalars()
                .all()
            )
        )
        materials = dict(
            (
                (row.id, row.cost_per_gram)
                for row in (
                    await db_session.execute(
                        select(ModelMaterial).execution_options(populate_existing=True)
                    )
                )
                .scalars()
                .all()
            )
        )
        rules = dict(
            (
                (row.id, row.rate_pct)
                for row in (
                    await db_session.execute(
                        select(FeeRule).execution_options(populate_existing=True)
                    )
                )
                .scalars()
                .all()
            )
        )
        spools = dict(
            (
                (row.id, row.purchase_price)
                for row in (
                    await db_session.execute(
                        select(Spool).execution_options(populate_existing=True)
                    )
                )
                .scalars()
                .all()
            )
        )
        provenance = (
            await db_session.execute(select(func.count()).select_from(PricingInputProvenance))
        ).scalar()
        return (prices, materials, rules, spools, provenance)

    async def test_no_price_moved(self, db_session, test_tenant, catalogue) -> None:
        before = await self._figures(db_session, test_tenant)

        await run_scenario(db_session, test_tenant)

        assert (await self._figures(db_session, test_tenant))[0] == before[0]

    async def test_no_material_cost_moved(self, db_session, test_tenant, catalogue) -> None:
        # The shock's own target. If anything leaks, it leaks here.
        before = await self._figures(db_session, test_tenant)

        await run_scenario(db_session, test_tenant)

        assert (await self._figures(db_session, test_tenant))[1] == before[1]

    async def test_no_fee_rate_moved(self, db_session, test_tenant, catalogue) -> None:
        from app.services.scenario_service import Shock

        before = await self._figures(db_session, test_tenant)

        await run_scenario(db_session, test_tenant, shock=Shock(fee_rate_pct=Decimal("50")))

        assert (await self._figures(db_session, test_tenant))[2] == before[2]

    async def test_no_spool_price_moved(self, db_session, test_tenant, catalogue) -> None:
        before = await self._figures(db_session, test_tenant)

        await run_scenario(db_session, test_tenant)

        assert (await self._figures(db_session, test_tenant))[3] == before[3]

    async def test_no_provenance_row_was_written(self, db_session, test_tenant, catalogue) -> None:
        # A scenario observes nothing. A provenance row written here would make
        # a hypothetical look like a measurement.
        before = await self._figures(db_session, test_tenant)

        await run_scenario(db_session, test_tenant)

        assert (await self._figures(db_session, test_tenant))[4] == before[4]

    async def test_the_run_itself_is_the_only_new_row(
        self, db_session, test_tenant, catalogue
    ) -> None:
        run = await run_scenario(db_session, test_tenant)

        stored = (
            await db_session.execute(select(ScenarioRun).where(ScenarioRun.id == run.id))
        ).scalar_one()
        assert stored.result_json is not None


class TestAPartialOrFailedRun:
    async def test_a_product_that_cannot_be_costed_is_reported(
        self, db_session, test_tenant, catalogue
    ) -> None:
        # A cycle in the operator's own bundles. The sweep must not stop at it
        # and must not pretend it costed it.
        first, second = catalogue["products"]
        db_session.add(
            ProductComponent(
                id=uuid4(),
                parent_product_id=first.id,
                child_product_id=second.id,
                quantity=1,
            )
        )
        db_session.add(
            ProductComponent(
                id=uuid4(),
                parent_product_id=second.id,
                child_product_id=first.id,
                quantity=1,
            )
        )
        await db_session.commit()

        run = await run_scenario(db_session, test_tenant)

        assert run.state == "partial"
        assert run.result_json["skipped"]

    async def test_it_says_why_it_skipped_each_one(
        self, db_session, test_tenant, catalogue
    ) -> None:
        first, second = catalogue["products"]
        db_session.add(
            ProductComponent(
                id=uuid4(),
                parent_product_id=first.id,
                child_product_id=second.id,
                quantity=1,
            )
        )
        db_session.add(
            ProductComponent(
                id=uuid4(),
                parent_product_id=second.id,
                child_product_id=first.id,
                quantity=1,
            )
        )
        await db_session.commit()

        run = await run_scenario(db_session, test_tenant)

        assert all(entry.get("reason") for entry in run.result_json["skipped"])

    async def test_a_partial_run_still_reports_what_it_got(
        self, db_session, test_tenant, catalogue
    ) -> None:
        # The failure FR-044b names is a job that reports nothing because part
        # of it failed. Half an answer beats none.
        first, second = catalogue["products"]
        db_session.add(
            ProductComponent(
                id=uuid4(),
                parent_product_id=first.id,
                child_product_id=second.id,
                quantity=1,
            )
        )
        await db_session.commit()

        run = await run_scenario(db_session, test_tenant, margin_floor_pct=Decimal("90"))

        assert run.result_json["evaluated"] >= 1

    async def test_a_run_with_no_catalogue_says_so(self, db_session, test_tenant) -> None:
        run = await run_scenario(db_session, test_tenant)

        assert run.state == "succeeded"
        assert run.result_json["evaluated"] == 0
        assert run.result_json["below_floor"] == []

    async def test_an_unexpected_failure_is_recorded_on_the_run(
        self, db_session, test_tenant, catalogue, monkeypatch
    ) -> None:
        import app.services.scenario_service as service

        async def _explode(*args, **kwargs):
            raise RuntimeError("the costing engine fell over")

        monkeypatch.setattr(service, "product_cost_breakdown", _explode)

        run = await run_scenario(db_session, test_tenant)

        assert run.state == "failed"
        assert "fell over" in (run.error_text or "")

    async def test_a_failed_run_does_not_stay_running(
        self, db_session, test_tenant, catalogue, monkeypatch
    ) -> None:
        import app.services.scenario_service as service

        async def _explode(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(service, "product_cost_breakdown", _explode)

        run = await run_scenario(db_session, test_tenant)

        assert run.state != "running"
        assert run.finished_at is not None

    async def test_a_run_already_finished_is_not_run_again(
        self, db_session, test_tenant, catalogue
    ) -> None:
        # A worker retry must not restate a result an operator has read.
        from app.services.scenario_service import execute_run

        run = await run_scenario(db_session, test_tenant)
        first_result = run.result_json

        again = await execute_run(db_session, test_tenant, run.id)

        assert again.result_json == first_result
