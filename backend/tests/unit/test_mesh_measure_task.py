"""The background measurement of a large model file (T037).

``measure_pending`` is what the Celery task runs; the tests call it with the
test session, reading the file from a local reference on disk.
"""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.model import Model
from app.models.model_file import FileLocation, ModelFile
from app.models.tenant import Tenant
from app.services.dims import Dims
from app.tasks.mesh_measure import measure_pending

pytestmark = pytest.mark.asyncio

MESHES = Path(__file__).parent.parent / "fixtures" / "meshes"


async def _model(db, tenant) -> Model:
    model = Model(id=uuid4(), tenant_id=tenant.id, sku=f"M-{uuid4().hex[:6]}", name="Block")
    db.add(model)
    await db.commit()
    return model


async def _pending(db, tenant, model, fixture: str) -> ModelFile:
    path = MESHES / fixture
    f = ModelFile(
        tenant_id=tenant.id,
        model_id=model.id,
        file_type="source_stl",
        file_location=FileLocation.LOCAL_REFERENCE.value,
        local_path=str(path),
        original_filename=fixture,
        file_size=path.stat().st_size,
        is_primary=False,
        measurement_status="pending",
    )
    db.add(f)
    await db.commit()
    return f


class TestMeasurePending:
    async def test_pending_becomes_done_and_applies(self, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        f = await _pending(db_session, test_tenant, model, "block_binary.stl")

        assert await measure_pending(db_session, test_tenant, f.id) == "done"
        await db_session.refresh(f)
        await db_session.refresh(model)
        assert f.measured_length_mm == Decimal("40.0")
        assert model.dimensions_source == "measured"
        assert model.dimensions_source_file_id == f.id

    async def test_entered_dimensions_are_left_alone(self, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        model.length_mm, model.width_mm, model.height_mm = (
            Decimal("100.0"), Decimal("90.0"), Decimal("80.0"),
        )  # fmt: skip
        model.dimensions_source = "entered"
        await db_session.commit()
        f = await _pending(db_session, test_tenant, model, "block_binary.stl")

        await measure_pending(db_session, test_tenant, f.id)
        await db_session.refresh(model)
        assert Dims.from_row(model) == Dims(Decimal("100.0"), Decimal("90.0"), Decimal("80.0"))
        assert model.dimensions_source == "entered"

    async def test_unreadable_file_fails(self, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        f = await _pending(db_session, test_tenant, model, "not_a_mesh.stl")

        assert await measure_pending(db_session, test_tenant, f.id) == "failed"
        await db_session.refresh(f)
        assert f.measurement_note
        assert f.measured_length_mm is None

    async def test_second_run_writes_nothing(self, db_session, test_tenant) -> None:
        model = await _model(db_session, test_tenant)
        f = await _pending(db_session, test_tenant, model, "block_binary.stl")
        await measure_pending(db_session, test_tenant, f.id)
        await db_session.refresh(f)
        measured_at = f.measured_at

        assert await measure_pending(db_session, test_tenant, f.id) == "done"
        await db_session.refresh(f)
        assert f.measured_at == measured_at

    async def test_another_tenants_file_is_not_touched(self, db_session, test_tenant) -> None:
        other = Tenant(id=uuid4(), name="Other", slug=f"o-{uuid4().hex[:8]}", settings={})
        db_session.add(other)
        await db_session.commit()
        model = await _model(db_session, other)
        f = await _pending(db_session, other, model, "block_binary.stl")

        assert await measure_pending(db_session, test_tenant, f.id) is None
        await db_session.refresh(f)
        assert f.measurement_status == "pending"
