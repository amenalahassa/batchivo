"""The "does not show the real item" warning survives edits (spec 008 FR-030, SC-005, T098).

Whether a job's results show the real item is decided once, at creation, from its
capability and from where each input came from; adopting into a product reads it.
Replicate is never called: jobs are finished by hand, as the runner would.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.models.generation_job import GenAIAdoption, GenAIAsset, GenerationJob
from app.models.product_image import ProductImage
from app.services.genai.service import GenAIService, JobRequest
from app.services.genai.storage import GenAIFileStore
from tests.utils.genai import GENAI, make_output_job, png_bytes
from tests.utils.ideas import entry_in, idea_in

EDIT = "image_edit"


def _ref(kind: str, ref_id) -> dict:
    return {"type": kind, "id": str(ref_id)}


def _edit(ref: dict) -> dict:
    return {"capability": EDIT, "inputs": {"instruction": "make it blue", "input_assets": [ref]}}


async def _stored_image_url(tenant, owner_type: str = "ideas") -> str:
    from app.services.image_storage import get_image_storage

    stored = await get_image_storage().save_image(
        png_bytes(), "image/png", str(tenant.id), "in.png", owner_type=owner_type
    )
    return stored["image_url"]


async def _finish(db, job_id: uuid.UUID) -> GenAIAsset:
    """Mark a job succeeded with one stored image output, as the runner leaves it."""
    job = await db.get(GenerationJob, job_id)
    saved = await GenAIFileStore().save_image(png_bytes(), "image/png", str(job.id))
    asset = GenAIAsset(
        tenant_id=job.tenant_id,
        job_id=job.id,
        source="output",
        kind="image",
        storage_url=saved["url"],
        thumbnail_url=saved["thumbnail_url"],
        content_type=saved["content_type"],
        file_size=saved["file_size"],
        width=saved["width"],
        height=saved["height"],
        ai_generated=True,
    )
    job.status = "succeeded"
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def _generation_entry(db, tenant, job_id):
    idea = await idea_in(db, tenant)
    return await entry_in(
        db,
        idea,
        kind="generation",
        body="Concept",
        image_url=await _stored_image_url(tenant),
        generation_job_id=job_id,
    )


async def _created_flag(db, tenant, capability: str, inputs: dict) -> bool:
    job = await GenAIService(db, tenant).create_job(JobRequest(capability, inputs))
    return job.shows_real_item


async def _adopt_needs_confirmation(client, db, tenant, user, asset_id, product) -> None:
    target = {"type": "product", "id": str(product.id)}
    refused = await client.post(f"{GENAI}/assets/{asset_id}/adopt", json={"target": target})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["code"] == "needs_confirmation"
    count = await db.scalar(select(func.count(ProductImage.id)).where(ProductImage.origin == "ai"))
    assert count == 0
    # The refusal rolled the shared test session back; reload what the next request reuses.
    for obj in (tenant, user):
        await db.refresh(obj)
    confirmed = await client.post(
        f"{GENAI}/assets/{asset_id}/adopt", json={"target": target, "confirm_not_real_item": True}
    )
    assert confirmed.status_code == 201, confirmed.text
    adoption = await db.scalar(select(GenAIAdoption).where(GenAIAdoption.asset_id == asset_id))
    assert adoption.warning_confirmed is True


# ============================================
# Through the API: create, finish, adopt into a product
# ============================================


async def test_edited_concept_needs_confirmation(
    client, db_session, connected_tenant, test_user, test_product
):
    _, concept = await make_output_job(db_session, connected_tenant, capability="concept_image")
    created = await client.post(f"{GENAI}/jobs", json=_edit(_ref("asset", concept.id)))
    assert created.status_code == 201, created.text
    assert created.json()["shows_real_item"] is False
    job_id = uuid.UUID(created.json()["id"])
    output = await _finish(db_session, job_id)
    fetched = await client.get(f"{GENAI}/jobs/{job_id}")
    assert fetched.json()["shows_real_item"] is False
    await _adopt_needs_confirmation(
        client, db_session, connected_tenant, test_user, output.id, test_product
    )


async def test_edited_generation_entry_needs_confirmation(
    client, db_session, connected_tenant, test_user, test_product
):
    concept, _ = await make_output_job(db_session, connected_tenant, capability="concept_image")
    entry = await _generation_entry(db_session, connected_tenant, concept.id)
    created = await client.post(f"{GENAI}/jobs", json=_edit(_ref("idea_entry", entry.id)))
    assert created.status_code == 201, created.text
    assert created.json()["shows_real_item"] is False
    output = await _finish(db_session, uuid.UUID(created.json()["id"]))
    await _adopt_needs_confirmation(
        client, db_session, connected_tenant, test_user, output.id, test_product
    )


async def test_edited_sketch_needs_confirmation(
    client, db_session, connected_tenant, test_user, test_product
):
    idea = await idea_in(db_session, connected_tenant)
    sketch = await entry_in(
        db_session,
        idea,
        kind="sketch",
        body=None,
        image_url=await _stored_image_url(connected_tenant),
    )
    created = await client.post(f"{GENAI}/jobs", json=_edit(_ref("idea_entry", sketch.id)))
    assert created.status_code == 201, created.text
    assert created.json()["shows_real_item"] is False
    output = await _finish(db_session, uuid.UUID(created.json()["id"]))
    await _adopt_needs_confirmation(
        client, db_session, connected_tenant, test_user, output.id, test_product
    )


async def test_edited_photo_adopts_directly(client, db_session, connected_tenant, test_product):
    upload = await client.post(
        f"{GENAI}/uploads", files={"file": ("photo.png", png_bytes(), "image/png")}
    )
    assert upload.status_code == 201, upload.text
    created = await client.post(f"{GENAI}/jobs", json=_edit(_ref("asset", upload.json()["id"])))
    assert created.status_code == 201, created.text
    assert created.json()["shows_real_item"] is True
    output = await _finish(db_session, uuid.UUID(created.json()["id"]))
    adopted = await client.post(
        f"{GENAI}/assets/{output.id}/adopt",
        json={"target": {"type": "product", "id": str(test_product.id)}},
    )
    assert adopted.status_code == 201, adopted.text
    adoption = await db_session.scalar(select(GenAIAdoption))
    assert adoption.warning_confirmed is False


async def test_concept_job_response_carries_the_flag(client, db_session, connected_tenant):
    created = await client.post(
        f"{GENAI}/jobs", json={"capability": "concept_image", "inputs": {"prompt": "a clip"}}
    )
    assert created.status_code == 201
    assert created.json()["shows_real_item"] is False
    listed = await client.get(f"{GENAI}/jobs")
    assert [j["shows_real_item"] for j in listed.json()["items"]] == [False]


# ============================================
# The service decides once, at creation
# ============================================


@pytest.mark.parametrize(
    "capability, inputs",
    [
        ("image_edit", {"instruction": "blue"}),
        ("product_photo_enhance", {}),
        ("upscale", {"factor": 2}),
        ("lifestyle_scene", {"scene": "on a desk"}),
        ("background_remove", {}),
    ],
)
async def test_every_capability_inherits_from_a_concept(
    db_session, connected_tenant, capability, inputs
):
    _, concept = await make_output_job(db_session, connected_tenant, capability="concept_image")
    real = await _created_flag(
        db_session,
        connected_tenant,
        capability,
        {**inputs, "input_assets": [_ref("asset", concept.id)]},
    )
    assert real is False


async def test_a_real_input_keeps_the_capability_answer(db_session, connected_tenant):
    _, enhanced = await make_output_job(
        db_session, connected_tenant, capability="product_photo_enhance"
    )
    assert (
        await _created_flag(
            db_session, connected_tenant, "upscale", {"input_assets": [_ref("asset", enhanced.id)]}
        )
        is True
    )
    # image_to_3d never shows the real item, whatever its input
    assert (
        await _created_flag(
            db_session,
            connected_tenant,
            "image_to_3d",
            {"input_assets": [_ref("asset", enhanced.id)]},
        )
        is False
    )


async def test_a_chain_of_edits_keeps_the_answer(db_session, connected_tenant):
    _, concept = await make_output_job(db_session, connected_tenant, capability="concept_image")
    first = await GenAIService(db_session, connected_tenant).create_job(
        JobRequest(EDIT, {"instruction": "blue", "input_assets": [_ref("asset", concept.id)]})
    )
    edited = await _finish(db_session, first.id)
    assert (
        await _created_flag(
            db_session, connected_tenant, "upscale", {"input_assets": [_ref("asset", edited.id)]}
        )
        is False
    )


async def test_reusing_an_imported_input_keeps_the_answer(db_session, connected_tenant):
    idea = await idea_in(db_session, connected_tenant)
    sketch = await entry_in(
        db_session,
        idea,
        kind="sketch",
        body=None,
        image_url=await _stored_image_url(connected_tenant),
    )
    first = await GenAIService(db_session, connected_tenant).create_job(
        JobRequest(EDIT, {"instruction": "blue", "input_assets": [_ref("idea_entry", sketch.id)]})
    )
    assert first.shows_real_item is False
    [imported] = first.inputs["input_assets"]
    assert (
        await _created_flag(
            db_session, connected_tenant, "upscale", {"input_assets": [_ref("asset", imported)]}
        )
        is False
    )


async def test_a_sketch_first_used_as_a_concept_reference_stays_not_real(
    client, db_session, connected_tenant, test_user, test_product
):
    """T101: the import remembers the sketch, whatever job first used it."""
    idea = await idea_in(db_session, connected_tenant)
    sketch = await entry_in(
        db_session,
        idea,
        kind="sketch",
        body=None,
        image_url=await _stored_image_url(connected_tenant),
    )
    concept = await client.post(
        f"{GENAI}/jobs",
        json={
            "capability": "concept_image",
            "inputs": {"prompt": "a visor clip", "input_assets": [_ref("idea_entry", sketch.id)]},
        },
    )
    assert concept.status_code == 201, concept.text
    [imported] = concept.json()["inputs"]["input_assets"]
    stored = await db_session.get(GenAIAsset, uuid.UUID(imported))
    assert stored.source == "upload" and stored.shows_real_item is False

    edited = await client.post(f"{GENAI}/jobs", json=_edit(_ref("asset", imported)))
    assert edited.status_code == 201, edited.text
    assert edited.json()["shows_real_item"] is False
    output = await _finish(db_session, uuid.UUID(edited.json()["id"]))
    await _adopt_needs_confirmation(
        client, db_session, connected_tenant, test_user, output.id, test_product
    )


async def test_an_imported_photo_reused_by_id_stays_real(db_session, connected_tenant):
    idea = await idea_in(db_session, connected_tenant)
    photo = await entry_in(
        db_session,
        idea,
        kind="image",
        body=None,
        image_url=await _stored_image_url(connected_tenant),
    )
    first = await GenAIService(db_session, connected_tenant).create_job(
        JobRequest(
            "concept_image", {"prompt": "a clip", "input_assets": [_ref("idea_entry", photo.id)]}
        )
    )
    assert first.shows_real_item is False  # the capability, not the input
    [imported] = first.inputs["input_assets"]
    assert (await db_session.get(GenAIAsset, uuid.UUID(imported))).shows_real_item is True
    assert (
        await _created_flag(
            db_session, connected_tenant, EDIT, _edit(_ref("asset", imported))["inputs"]
        )
        is True
    )


async def test_generation_entry_of_an_unknown_job_is_not_real(db_session, connected_tenant):
    entry = await _generation_entry(db_session, connected_tenant, None)
    real = await _created_flag(
        db_session,
        connected_tenant,
        EDIT,
        {"instruction": "x", "input_assets": [_ref("idea_entry", entry.id)]},
    )
    assert real is False


async def test_generation_entry_of_a_real_job_is_real(db_session, connected_tenant):
    enhanced, _ = await make_output_job(
        db_session, connected_tenant, capability="product_photo_enhance"
    )
    entry = await _generation_entry(db_session, connected_tenant, enhanced.id)
    real = await _created_flag(
        db_session, connected_tenant, "upscale", {"input_assets": [_ref("idea_entry", entry.id)]}
    )
    assert real is True


async def test_photo_entries_and_images_are_real(db_session, connected_tenant, test_product):
    idea = await idea_in(db_session, connected_tenant)
    photo = await entry_in(
        db_session,
        idea,
        kind="image",
        body=None,
        image_url=await _stored_image_url(connected_tenant),
    )
    assert (
        await _created_flag(
            db_session,
            connected_tenant,
            "upscale",
            {"input_assets": [_ref("idea_entry", photo.id)]},
        )
        is True
    )
    for order, origin in enumerate(("photo", "render")):
        image = ProductImage(
            tenant_id=connected_tenant.id,
            product_id=test_product.id,
            image_url=await _stored_image_url(connected_tenant, "products"),
            display_order=order,
            origin=origin,
        )
        db_session.add(image)
        await db_session.commit()
        assert (
            await _created_flag(
                db_session,
                connected_tenant,
                "upscale",
                {"input_assets": [_ref("product_image", image.id)]},
            )
            is True
        )


async def test_ai_product_image_follows_its_source(
    client, db_session, connected_tenant, test_user, test_product
):
    _, concept = await make_output_job(db_session, connected_tenant, capability="concept_image")
    adopted = await client.post(
        f"{GENAI}/assets/{concept.id}/adopt",
        json={
            "target": {"type": "product", "id": str(test_product.id)},
            "confirm_not_real_item": True,
        },
    )
    assert adopted.status_code == 201, adopted.text
    image_id = adopted.json()["product_image_id"]
    assert (
        await _created_flag(
            db_session,
            connected_tenant,
            "upscale",
            {"input_assets": [_ref("product_image", image_id)]},
        )
        is False
    )

    _, enhanced = await make_output_job(
        db_session, connected_tenant, capability="product_photo_enhance"
    )
    adopted = await client.post(
        f"{GENAI}/assets/{enhanced.id}/adopt",
        json={"target": {"type": "product", "id": str(test_product.id)}},
    )
    assert adopted.status_code == 201, adopted.text
    assert (
        await _created_flag(
            db_session,
            connected_tenant,
            "upscale",
            {"input_assets": [_ref("product_image", adopted.json()["product_image_id"])]},
        )
        is True
    )
