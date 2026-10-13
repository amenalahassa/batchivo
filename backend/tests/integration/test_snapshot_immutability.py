"""Changing an input must not restate a settled order's margin (T090, FR-038).

This is the test the whole snapshot mechanism exists for. The failure it
prevents is silent: without it, a system recomputes a historical margin from
today's figures, so raising a labor rate on Monday quietly rewrites every
margin the business ever reported. An operator then cannot answer "did that
product line make money last year", because the answer changes every time
somebody edits a setting.

So: build a world, settle three orders in it, then change **a spool price, a
labor rate, an overhead setting and a fee rule** -- the four inputs FR-038
names -- and require that **zero** settled orders report a different margin.

## The control, and why it is not optional

A test that reads a frozen number and asserts it did not change would pass
even if the four edits had done nothing at all. So
:class:`TestTheInputChangesAreMaterial` takes an order with **no** snapshot,
subjects it to the same edits, and requires its margin to move. That is what
makes the rest of the file mean something: the inputs genuinely moved, and the
settled orders held still anyway.

## How a margin is "reported" here

There is no realised-margin service yet -- US7's T117a brings one. The reader
below is the one a report must implement: **prefer the snapshot, fall back to
live recomputation**. The fallback is the dangerous half, and keeping it in the
reader is what lets the control test exist at all. A reader that could only
read snapshots would make this file tautological.
"""

from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core import clock
from app.models.fee_rule import FeeRule
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.models.spool import Spool
from app.models.tenant_pricing_policy import TenantPricingPolicy
from app.services import fee_engine
from app.services.cost_resolution import product_cost_breakdown
from app.services.pricing_policy import resolve_cost_policy, write_policy
from app.services.sale_snapshot import write_sale_snapshot

ZERO = Decimal("0")
CENT = Decimal("0.01")
HUNDRED = Decimal("100")

#: The orders are settled in the past, so "today's" inputs are unambiguously
#: not the ones that were in force when they were placed.
SALE_DAY = clock.today() - timedelta(days=45)


# ---------------------------------------------------------------------------
# Reading a margin back
# ---------------------------------------------------------------------------


async def reported_margin(db, tenant, order: Order) -> Decimal:
    """The margin a report would show for ``order``, as a percentage.

    Snapshot first, live recomputation second. The second branch is what
    FR-038 forbids a settled order from reaching, and it is here so the control
    test can prove the inputs moved.

    Revenue is what was charged. Costs are the frozen make-cost and the frozen
    fees where they exist, and today's equivalents where they do not.
    """
    revenue = ZERO
    costs = ZERO

    for item in order.items:
        quantity = Decimal(str(item.quantity or 0))
        revenue += Decimal(str(item.total_price or ZERO))

        if item.make_cost_at_sale is not None:
            costs += Decimal(str(item.make_cost_at_sale)) * quantity
        elif item.product_id is not None:
            product = await _load_product(db, item.product_id)
            if product is not None:
                breakdown = await product_cost_breakdown(db, tenant, product)
                costs += breakdown.total_make_cost * quantity

        if item.fees_json:
            costs += sum(
                (Decimal(str(charge["amount"])) for charge in item.fees_json), ZERO
            )

    if not any(item.fees_json for item in order.items):
        costs += await _live_fees(db, tenant, order)

    if revenue <= ZERO:
        return ZERO
    return ((revenue - costs) / revenue * HUNDRED).quantize(CENT)


async def _live_fees(db, tenant, order: Order) -> Decimal:
    """Today's fee stack on ``order`` -- the unfrozen path."""
    if order.sales_channel_id is None:
        return ZERO

    channel = (
        await db.execute(
            select(SalesChannel)
            .options(selectinload(SalesChannel.fee_rules))
            .where(SalesChannel.id == order.sales_channel_id)
        )
    ).scalar_one_or_none()
    if channel is None:
        return ZERO

    context, _ = fee_engine.exclusive_context(
        item_subtotal=sum(
            (Decimal(str(item.total_price or ZERO)) for item in order.items), ZERO
        ),
        shipping_revenue=Decimal(str(order.shipping_cost or ZERO)),
        quantity=sum(int(item.quantity or 0) for item in order.items) or 1,
        sales_tax_collected=Decimal(str(order.sales_tax_collected or ZERO)),
    )
    stack = fee_engine.compute(
        channel, context, clock.today(), rules=list(channel.fee_rules)
    )
    return stack.total_exact


async def _load_product(db, product_id) -> Product | None:
    """Re-read from the database, not from the identity map.

    ``populate_existing`` is what makes the reload mean something: without it
    an edit flushed earlier in the test would be served from memory, and a
    read that never touched the database could not show whether a stored
    figure had moved. It also keeps the refresh inside an awaited ``execute``,
    where a lazy attribute load would raise ``MissingGreenlet``.
    """
    return (
        await db.execute(
            select(Product)
            .execution_options(populate_existing=True)
            .options(
                selectinload(Product.product_models)
                .selectinload(ProductModel.model)
                .selectinload(Model.materials),
                selectinload(Product.product_models)
                .selectinload(ProductModel.model)
                .selectinload(Model.components),
                selectinload(Product.child_products),
                selectinload(Product.packaging_consumable),
            )
            .where(Product.id == product_id)
        )
    ).scalar_one_or_none()


async def _reload_order(db, order_id) -> Order:
    """The order and its lines, re-read from the database (see _load_product)."""
    return (
        await db.execute(
            select(Order)
            .execution_options(populate_existing=True)
            .options(selectinload(Order.items))
            .where(Order.id == order_id)
        )
    ).scalar_one()


# ---------------------------------------------------------------------------
# The world
# ---------------------------------------------------------------------------


class SettledWorld:
    """Everything the four edits need to reach, plus the settled orders."""

    def __init__(self, **parts):
        self.__dict__.update(parts)


@pytest_asyncio.fixture
async def world(db_session, test_tenant, test_filament_type) -> SettledWorld:
    """Three settled orders, snapshotted, in a fully configured tenant."""
    policy = TenantPricingPolicy(
        id=uuid4(),
        tenant_id=test_tenant.id,
        print_labor_rate=Decimal("25.00"),
        finishing_labor_rate=Decimal("25.00"),
        overhead_method="per_machine_hour",
        overhead_monthly_pool=Decimal("180.00"),
        expected_monthly_machine_hours=Decimal("600"),
        electricity_rate_per_kwh=Decimal("0.13"),
        margin_basis="customer_total",
        effective_from=SALE_DAY - timedelta(days=30),
    )
    db_session.add(policy)

    spool = Spool(
        id=uuid4(),
        tenant_id=test_tenant.id,
        filament_type_id=test_filament_type.id,
        spool_id="IMMUTABLE-SPOOL-001",
        initial_weight=Decimal("1000"),
        current_weight=Decimal("800"),
        purchase_price=Decimal("31.00"),
        unusable_remainder_grams=Decimal("25"),
        is_active=True,
        is_labeled=True,
    )
    db_session.add(spool)
    await db_session.flush()

    # Seeded from the spool, which is how the real flow fills this column.
    cost_per_gram = spool.cost_per_gram
    assert cost_per_gram is not None, "the fixture spool must have a derivable cost"

    model = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku="IMMUTABLE-MODEL-001",
        name="Settled part",
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

    material = ModelMaterial(
        id=uuid4(),
        model_id=model.id,
        spool_id=spool.id,
        weight_grams=Decimal("142"),
        cost_per_gram=cost_per_gram,
    )
    db_session.add(material)

    product = Product(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku="IMMUTABLE-PROD-001",
        name="Settled product",
        packaging_cost=Decimal("0.92"),
        packaging_quantity=1,
        units_in_stock=50,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    db_session.add(
        ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1)
    )

    channel = SalesChannel(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Settled Marketplace",
        platform_type="etsy",
        fee_percentage=Decimal("0"),
        fee_fixed=Decimal("0"),
        monthly_cost=Decimal("0"),
        currency_code="CAD",
        expected_refund_pct=Decimal("1.5"),
        is_active=True,
    )
    db_session.add(channel)
    await db_session.flush()

    commission = FeeRule(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sales_channel_id=channel.id,
        name="Commission",
        basis="item_plus_shipping",
        rate_pct=Decimal("6.5"),
        fixed_amount=Decimal("0"),
        sort_order=10,
        applies_from=SALE_DAY - timedelta(days=90),
    )
    processing = FeeRule(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sales_channel_id=channel.id,
        name="Processing",
        basis="order_total",
        rate_pct=Decimal("3.0"),
        fixed_amount=Decimal("0.25"),
        sort_order=20,
        applies_from=SALE_DAY - timedelta(days=90),
    )
    db_session.add_all([commission, processing])

    db_session.add(
        ProductPricing(
            id=uuid4(),
            product_id=product.id,
            sales_channel_id=channel.id,
            list_price=Decimal("64.99"),
            valid_from=SALE_DAY - timedelta(days=60),
            min_quantity=1,
            is_active=True,
        )
    )
    await db_session.flush()

    orders: list[Order] = []
    for index, quantity in enumerate((1, 2, 3), start=1):
        unit_price = Decimal("64.99")
        order = Order(
            id=uuid4(),
            tenant_id=test_tenant.id,
            order_number=f"SETTLED-{index:03d}",
            sales_channel_id=channel.id,
            status=OrderStatus.DELIVERED,
            customer_email=f"buyer{index}@example.test",
            customer_name=f"Buyer {index}",
            shipping_address_line1="1 Settled Way",
            shipping_city="Victoria",
            shipping_postcode="V8W 1A1",
            shipping_country="Canada",
            shipping_method="Standard",
            shipping_cost=Decimal("0"),
            subtotal=unit_price * quantity,
            total=unit_price * quantity,
            currency="CAD",
            payment_provider="test",
            payment_status="completed",
        )
        order.items.append(
            OrderItem(
                id=uuid4(),
                tenant_id=test_tenant.id,
                product_id=product.id,
                product_sku=product.sku,
                product_name=product.name,
                quantity=quantity,
                unit_price=unit_price,
                total_price=unit_price * quantity,
            )
        )
        db_session.add(order)
        orders.append(order)

    await db_session.flush()
    for order in orders:
        result = await write_sale_snapshot(
            db_session, test_tenant, order, as_of=SALE_DAY
        )
        assert result.wrote_anything, "the fixture must actually freeze a snapshot"
    await db_session.commit()

    return SettledWorld(
        tenant=test_tenant,
        spool=spool,
        material=material,
        model=model,
        product=product,
        channel=channel,
        policy=policy,
        commission=commission,
        processing=processing,
        orders=orders,
        order_ids=[order.id for order in orders],
    )


# ---------------------------------------------------------------------------
# The four edits
# ---------------------------------------------------------------------------


async def raise_the_spool_price(db, world: SettledWorld) -> None:
    """A restock at a worse price, propagated to the material as the app does."""
    world.spool.purchase_price = Decimal("46.50")
    db.add(world.spool)
    await db.flush()
    world.material.cost_per_gram = world.spool.cost_per_gram
    db.add(world.material)
    await db.flush()


async def raise_the_labor_rate(db, world: SettledWorld) -> None:
    """Edited **in place**, on the row that was in force at the sale.

    Deliberately the most hostile version. ``write_policy`` opens a new
    effective row, which a dated read would step around on its own; rewriting
    the historical row removes that protection and leaves only the snapshot
    standing between an input change and a restated margin.
    """
    world.policy.print_labor_rate = Decimal("41.00")
    world.policy.finishing_labor_rate = Decimal("41.00")
    db.add(world.policy)
    await db.flush()


async def change_the_overhead_setting(db, world: SettledWorld) -> None:
    """A bigger pool absorbed over fewer hours -- overhead per hour triples."""
    world.policy.overhead_monthly_pool = Decimal("540.00")
    world.policy.expected_monthly_machine_hours = Decimal("200")
    db.add(world.policy)
    await db.flush()


async def change_a_fee_rule(db, world: SettledWorld) -> None:
    """A channel raising its commission, in place on the existing rule."""
    world.commission.rate_pct = Decimal("12.0")
    world.processing.fixed_amount = Decimal("0.60")
    db.add_all([world.commission, world.processing])
    await db.flush()


ALL_EDITS = (
    ("a spool price", raise_the_spool_price),
    ("a labor rate", raise_the_labor_rate),
    ("an overhead setting", change_the_overhead_setting),
    ("a fee rule", change_a_fee_rule),
)


# ---------------------------------------------------------------------------
# FR-038
# ---------------------------------------------------------------------------


class TestNoSettledOrderIsRestated:
    """Zero settled orders report a different margin. Zero, not "few"."""

    async def test_the_fixture_reports_a_plausible_margin_to_begin_with(
        self, db_session, world
    ) -> None:
        """A guard on the fixture, not on the feature.

        If the baseline were zero or negative, every assertion below would hold
        trivially and prove nothing.
        """
        for order_id in world.order_ids:
            order = await _reload_order(db_session, order_id)
            margin = await reported_margin(db_session, world.tenant, order)
            assert Decimal("10") < margin < Decimal("90"), (
                f"order {order.order_number} reported {margin}% before anything "
                f"changed, which means the fixture is not costing properly"
            )

    @pytest.mark.parametrize("label,edit", ALL_EDITS, ids=[name for name, _ in ALL_EDITS])
    async def test_changing_one_input_restates_nothing(
        self, db_session, world, label, edit
    ) -> None:
        before = {
            order_id: await reported_margin(
                db_session, world.tenant, await _reload_order(db_session, order_id)
            )
            for order_id in world.order_ids
        }

        await edit(db_session, world)
        await db_session.flush()

        restated = []
        for order_id in world.order_ids:
            order = await _reload_order(db_session, order_id)
            after = await reported_margin(db_session, world.tenant, order)
            if after != before[order_id]:
                restated.append((order.order_number, before[order_id], after))

        assert restated == [], (
            f"changing {label} restated {len(restated)} settled order(s): "
            + "; ".join(
                f"{number} moved from {was}% to {now}%" for number, was, now in restated
            )
        )

    async def test_changing_all_four_at_once_restates_nothing(
        self, db_session, world
    ) -> None:
        """FR-038 verbatim, with every input moving together."""
        before = {
            order_id: await reported_margin(
                db_session, world.tenant, await _reload_order(db_session, order_id)
            )
            for order_id in world.order_ids
        }

        for _label, edit in ALL_EDITS:
            await edit(db_session, world)
        await db_session.flush()

        after = {
            order_id: await reported_margin(
                db_session, world.tenant, await _reload_order(db_session, order_id)
            )
            for order_id in world.order_ids
        }

        differing = {
            order_id for order_id in before if before[order_id] != after[order_id]
        }
        assert differing == set(), (
            f"{len(differing)} of {len(before)} settled orders were restated after a "
            f"spool price, a labor rate, an overhead setting and a fee rule all moved"
        )


class TestTheInputChangesAreMaterial:
    """The control. Without this the file above proves nothing.

    An order with no snapshot is read by the same reader, through its live
    branch. Subjected to the same four edits its margin must move -- which is
    what establishes that the edits were real and that the settled orders held
    still by design rather than by accident.
    """

    @pytest_asyncio.fixture
    async def unsnapshotted_order(self, db_session, world) -> Order:
        order = Order(
            id=uuid4(),
            tenant_id=world.tenant.id,
            order_number="UNFROZEN-001",
            sales_channel_id=world.channel.id,
            status=OrderStatus.DELIVERED,
            customer_email="control@example.test",
            customer_name="Control",
            shipping_address_line1="1 Settled Way",
            shipping_city="Victoria",
            shipping_postcode="V8W 1A1",
            shipping_country="Canada",
            shipping_method="Standard",
            shipping_cost=Decimal("0"),
            subtotal=Decimal("64.99"),
            total=Decimal("64.99"),
            currency="CAD",
            payment_provider="test",
            payment_status="completed",
        )
        order.items.append(
            OrderItem(
                id=uuid4(),
                tenant_id=world.tenant.id,
                product_id=world.product.id,
                product_sku=world.product.sku,
                product_name=world.product.name,
                quantity=1,
                unit_price=Decimal("64.99"),
                total_price=Decimal("64.99"),
            )
        )
        db_session.add(order)
        await db_session.flush()
        return order

    async def test_it_really_has_no_snapshot(self, unsnapshotted_order) -> None:
        assert all(not item.has_snapshot for item in unsnapshotted_order.items)

    @pytest.mark.parametrize("label,edit", ALL_EDITS, ids=[name for name, _ in ALL_EDITS])
    async def test_each_edit_moves_an_unfrozen_margin(
        self, db_session, world, unsnapshotted_order, label, edit
    ) -> None:
        before = await reported_margin(
            db_session,
            world.tenant,
            await _reload_order(db_session, unsnapshotted_order.id),
        )

        await edit(db_session, world)
        await db_session.flush()

        after = await reported_margin(
            db_session,
            world.tenant,
            await _reload_order(db_session, unsnapshotted_order.id),
        )

        assert after != before, (
            f"changing {label} did not move an unfrozen margin ({before}%), so the "
            f"edit was not material and the immutability tests above prove nothing"
        )


class TestTheSnapshotItselfIsUntouched:
    """Not just the derived margin -- the stored figures do not move either."""

    async def _frozen_state(self, db_session, world) -> dict:
        state = {}
        for order_id in world.order_ids:
            order = await _reload_order(db_session, order_id)
            for item in order.items:
                state[item.id] = {
                    "make_cost_at_sale": item.make_cost_at_sale,
                    "list_price_at_sale": item.list_price_at_sale,
                    "fees_json": deepcopy(item.fees_json),
                    "fx_rate": item.fx_rate,
                    "margin_basis_at_sale": item.margin_basis_at_sale,
                    "pricing_rev": item.pricing_rev,
                    "cost_breakdown_json": deepcopy(item.cost_breakdown_json),
                }
        return state

    async def test_every_frozen_column_survives_all_four_edits(
        self, db_session, world
    ) -> None:
        before = await self._frozen_state(db_session, world)

        for _label, edit in ALL_EDITS:
            await edit(db_session, world)
        await db_session.flush()

        after = await self._frozen_state(db_session, world)

        assert after == before

    async def test_resnapshotting_after_the_edits_changes_nothing(
        self, db_session, world
    ) -> None:
        """"Written once" under the worst case: a second call after a change.

        All three sale paths may call ``write_sale_snapshot`` more than once,
        so a second call that overwrote would restate every order it touched.
        """
        before = await self._frozen_state(db_session, world)

        for _label, edit in ALL_EDITS:
            await edit(db_session, world)
        await db_session.flush()

        for order_id in world.order_ids:
            order = await _reload_order(db_session, order_id)
            result = await write_sale_snapshot(db_session, world.tenant, order)
            assert result.lines_written == 0
            assert result.lines_skipped == len(order.items)
        await db_session.flush()

        assert await self._frozen_state(db_session, world) == before

    async def test_the_frozen_breakdown_holds_the_old_cost_not_the_new_one(
        self, db_session, world
    ) -> None:
        """Stated positively, so a failure says which figure leaked.

        After the spool price rises by half, a live cost is materially higher.
        The frozen one must still be the lower, earlier figure.
        """
        order = await _reload_order(db_session, world.order_ids[0])
        frozen = Decimal(str(order.items[0].make_cost_at_sale))

        await raise_the_spool_price(db_session, world)
        await db_session.flush()

        product = await _load_product(db_session, world.product.id)
        live = (
            await product_cost_breakdown(db_session, world.tenant, product)
        ).total_make_cost

        assert live > frozen, "the spool price rise must move a live cost"

        order = await _reload_order(db_session, world.order_ids[0])
        assert Decimal(str(order.items[0].make_cost_at_sale)) == frozen

    async def test_the_pricing_revision_is_recorded(self, db_session, world) -> None:
        """So a historical margin can be attributed to the arithmetic behind it.

        Without it, a figure frozen by a later version of the engine is
        indistinguishable from one frozen by this one, and a corrected
        calculation becomes impossible to tell from a corrected input.
        """
        order = await _reload_order(db_session, world.order_ids[0])

        for item in order.items:
            assert item.pricing_rev is not None
            assert item.margin_basis_at_sale == "customer_total"


class TestTheFrozenFeesReconcile:
    """An allocated fee is only trustworthy if the shares add up.

    Order-level fees are charged once and snapshotted per line. If the shares
    did not sum to the charge, every settled order's margin would be wrong by
    a rounding remainder -- stable, so this file would still pass, and wrong.
    """

    async def test_the_allocated_shares_sum_to_the_charge(
        self, db_session, world
    ) -> None:
        for order_id in world.order_ids:
            order = await _reload_order(db_session, order_id)
            charged: dict[str, Decimal] = {}
            allocated: dict[str, Decimal] = {}

            for item in order.items:
                for charge in item.fees_json or []:
                    charged[charge["name"]] = Decimal(str(charge["order_amount"]))
                    allocated[charge["name"]] = allocated.get(
                        charge["name"], ZERO
                    ) + Decimal(str(charge["amount"]))

            assert charged, f"order {order.order_number} froze no fees"
            for name, total in charged.items():
                assert allocated[name] == total.quantize(CENT), (
                    f"{name} on {order.order_number} allocated "
                    f"{allocated[name]} against a charge of {total}"
                )

    async def test_the_frozen_fees_are_strings_not_numbers(
        self, db_session, world
    ) -> None:
        """A JSONB number is a float once anything reads it (Constitution IV)."""
        order = await _reload_order(db_session, world.order_ids[0])

        for item in order.items:
            for charge in item.fees_json or []:
                for field in ("amount", "rate_pct", "fixed_amount", "order_amount"):
                    assert isinstance(charge[field], str), (
                        f"{field} was frozen as {type(charge[field]).__name__}; a "
                        f"monetary figure must cross into JSON as a string"
                    )


class TestADatedReadIsAlsoProtected:
    """Belt and braces: the dated read must not drift either.

    The snapshot is the guarantee, but a report may also resolve policy and
    price as at the sale date. That path must give the same answer before and
    after the edits, or two reports of the same order would disagree.
    """

    async def test_the_policy_as_at_the_sale_date_is_unchanged_by_a_new_row(
        self, db_session, world
    ) -> None:
        """A new effective row leaves the one that was in force alone.

        Written through ``write_policy`` rather than by hand: it closes the
        superseded row, which the partial unique index on
        ``effective_to IS NULL`` requires -- there is exactly one current
        policy per tenant, and a second open row is refused by the schema.
        """
        before = await resolve_cost_policy(db_session, world.tenant, SALE_DAY)

        await write_policy(
            db_session,
            world.tenant,
            {
                "print_labor_rate": Decimal("41.00"),
                "finishing_labor_rate": Decimal("41.00"),
                "overhead_monthly_pool": Decimal("540.00"),
                "expected_monthly_machine_hours": Decimal("200"),
            },
            effective_from=clock.today(),
        )
        await db_session.flush()

        after = await resolve_cost_policy(db_session, world.tenant, SALE_DAY)
        today = await resolve_cost_policy(db_session, world.tenant, clock.today())

        assert after.print_labor_rate == before.print_labor_rate
        assert after.overhead_monthly_pool == before.overhead_monthly_pool
        assert today.print_labor_rate == Decimal("41.00"), (
            "the new row must actually be in force today, or this test is vacuous"
        )

    async def test_the_list_price_as_at_the_sale_date_is_unchanged_by_a_new_period(
        self, db_session, world
    ) -> None:
        from app.services.temporal_pricing import price_as_of, set_price

        await set_price(
            db_session,
            product_id=world.product.id,
            sales_channel_id=world.channel.id,
            list_price=Decimal("79.99"),
            valid_from=clock.today(),
        )
        await db_session.flush()

        then = await price_as_of(
            db_session, world.product.id, world.channel.id, as_of=SALE_DAY
        )
        now = await price_as_of(
            db_session, world.product.id, world.channel.id, as_of=clock.today()
        )

        assert then is not None and Decimal(str(then.list_price)) == Decimal("64.99")
        assert now is not None and Decimal(str(now.list_price)) == Decimal("79.99")
