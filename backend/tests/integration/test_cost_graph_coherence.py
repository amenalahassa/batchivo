"""No stale figure may be served through any transitive ancestor.

Constitution V: a derived figure must not be served after any input beneath it
has changed, *including transitively through nested bills of materials*. A
stale cost raises no error and reads like a real one, which makes it the most
damaging failure this system can have.

The test builds a randomised bill-of-materials graph -- leaves with their own
materials, bundles of those, bundles of bundles -- mutates one leaf input, and
asserts every ancestor's reported cost moved by exactly the amount the mutation
implies. Recomputation on demand is what makes this pass; introducing a stored
derived cost without invalidation in the same change is what would break it.
"""

import random
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.product import Product
from app.models.product_component import ProductComponent
from app.models.product_model import ProductModel
from app.models.spool import Spool
from app.models.tenant import Tenant
from app.services.costing import CostingService

SEED = 20261011
LABOR_RATE = Decimal("25.00")


#: How deep a bundle hierarchy these tests build. The engine's own limit is
#: MAX_RECURSION_DEPTH; this is only how far the test eager-loads.
PRELOAD_DEPTH = 4


def _eager_options(depth: int = PRELOAD_DEPTH) -> list:
    """Eager-load a product graph `depth` bundle levels down.

    The engine is synchronous, so anything it touches must already be loaded --
    a lazy load inside it would raise rather than return a stale figure, which
    would hide the very thing this file tests.
    """
    branch = selectinload(Product.child_products).selectinload(ProductComponent.child_product)
    options = [
        selectinload(Product.product_models).selectinload(ProductModel.model),
        selectinload(Product.packaging_consumable),
        branch,
    ]
    for _ in range(depth):
        options.append(branch.selectinload(Product.product_models).selectinload(ProductModel.model))
        options.append(branch.selectinload(Product.packaging_consumable))
        branch = branch.selectinload(Product.child_products).selectinload(
            ProductComponent.child_product
        )
        options.append(branch)
    return options


async def _cost(db: AsyncSession, product_id) -> Decimal:
    """Cost a product from scratch: nothing from the session, nothing cached.

    `expunge_all` is deliberate. Reading through objects the session already
    holds would test SQLAlchemy's identity map, not whether the engine serves a
    stale figure.
    """
    db.expunge_all()
    product = (
        await db.execute(select(Product).where(Product.id == product_id).options(*_eager_options()))
    ).scalar_one()
    return CostingService.calculate_product_cost(product, labor_rate=LABOR_RATE).total_make_cost


async def _set_cost_per_gram(db: AsyncSession, material_id, value: Decimal) -> None:
    """Change one BOM input from outside any session that might cache it."""
    await db.execute(
        update(ModelMaterial).where(ModelMaterial.id == material_id).values(cost_per_gram=value)
    )
    await db.commit()


async def _make_leaf(
    db: AsyncSession,
    tenant: Tenant,
    spool_id,
    grams: Decimal,
    cost_per_gram: Decimal,
    tag: str,
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
        cost_per_gram=cost_per_gram,
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
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        """One leaf input moves; the leaf, its bundle and the bundle of bundles all move."""
        leaf, material = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("142"), Decimal("0.0310"), "A"
        )
        sibling, _ = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("80"), Decimal("0.0200"), "B"
        )
        middle = await _make_bundle(db_session, test_tenant, [(leaf, 2), (sibling, 1)], "MID")
        top = await _make_bundle(db_session, test_tenant, [(middle, 3)], "TOP")
        await db_session.commit()

        leaf_id, middle_id, top_id, material_id = leaf.id, middle.id, top.id, material.id

        before = {
            "leaf": await _cost(db_session, leaf_id),
            "middle": await _cost(db_session, middle_id),
            "top": await _cost(db_session, top_id),
        }

        # One input beneath everything changes.
        await _set_cost_per_gram(db_session, material_id, Decimal("0.0620"))

        after = {
            "leaf": await _cost(db_session, leaf_id),
            "middle": await _cost(db_session, middle_id),
            "top": await _cost(db_session, top_id),
        }

        leaf_delta = after["leaf"] - before["leaf"]
        assert leaf_delta > 0, "the leaf served a stale cost after its own input changed"
        assert after["middle"] - before["middle"] == leaf_delta * 2, (
            "the bundle did not reflect its child's change at the child's quantity"
        )
        assert after["top"] - before["top"] == leaf_delta * 2 * 3, (
            "the bundle of bundles served a figure stale through two levels"
        )

    async def test_a_seeded_random_graph_reports_no_stale_cost_anywhere(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        """Build an arbitrary graph, perturb one leaf, check every ancestor."""
        rng = random.Random(SEED)

        leaves: list[tuple[Product, ModelMaterial]] = []
        for index in range(6):
            leaves.append(
                await _make_leaf(
                    db_session,
                    test_tenant,
                    test_spool.id,
                    Decimal(rng.randrange(20, 400)),
                    Decimal(rng.randrange(100, 900)) / Decimal("10000"),
                    f"R{index}",
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
        perturbed_id = leaves[0][1].id
        perturbed_from = Decimal(str(leaves[0][1].cost_per_gram))
        second_id = second.id

        before = {pid: await _cost(db_session, pid) for pid in tracked}
        second_before = await _cost(db_session, second_id)

        # Perturb the leaf that sits under `first` and therefore under `root`.
        await _set_cost_per_gram(db_session, perturbed_id, perturbed_from * Decimal("3"))

        after = {pid: await _cost(db_session, pid) for pid in tracked}

        for pid in tracked:
            assert after[pid] > before[pid], (
                f"product {pid} served {after[pid]}, unchanged from {before[pid]}, "
                "after an input beneath it changed"
            )

        # `second` holds none of the perturbed leaf, so it must not move.
        assert await _cost(db_session, second_id) == second_before

    async def test_an_unrelated_branch_does_not_move(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        """Coherence cuts both ways: a change must not leak sideways."""
        touched, material = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("142"), Decimal("0.0310"), "T"
        )
        untouched, _ = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("142"), Decimal("0.0310"), "U"
        )
        unrelated = await _make_bundle(db_session, test_tenant, [(untouched, 2)], "UNREL")
        await db_session.commit()

        touched_id, unrelated_id, material_id = touched.id, unrelated.id, material.id

        before = await _cost(db_session, unrelated_id)
        touched_before = await _cost(db_session, touched_id)

        await _set_cost_per_gram(db_session, material_id, Decimal("0.0999"))

        assert await _cost(db_session, touched_id) > touched_before
        assert await _cost(db_session, unrelated_id) == before


class TestTheBomSnapshotIsADeliberateBoundary:
    """`ModelMaterial.cost_per_gram` is a snapshot, and that is on purpose.

    Changing a *spool's* price does not restate a bill of materials: the BOM
    line captured the price at the moment the material was added, which is what
    keeps a model's historical cost meaningful. This is the boundary of the
    coherence guarantee above, and it is asserted here so nobody later reads the
    silence as a bug -- or, worse, "fixes" it and restates settled history.

    Tier 1's landed cost (tasks T042, T039) changes *how* the per-gram figure is
    derived when a BOM line is created or refreshed. It must not make an
    existing line track its spool retroactively.
    """

    async def test_changing_a_spool_price_does_not_restate_an_existing_bom_line(
        self, db_session: AsyncSession, test_tenant: Tenant, test_spool
    ) -> None:
        leaf, _ = await _make_leaf(
            db_session, test_tenant, test_spool.id, Decimal("142"), Decimal("0.0310"), "SNAP"
        )
        await db_session.commit()

        leaf_id = leaf.id
        spool_id = test_spool.id
        was = Decimal(str(test_spool.purchase_price or "20.00"))

        before = await _cost(db_session, leaf_id)

        await db_session.execute(
            update(Spool).where(Spool.id == spool_id).values(purchase_price=was * Decimal("5"))
        )
        await db_session.commit()

        assert await _cost(db_session, leaf_id) == before, (
            "a spool price change restated an existing BOM line; the snapshot is "
            "what keeps a model's historical cost meaningful"
        )
