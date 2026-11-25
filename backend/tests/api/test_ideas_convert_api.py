"""Turning an idea into a model or a product (spec 007, User Story 3)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idea import IdeaEntry
from app.models.model import Model
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.product_model import ProductModel
from app.models.user import UserRole
from app.services import idea_service as idea_service_module
from tests.utils.ideas import (
    IDEAS,
    create_idea,
    idea_in,
    image_file,
    other_tenant,
    upload_images,
)


@pytest.fixture(autouse=True)
def _storage(image_storage_fixture):
    return image_storage_fixture


async def _idea_with_images(client: AsyncClient) -> tuple[dict, list[dict]]:
    """An idea with a cover that is not pinned, two pinned images and one plain image."""
    idea = await create_idea(client, title="Sun visor clip", summary="Holds the visor.")
    images = (
        await upload_images(
            client,
            idea["id"],
            image_file("cover.jpg"),
            image_file("pin1.jpg"),
            image_file("pin2.jpg"),
            image_file("plain.jpg"),
        )
    ).json()["created"]
    for pinned in images[1:3]:
        await client.patch(f"{IDEAS}/{idea['id']}/entries/{pinned['id']}", json={"pinned": True})
    await client.patch(f"{IDEAS}/{idea['id']}", json={"cover_entry_id": images[0]["id"]})
    return idea, images


async def _count(db: AsyncSession, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


class TestConvertToModel:
    async def test_model_from_idea_links_both_ways(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        idea, _ = await _idea_with_images(client)
        response = await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "model"})
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["product_id"] is None and body["copied_images"] == 1

        model = await db_session.get(Model, uuid.UUID(body["model_id"]))
        assert (model.name, model.description) == ("Sun visor clip", "Holds the visor.")
        assert model.source_idea_id == uuid.UUID(idea["id"])
        assert model.image_url.startswith(f"/uploads/products/{model.id}/")
        assert model.sku.startswith("MOD-")

        assert body["idea"]["status"] == "converted"
        assert body["idea"]["model"] == {
            "id": str(model.id),
            "name": "Sun visor clip",
            "sku": model.sku,
            "state": "linked",
        }
        shown = (await client.get(f"/api/v1/models/{model.id}")).json()
        assert shown["source_idea_id"] == idea["id"]
        assert shown["source_idea_title"] == "Sun visor clip"
        assert shown["source_idea_archived"] is False

    async def test_name_and_sku_can_be_chosen(self, client: AsyncClient):
        idea = await create_idea(client)
        body = (
            await client.post(
                f"{IDEAS}/{idea['id']}/convert",
                json={"target": "model", "name": "Visor clip v2", "model_sku": "CLIP-1"},
            )
        ).json()
        shown = (await client.get(f"/api/v1/models/{body['model_id']}")).json()
        assert (shown["name"], shown["sku"]) == ("Visor clip v2", "CLIP-1")


class TestConvertToProduct:
    async def test_product_model_bom_and_images(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        idea, images = await _idea_with_images(client)
        response = await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "product"})
        assert response.status_code == 201, response.text
        body = response.json()
        product_id = uuid.UUID(body["product_id"])

        lines = list(
            await db_session.scalars(
                select(ProductModel).where(ProductModel.product_id == product_id)
            )
        )
        assert [(str(pm.model_id), pm.quantity) for pm in lines] == [(body["model_id"], 1)]

        product_images = list(
            await db_session.scalars(
                select(ProductImage)
                .where(ProductImage.product_id == product_id)
                .order_by(ProductImage.display_order)
            )
        )
        # Cover first (primary) even though it is not pinned, then the two pinned ones.
        names = [i.original_filename for i in product_images]
        assert names[0] == "cover.jpg"
        assert sorted(names[1:]) == ["pin1.jpg", "pin2.jpg"]
        assert [i.is_primary for i in product_images] == [True, False, False]

        # The product list names the idea too (contract: changes to existing endpoints).
        listed = (await client.get("/api/v1/products")).json()["products"]
        row = next(p for p in listed if p["id"] == body["product_id"])
        assert row["source_idea_id"] == idea["id"]
        assert row["source_idea_title"] == idea["title"]
        assert row["source_idea_archived"] is False
        searched = (await client.get("/api/v1/products", params={"search": "visor"})).json()
        for found in searched["products"]:
            if found["id"] == body["product_id"]:
                assert found["source_idea_id"] == idea["id"]
        assert all(
            i.image_url.startswith(f"/uploads/products/{product_id}/") for i in product_images
        )
        assert body["copied_images"] == 4  # model cover + three product images

        product = await db_session.get(Product, product_id)
        assert product.source_idea_id == uuid.UUID(idea["id"])
        shown = (await client.get(f"/api/v1/products/{product_id}")).json()
        assert shown["source_idea_title"] == "Sun visor clip"
        assert body["idea"]["product"]["state"] == "linked"
        assert body["idea"]["model"]["state"] == "linked"
        # Public product images open at their usual address.
        assert (await client.get(product_images[0].image_url)).status_code == 200
        assert len(images) == 4

    async def test_without_images(self, client: AsyncClient, db_session: AsyncSession):
        idea, _ = await _idea_with_images(client)
        body = (
            await client.post(
                f"{IDEAS}/{idea['id']}/convert",
                json={"target": "product", "include_images": False},
            )
        ).json()
        assert body["copied_images"] == 0
        assert await _count(db_session, ProductImage) == 0

    async def test_model_then_product_reuses_the_model(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        idea = await create_idea(client)
        first = (
            await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "model"})
        ).json()
        second = await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "product"})
        assert second.status_code == 201
        assert second.json()["model_id"] == first["model_id"]
        assert await _count(db_session, Model) == 1

    async def test_already_converted_to_product_is_refused(self, client: AsyncClient):
        idea = await create_idea(client)
        await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "product"})
        for target in ("product", "model"):
            response = await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": target})
            assert response.status_code == 409

    async def test_archived_idea_is_refused(self, client: AsyncClient):
        idea = await create_idea(client)
        await client.delete(f"{IDEAS}/{idea['id']}")
        response = await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "model"})
        assert response.status_code == 409


class TestAllOrNothing:
    async def test_taken_sku_creates_nothing(self, client: AsyncClient, db_session: AsyncSession):
        idea = await create_idea(client)
        await client.post("/api/v1/models", json={"sku": "TAKEN", "name": "Existing"})
        response = await client.post(
            f"{IDEAS}/{idea['id']}/convert", json={"target": "model", "model_sku": "TAKEN"}
        )
        assert response.status_code == 400
        assert await _count(db_session, Model) == 1
        assert (await client.get(f"{IDEAS}/{idea['id']}")).json()["status"] == "inbox"

    async def test_failure_after_model_rolls_everything_back(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch, image_storage_fixture
    ):
        idea, _ = await _idea_with_images(client)
        deleted: list[str] = []
        real_delete = image_storage_fixture.delete_image

        async def spy_delete(url, thumb=None):
            deleted.append(url)
            return await real_delete(url, thumb)

        async def boom(*args, **kwargs):
            raise RuntimeError("product creation failed")

        monkeypatch.setattr(image_storage_fixture, "delete_image", spy_delete)
        monkeypatch.setattr(idea_service_module, "create_product", boom)

        with pytest.raises(RuntimeError):
            await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "product"})

        assert await _count(db_session, Model) == 0
        assert await _count(db_session, Product) == 0
        # The model cover was copied before the failure, then deleted again.
        assert len(deleted) == 1 and deleted[0].startswith("/uploads/products/")
        assert (await client.get(f"{IDEAS}/{idea['id']}")).json()["status"] == "inbox"

    async def test_missing_image_file_is_a_warning(
        self, client: AsyncClient, db_session: AsyncSession, image_storage_fixture
    ):
        idea, images = await _idea_with_images(client)
        row = await db_session.get(IdeaEntry, uuid.UUID(images[1]["id"]))
        await image_storage_fixture.delete_image(row.image_url)

        response = await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "product"})
        assert response.status_code == 201
        body = response.json()
        assert len(body["warnings"]) == 1 and "pin1.jpg" in body["warnings"][0]
        assert body["copied_images"] == 3


class TestLinksAfterwards:
    async def test_deleted_model_shows_as_gone(self, client: AsyncClient, db_session: AsyncSession):
        idea = await create_idea(client)
        body = (await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "model"})).json()
        await db_session.delete(await db_session.get(Model, uuid.UUID(body["model_id"])))
        await db_session.commit()

        shown = (await client.get(f"{IDEAS}/{idea['id']}")).json()
        assert shown["model"] == {"id": None, "name": None, "sku": None, "state": "gone"}

    async def test_archived_idea_is_marked_on_the_model(self, client: AsyncClient):
        idea = await create_idea(client)
        body = (await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "model"})).json()
        await client.delete(f"{IDEAS}/{idea['id']}")
        shown = (await client.get(f"/api/v1/models/{body['model_id']}")).json()
        assert shown["source_idea_archived"] is True

    async def test_converted_idea_can_move_back_and_keeps_links(self, client: AsyncClient):
        idea = await create_idea(client)
        await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "model"})
        moved = (await client.patch(f"{IDEAS}/{idea['id']}", json={"status": "ready"})).json()
        assert moved["status"] == "ready" and moved["model"]["state"] == "linked"

    async def test_models_not_from_ideas_unchanged(self, client: AsyncClient):
        created = await client.post("/api/v1/models", json={"sku": "PLAIN-1", "name": "Plain"})
        assert created.status_code == 201
        assert created.json()["source_idea_id"] is None
        assert created.json()["source_idea_title"] is None


class TestConvertAccess:
    async def test_member_converts_to_model_but_not_to_product(self, client: AsyncClient, as_role):
        idea = await create_idea(client)
        other = await create_idea(client, title="Other")
        async with as_role(UserRole.MEMBER) as member:
            refused = await member.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "product"})
            assert refused.status_code == 403
            allowed = await member.post(f"{IDEAS}/{other['id']}/convert", json={"target": "model"})
            assert allowed.status_code == 201

    async def test_viewer_cannot_convert(self, client: AsyncClient, as_role):
        idea = await create_idea(client)
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "model"})
        assert response.status_code == 403

    async def test_requires_authentication(self, unauthenticated_client: AsyncClient):
        response = await unauthenticated_client.post(
            f"{IDEAS}/{uuid.uuid4()}/convert", json={"target": "model"}
        )
        assert response.status_code == 401

    async def test_unknown_and_foreign_ideas_are_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        foreign = await idea_in(db_session, await other_tenant(db_session))
        for idea_id in (uuid.uuid4(), foreign.id):
            response = await client.post(f"{IDEAS}/{idea_id}/convert", json={"target": "model"})
            assert response.status_code == 404

    async def test_bad_target_is_422(self, client: AsyncClient):
        idea = await create_idea(client)
        response = await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "bundle"})
        assert response.status_code == 422
