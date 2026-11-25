"""AI 3D drafts into models (spec 008, US4, FR-017a, FR-019; T030, T032, T043).

A draft becomes an inactive "AI draft" version of the model; the active version
and the model's dimensions never change. On conversion of an idea, each 3D draft
adopted on it is carried to the new model, and a rollback removes the stored files.
"""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import get_settings
from app.models.generation_job import GenAIAdoption
from app.models.model import Model
from app.models.model_file import ModelFile
from app.models.model_file_version import ModelFileVersion
from app.services import idea_service as idea_service_module
from app.services.genai.adoption import AI_DRAFT_LABEL
from app.services.model_file_service import ModelFileService, ModelFileType
from app.services.model_file_version_service import ModelFileVersionService
from tests.utils.genai import GENAI, make_output_job
from tests.utils.ideas import idea_in

IDEAS = "/api/v1/ideas"


@pytest.fixture(autouse=True)
def model_storage(tmp_path, monkeypatch):
    """Model files go to a temporary directory."""
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_type", "local")
    monkeypatch.setattr(settings, "storage_path", str(tmp_path / "store"))
    return tmp_path / "store"


def _stored(root: Path) -> list[Path]:
    return [p for p in (root / "models").rglob("*") if p.is_file()] if root.exists() else []


async def _versions(db, model_id):
    return list(
        await db.scalars(
            select(ModelFileVersion)
            .where(ModelFileVersion.model_id == model_id)
            .order_by(ModelFileVersion.sequence)
            .execution_options(populate_existing=True)
        )
    )


# ============================================
# Additive service options
# ============================================


async def test_first_version_can_stay_inactive(db_session, test_tenant, test_model):
    service = ModelFileVersionService(db_session, test_tenant)
    version = await service.create_version(test_model, "AI draft", activate_if_first=False)
    assert version.is_active is False
    default = await ModelFileVersionService(db_session, test_tenant).create_version(test_model)
    assert default.is_active is False  # not the first any more


async def test_first_version_active_by_default(db_session, test_tenant, test_model):
    version = await ModelFileVersionService(db_session, test_tenant).create_version(test_model)
    assert version.is_active is True


async def test_upload_without_commit_or_measurement_offer(
    db_session, test_tenant, test_model, model_storage
):
    from app.services.genai.glb import build_glb, to_stl

    stl = to_stl(build_glb([(0, 0, 0), (40, 0, 0), (0, 30, 0), (0, 0, 20)], [0, 1, 2, 0, 1, 3]))
    model_id = test_model.id
    service = ModelFileService(db=db_session, tenant=test_tenant)
    model_file = await service.upload_file(
        model_id=model_id,
        file_content=stl,
        content_type="model/stl",
        original_filename="draft.stl",
        file_type=ModelFileType.SOURCE_STL,
        commit=False,
        offer_measurement=False,
    )
    assert model_file.measured_length_mm is not None  # recorded on the file
    assert model_file.measurement_applied_to == []
    model = await db_session.get(Model, model_id)
    assert model.length_mm is None  # never offered to the model
    url = model_file.file_url
    await db_session.rollback()  # nothing was committed
    assert await db_session.scalar(select(func.count(ModelFile.id))) == 0
    assert await service.delete_stored_file(url) is True
    assert _stored(model_storage) == []
    assert await service.delete_stored_file(None) is False


# ============================================
# Adopting a mesh into a model
# ============================================


async def test_adopt_mesh_adds_inactive_ai_draft(client, db_session, connected_tenant, test_model):
    model_id = test_model.id
    active = await ModelFileVersionService(db_session, connected_tenant).create_version(test_model)
    await db_session.commit()
    job, asset = await make_output_job(
        db_session, connected_tenant, capability="image_to_3d", kind="mesh"
    )
    response = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt", json={"target": {"type": "model", "id": str(model_id)}}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    versions = await _versions(db_session, model_id)
    assert [v.is_active for v in versions] == [True, False]
    assert versions[0].id == active.id
    draft = versions[1]
    assert draft.label == AI_DRAFT_LABEL
    assert str(job.id) in (draft.note or "")
    assert body["model_file_version_id"] == str(draft.id)
    model_file = await db_session.get(ModelFile, uuid.UUID(body["model_file_id"]))
    assert model_file.original_filename.endswith(".stl")
    assert model_file.version_id == draft.id
    model = await db_session.get(Model, model_id, populate_existing=True)
    assert model.length_mm is None and model.width_mm is None
    adoption = await db_session.scalar(select(GenAIAdoption))
    assert adoption.model_file_id == model_file.id


async def test_image_cannot_become_model_file(client, db_session, connected_tenant, test_model):
    _, asset = await make_output_job(db_session, connected_tenant)
    response = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt",
        json={"target": {"type": "model", "id": str(test_model.id)}},
    )
    assert response.status_code == 422
    assert await db_session.scalar(select(func.count(ModelFileVersion.id))) == 0


async def test_corrupt_mesh_leaves_nothing(
    client, db_session, connected_tenant, test_model, model_storage
):
    _, asset = await make_output_job(
        db_session, connected_tenant, capability="image_to_3d", kind="mesh"
    )
    from app.services.genai.storage import GenAIFileStore

    broken = b"glTF" + b"\x02\x00\x00\x00" + b"\x00" * 16
    store = GenAIFileStore()
    await store.delete(asset.storage_url)
    store._put(asset.storage_url[len("/uploads/") :], broken, "model/gltf-binary")
    response = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt",
        json={"target": {"type": "model", "id": str(test_model.id)}},
    )
    assert response.status_code == 422
    assert await db_session.scalar(select(func.count(ModelFileVersion.id))) == 0
    assert _stored(model_storage) == []


# ============================================
# Conversion carries 3D drafts (Q4)
# ============================================


async def _idea_with_draft(client, db_session, tenant):
    idea = await idea_in(db_session, tenant, title="Visor clip")
    idea_id = idea.id
    _, asset = await make_output_job(
        db_session, tenant, capability="image_to_3d", kind="mesh", target_type="idea",
        target_id=idea_id,
    )  # fmt: skip
    adopted = await client.post(
        f"{GENAI}/assets/{asset.id}/adopt", json={"target": {"type": "idea", "id": str(idea_id)}}
    )
    assert adopted.status_code == 201, adopted.text
    return idea_id


async def test_conversion_carries_drafts(client, db_session, connected_tenant):
    idea_id = await _idea_with_draft(client, db_session, connected_tenant)
    response = await client.post(f"{IDEAS}/{idea_id}/convert", json={"target": "model"})
    assert response.status_code == 201, response.text
    assert response.json()["warnings"] == []
    model_id = uuid.UUID(response.json()["model_id"])
    versions = await _versions(db_session, model_id)
    assert [(v.label, v.is_active) for v in versions] == [(AI_DRAFT_LABEL, False)]
    adoptions = list(await db_session.scalars(select(GenAIAdoption)))
    assert {a.owner_type for a in adoptions} == {"idea", "model"}
    model = await db_session.get(Model, model_id)
    assert model.length_mm is None


async def test_conversion_rollback_removes_draft_files(
    client, db_session, connected_tenant, model_storage, monkeypatch
):
    idea_id = await _idea_with_draft(client, db_session, connected_tenant)

    async def broken(*args, **kwargs):
        raise RuntimeError("product creation failed")

    monkeypatch.setattr(idea_service_module, "create_product", broken)
    with pytest.raises(RuntimeError):
        await client.post(f"{IDEAS}/{idea_id}/convert", json={"target": "product"})
    await db_session.rollback()
    assert await db_session.scalar(select(func.count(ModelFileVersion.id))) == 0
    assert await db_session.scalar(select(func.count(Model.id))) == 0
    assert _stored(model_storage) == []


async def test_conversion_reports_an_unusable_draft(client, db_session, connected_tenant):
    idea_id = await _idea_with_draft(client, db_session, connected_tenant)
    from app.services.genai.storage import GenAIFileStore
    from app.models.generation_job import GenAIAsset

    asset = await db_session.scalar(select(GenAIAsset).where(GenAIAsset.kind == "mesh"))
    await GenAIFileStore().delete(asset.storage_url)
    response = await client.post(f"{IDEAS}/{idea_id}/convert", json={"target": "model"})
    assert response.status_code == 201, response.text
    [warning] = response.json()["warnings"]
    assert "3D draft" in warning
    assert await db_session.scalar(select(func.count(ModelFileVersion.id))) == 0


async def test_product_conversion_carries_drafts(client, db_session, connected_tenant):
    """Converting to a product creates its model too, and the draft lands on that model."""
    idea_id = await _idea_with_draft(client, db_session, connected_tenant)
    response = await client.post(f"{IDEAS}/{idea_id}/convert", json={"target": "product"})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["product_id"] is not None
    assert body["warnings"] == []
    versions = await _versions(db_session, uuid.UUID(body["model_id"]))
    assert [(v.label, v.is_active) for v in versions] == [(AI_DRAFT_LABEL, False)]
    owners = {a.owner_type for a in await db_session.scalars(select(GenAIAdoption))}
    assert owners == {"idea", "model"}


async def test_archived_drafts_are_not_carried(client, db_session, connected_tenant):
    idea_id = await _idea_with_draft(client, db_session, connected_tenant)
    adoption = await db_session.scalar(
        select(GenAIAdoption).where(GenAIAdoption.owner_type == "idea")
    )
    archived = await client.delete(f"{IDEAS}/{idea_id}/entries/{adoption.idea_entry_id}")
    assert archived.status_code == 200, archived.text
    response = await client.post(f"{IDEAS}/{idea_id}/convert", json={"target": "model"})
    assert response.status_code == 201, response.text
    assert response.json()["warnings"] == []
    assert await _versions(db_session, uuid.UUID(response.json()["model_id"])) == []
    owners = {a.owner_type for a in await db_session.scalars(select(GenAIAdoption))}
    assert owners == {"idea"}
