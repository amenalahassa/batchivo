"""Product image origin: photo, render or ai (spec 008, FR-018, T040)."""

import uuid

from app.models.product_image import ProductImage


async def _image(db, product, origin="photo"):
    image = ProductImage(
        tenant_id=product.tenant_id,
        product_id=product.id,
        image_url=f"/uploads/products/{uuid.uuid4().hex}.png",
        origin=origin,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    return image


def _url(product, image):
    return f"/api/v1/products/{product.id}/images/{image.id}"


async def test_existing_images_read_as_photo(client, db_session, test_product):
    await _image(db_session, test_product)
    body = (await client.get(f"/api/v1/products/{test_product.id}/images")).json()
    assert [i["origin"] for i in body["images"]] == ["photo"]


async def test_operator_labels_a_render(client, db_session, test_product):
    image = await _image(db_session, test_product)
    response = await client.patch(_url(test_product, image), json={"origin": "render"})
    assert response.status_code == 200
    assert response.json()["origin"] == "render"


async def test_ai_cannot_be_set_by_hand(client, db_session, test_product):
    image = await _image(db_session, test_product)
    response = await client.patch(_url(test_product, image), json={"origin": "ai"})
    assert response.status_code == 422


async def test_ai_image_keeps_its_label(client, db_session, test_product):
    image = await _image(db_session, test_product, origin="ai")
    product_id, image_id = test_product.id, image.id
    refused = await client.patch(
        f"/api/v1/products/{product_id}/images/{image_id}", json={"origin": "photo"}
    )
    assert refused.status_code == 422
    await db_session.refresh(test_product)
    alt = await client.patch(
        f"/api/v1/products/{product_id}/images/{image_id}", json={"alt_text": "On a desk"}
    )
    assert alt.status_code == 200
    assert alt.json()["origin"] == "ai"


async def test_null_origin_is_ignored(client, db_session, test_product):
    image = await _image(db_session, test_product, origin="render")
    response = await client.patch(_url(test_product, image), json={"origin": None})
    assert response.status_code == 200
    assert response.json()["origin"] == "render"
