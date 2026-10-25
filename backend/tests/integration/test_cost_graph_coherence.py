"""No stale figure may be served through any transitive ancestor.

Constitution V: a derived figure must not be served after any input beneath it
has changed, *including transitively through nested bills of materials*. A
stale cost raises no error and reads like a real one, which makes it the most
damaging failure this system can have.

The test builds a randomised bill-of-materials graph -- leaves with their own
materials, bundles of those, bundles of bundles -- mutates one leaf input, and
asserts every ancestor's reported cost moved by exactly the amount the mutation
implies. The leaf input is a spool -- its price, its purchase's shipping, its
remainder -- since a bill-of-materials line costs at the spool's landed figure
(T254). Recomputation on demand is what makes this pass; introducing a stored
derived cost without invalidation in the same change is what would break it.
"""

import random
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.filament_purchase import FilamentPurchase
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.product import Product
from app.models.product_component import ProductComponent
from app.models.product_model import ProductModel
from app.models.spool import Spool
from app.models.tenant import Tenant
from app.services.cost_resolution import cost_load_options
from app.services.costing import CostingService

SEED = 20261011
LABOR_RATE = Decimal("25.00")


async def _cost(db: AsyncSession, product_id) -> Decimal:
    """Cost a product from scratch: nothing from the session, nothing cached.

    `expunge_all` is deliberate. Reading through objects the session already
    holds would test SQLAlchemy's identity map, not whether the engine serves a
    stale figure.
    """
    db.expunge_all()
    product = (
        await db.execute(
            select(Product).where(Product.id == product_id).options(*cost_load_options())
        )
    ).scalar_one()
    return CostingService.calculate_product_cost(product, labor_rate=LABOR_RATE).total_make_cost


async def _set_spool(db: AsyncSession, spool_id, **values) -> None:
    """Change one leaf input from outside any session that might cache it.

    The leaf input is the spool, as T009 asks: a bill-of-materials line costs
    at its spool's landed per-gram figure, derived on read (T254).
    """
    await db.execute(update(Spool).where(Spool.id == spool_id).values(**values))
    await db.commit()


async def _make_spool(
    db: AsyncSession, tenant: Tenant, filament_type_id, price: Decimal, tag: str
) -> Spool:
    """A 1 kg spool of its own, so moving it moves exactly one leaf."""
    spool = Spool(
        id=uuid4(),
        tenant_id=tenant.id,
        filament_type_id=filament_type_id,
        spool_id=f"GRAPH-S-{tag}",
        initial_weight=Decimal("1000"),
        current_weight=Decimal("1000"),
        purchase_price=price,
        is_active=True,
        is_labeled=False,
    )
    db.add(spool)
    await db.flush()
    return spool


async def _make_leaf(
    db: AsyncSession,
    tenant: Tenant,
    spool_id,
    grams: Decimal,
    tag: str,
    *,
    override: Optional[Decimal] = None,
) -> tuple[Product, ModelMaterial]:
    """A product holding one model, which holds one BOM line."""
    model = Model(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"GRAPH-M-{tag}",
        name=f"Graph model {tag}",
        is_active=True,
    )
    db.add(model)
    await db.flush()

    material = ModelMaterial(
        id=uuid4(),
        model_id=model.id,
        spool_id=spool_id,
        weight_grams=grams,
        cost_per_gram=override,
    )
    db.add(material)

    product = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"GRAPH-P-{tag}",
        name=f"Graph product {tag}",
        is_active=True,
    )
    db.add(product)
    await db.flush()

    db.add(ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1))
    await db.flush()
    return product, material


async def _make_bundle(
    db: AsyncSession,
    tenant: Tenant,
    children: list[tuple[Product, int]],
    tag: str,
) -> Product:
    bundle = Product(
        id=uuid4(),
        tenant_id=tenant.id,
        sku=f"GRAPH-B-{tag}",
        name=f"Graph bundle {tag}",
        is_active=True,
    )
    db.add(bundle)
    await db.flush()
    for child, quantity in children:
        db.add(
            ProductComponent(
                id=uuid4(),
                parent_product_id=bundle.id,
                child_product_id=child.id,
                quantity=quantity,
            )
        )
    await db.flush()
    return bundle


class TestLeafChangePropagatesToEveryAncestor:
    async def test_a_three_level_graph_reports_no_stale_cost(
        self, db_session: AsyncSession, test_tenant: Tenant, test_filament_type
    ) -> None:
        """One spool's price moves; the leaf, its bundle and the bundle of bundles all move."""
        spool = await _make_spool(
            db_session, test_tenant, test_filament_type.id, Decimal("31.00"), "A"
        )
        other = await _make_spool(
            db_session, test_tenant, test_filament_type.id, Decimal("20.00"), "B"
        )
        leaf, _ = await _make_leaf(db_session, test_tenant, spool.id, Decimal("142"), "A")
        sibling, _ = await _make_leaf(db_session, test_tenant, other.id, Decimal("80"), "B")
        middle = await _make_bundle(db_session, test_tenant, [(leaf, 2), (sibling, 1)], "MID")
        top = await _make_bundle(db_session, test_tenant, [(middle, 3)], "TOP")
        await db_session.commit()

        leaf_id, middle_id, top_id, spool_id = leaf.id, middle.id, top.id, spool.id

        before = {
            "leaf": await _cost(db_session, leaf_id),
            "middle": await _cost(db_session, middle_id),
            "top": await _cost(db_session, top_id),
        }

        # One input beneath everything changes: the spool rises by 50.00.
        await _set_spool(db_session, spool_id, purchase_price=Decimal("81.00"))

        after = {
            "leaf": await _cost(db_session, leaf_id),
            "middle": await _cost(db_session, middle_id),
            "top": await _cost(db_session, top_id),
        }

        leaf_delta = after["leaf"] - before["leaf"]
        # 142 g at 0.05 more per gram.
        assert leaf_delta == Decimal("7.10"), "the leaf served a stale cost after its spool moved"
        assert after["middle"] - before["middle"] == leaf_delta * 2, (
            "the bundle did not reflect its child's change at the child's quantity"
        )
        assert after["top"] - before["top"] == leaf_delta * 2 * 3, (
            "the bundle of bundles served a figure stale through two levels"
        )

    async def test_a_seeded_random_graph_reports_no_stale_cost_anywhere(
        self, db_session: AsyncSession, test_tenant: Tenant, test_filament_type
    ) -> None:
        """Build an arbitrary graph, perturb one leaf's spool, check every ancestor."""
        rng = random.Random(SEED)

        leaves: list[tuple[Product, ModelMaterial]] = []
        spools: list[Spool] = []
        for index in range(6):
            spool = await _make_spool(
                db_session,
                test_tenant,
                test_filament_type.id,
                Decimal(rng.randrange(1000, 9000)) / Decimal("100"),
                f"R{index}",
            )
            spools.append(spool)
            leaves.append(
                await _make_leaf(
                    db_session, test_tenant, spool.id, Decimal(rng.randrange(20, 400)), f"R{index}"
                )
            )

        # Two bundles over disjoint leaves, then one bundle over both.
        first = await _make_bundle(
            db_session,
            test_tenant,
            [(leaves[i][0], rng.randrange(1, 4)) for i in (0, 1, 2)],
            "R-FIRST",
        )
        second = await _make_bundle(
            db_session,
            test_tenant,
            [(leaves[i][0], rng.randrange(1, 4)) for i in (3, 4)],
            "R-SECOND",
        )
        root = await _make_bundle(
            db_session, test_tenant, [(first, 1), (second, 2), (leaves[5][0], 1)], "R-ROOT"
        )
        await db_session.commit()

        tracked = [leaves[0][0].id, first.id, root.id]
        perturbed_spool = spools[0].id
        perturbed_from = Decimal(str(spools[0].purchase_price))
        second_id = second.id

        before = {pid: await _cost(db_session, pid) for pid in tracked}
        second_before = await _cost(db_session, second_id)

        # Perturb the spool under `first` and therefore under `root`.
        await _set_spool(db_session, perturbed_spool, purchase_price=perturbed_from * Decimal("3"))

        after = {pid: await _cost(db_session, pid) for pid in tracked}

        for pid in tracked:
            assert after[pid] > before[pid], (
                f"product {pid} served {after[pid]}, unchanged from {before[pid]}, "
                "after an input beneath it changed"
            )

        # `second` holds none of the perturbed leaf, so it must not move.
        assert await _cost(db_session, second_id) == second_before

    async def test_an_unrelated_branch_does_not_move(
        self, db_session: AsyncSession, test_tenant: Tenant, test_filament_type
    ) -> None:
        """Coherence cuts both ways: a change must not leak sideways."""
        moved = await _make_spool(
            db_session, test_tenant, test_filament_type.id, Decimal("31"), "T"
        )
        still = await _make_spool(
            db_session, test_tenant, test_filament_type.id, Decimal("31"), "U"
        )
        touched, _ = await _make_leaf(db_session, test_tenant, moved.id, Decimal("142"), "T")
        untouched, _ = await _make_leaf(db_session, test_tenant, still.id, Decimal("142"), "U")
        unrelated = await _make_bundle(db_session, test_tenant, [(untouched, 2)], "UNREL")
        await db_session.commit()

        touched_id, unrelated_id, spool_id = touched.id, unrelated.id, moved.id

        before = await _cost(db_session, unrelated_id)
        touched_before = await _cost(db_session, touched_id)

        await _set_spool(db_session, spool_id, purchase_price=Decimal("99.90"))

        assert await _cost(db_session, touched_id) > touched_before
        assert await _cost(db_session, unrelated_id) == before


class TestEveryLandedInputReachesTheMakeCost:
    """FR-008 to FR-008d hold on the make-cost, not only on the purchase screen.

    Each part of the landed cost -- allocated shipping, the unusable remainder
    -- is moved on its own, and the leaf's material line follows it exactly.
    """

    async def test_purchase_shipping_is_allocated_into_the_material_line(
        self, db_session: AsyncSession, test_tenant: Tenant, test_filament_type
    ) -> None:
        purchase = FilamentPurchase(
            id=uuid4(),
            tenant_id=test_tenant.id,
            purchase_date=date(2026, 10, 1),
            inbound_shipping_cost=Decimal("0"),
            tax_amount=Decimal("0"),
            tax_recoverable=True,
        )
        db_session.add(purchase)
        await db_session.flush()
        spools = [
            await _make_spool(
                db_session, test_tenant, test_filament_type.id, Decimal("25"), f"P{index}"
            )
            for index in range(4)
        ]
        for spool in spools:
            spool.filament_purchase_id = purchase.id
        leaf, _ = await _make_leaf(db_session, test_tenant, spools[0].id, Decimal("100"), "SHIP")
        await db_session.commit()
        leaf_id, purchase_id = leaf.id, purchase.id

        before = await _cost(db_session, leaf_id)
        await db_session.execute(
            update(FilamentPurchase)
            .where(FilamentPurchase.id == purchase_id)
            .values(inbound_shipping_cost=Decimal("24.00"))
        )
        await db_session.commit()

        # 24.00 over four 1 kg spools is 6.00 a spool, 0.006 a gram, 0.60 on 100 g.
        assert await _cost(db_session, leaf_id) - before == Decimal("0.600")

    async def test_the_unusable_remainder_raises_the_per_gram_cost(
        self, db_session: AsyncSession, test_tenant: Tenant, test_filament_type
    ) -> None:
        spool = await _make_spool(
            db_session, test_tenant, test_filament_type.id, Decimal("30"), "REM"
        )
        leaf, _ = await _make_leaf(db_session, test_tenant, spool.id, Decimal("100"), "REM")
        await db_session.commit()
        leaf_id, spool_id = leaf.id, spool.id

        before = await _cost(db_session, leaf_id)
        await _set_spool(db_session, spool_id, unusable_remainder_grams=Decimal("250"))

        # 30.00 over 750 usable grams instead of 1000: 0.04 a gram, not 0.03.
        assert await _cost(db_session, leaf_id) - before == Decimal("1.000")


class TestAnOverrideIsTheOperatorsFigure:
    """A per-gram figure typed on the line wins, and does not follow the spool.

    It is the one deliberate boundary: the operator decided that figure, so a
    spool price change must not overwrite it (FR-002). Settled history is not
    this boundary's job -- a sale freezes its cost on its snapshot (FR-036) and
    consumed material is frozen on the production run.
    """

    async def test_a_spool_price_change_does_not_move_an_overridden_line(
        self, db_session: AsyncSession, test_tenant: Tenant, test_filament_type
    ) -> None:
        spool = await _make_spool(
            db_session, test_tenant, test_filament_type.id, Decimal("20"), "OVR"
        )
        leaf, _ = await _make_leaf(
            db_session, test_tenant, spool.id, Decimal("142"), "OVR", override=Decimal("0.0310")
        )
        await db_session.commit()
        leaf_id, spool_id = leaf.id, spool.id

        before = await _cost(db_session, leaf_id)
        await _set_spool(db_session, spool_id, purchase_price=Decimal("100"))

        assert await _cost(db_session, leaf_id) == before
