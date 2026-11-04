"""Making another version active restates no settled order (T024, FR-014, SC-003).

Activating a version can move a model's print time, parts per plate, weight and
dimensions -- every one of them an input to its cost. The settled orders of the
snapshot-immutability world must report exactly the margin they did, while the
live cost of the same product moves: the control that proves the activation
really changed an input.
"""

from decimal import Decimal

import pytest

from app.models.model_material import ModelMaterial
from app.services.cost_resolution import product_cost_breakdown
from app.services.model_file_service import ModelFileService
from app.services.model_file_version_service import ModelFileVersionService
from tests.fixtures.model_files import block_stl, sliced_3mf
from tests.integration.test_snapshot_immutability import (  # noqa: F401 - fixture
    _load_product,
    _reload_order,
    reported_margin,
    world,
)
from app.models.model_file import ModelFileType


@pytest.fixture(autouse=True)
def _local_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_TYPE", "local")
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _activate_a_slower_heavier_version(db, world) -> None:  # noqa: F811
    files = ModelFileService(db, world.tenant)
    await files.upload_file(
        world.model.id, block_stl(), "model/stl", "v1.stl", ModelFileType.SOURCE_STL
    )
    sliced = await files.upload_file(
        world.model.id,
        sliced_3mf(plates=1, seconds=60 * 900, weight="120.00"),
        "application/octet-stream",
        "v2.gcode.3mf",
        ModelFileType.SOURCE_3MF,
        new_version_label="2",
    )
    versions = ModelFileVersionService(db, world.tenant)
    version = await versions.get(world.model.id, sliced.version_id)
    preview = await versions.activation_preview(world.model, version)
    selectable = [row.field for row in preview.rows if row.selectable]
    assert "print_time_minutes" in selectable, preview
    await versions.activate(world.model, version, selectable)


class TestActivationRestatesNothing:
    async def test_settled_orders_keep_their_margin(self, db_session, world) -> None:  # noqa: F811
        before = {
            order_id: await reported_margin(
                db_session, world.tenant, await _reload_order(db_session, order_id)
            )
            for order_id in world.order_ids
        }
        await _activate_a_slower_heavier_version(db_session, world)
        after = {
            order_id: await reported_margin(
                db_session, world.tenant, await _reload_order(db_session, order_id)
            )
            for order_id in world.order_ids
        }
        assert after == before

    async def test_the_live_cost_did_move(self, db_session, world) -> None:  # noqa: F811
        """The control: without it the test above would hold for an activation that did nothing."""
        product = await _load_product(db_session, world.product.id)
        live_before = (
            await product_cost_breakdown(db_session, world.tenant, product)
        ).total_make_cost
        await _activate_a_slower_heavier_version(db_session, world)
        await db_session.refresh(world.model)
        assert world.model.print_time_minutes == 900
        material = await db_session.get(ModelMaterial, world.material.id)
        await db_session.refresh(material)
        product = await _load_product(db_session, world.product.id)
        live_after = (
            await product_cost_breakdown(db_session, world.tenant, product)
        ).total_make_cost
        assert live_after > live_before > Decimal("0")
