"""Owner-keyed image storage (spec 007, research R1).

Product images must keep exactly their historical paths (FR-021, SC-007);
ideas get their own ``ideas/{id}/`` directory; unknown owners and path tricks
are refused; ``copy_image`` makes an independent copy for another owner.
"""

import re
import uuid
from io import BytesIO

import boto3
import pytest
from moto import mock_aws
from PIL import Image

from app.services.image_storage import MAX_FILE_SIZE, ImageStorage, ImageStorageError

TEST_BUCKET = "batchivo-owner-keyed-images"
UUID_FILE = r"[0-9a-f-]{36}"


def _jpeg(width: int = 120, height: int = 80) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color="blue").save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture(params=["local", "s3"])
def storage(request, tmp_path):
    """The same assertions against both backends."""
    store = ImageStorage()
    if request.param == "local":
        store.storage_type = "local"
        store.base_path = tmp_path
        yield store
        return
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=TEST_BUCKET)
        store.storage_type = "s3"
        store._s3_client = client
        store._bucket = TEST_BUCKET
        yield store


# ============================================
# Product paths do not move
# ============================================


@pytest.mark.asyncio
async def test_product_keyword_call_keeps_historical_path(storage):
    product_id = str(uuid.uuid4())
    result = await storage.save_image(_jpeg(), "image/jpeg", product_id=product_id)
    assert re.fullmatch(rf"/uploads/products/{product_id}/{UUID_FILE}\.jpg", result["image_url"])
    assert re.fullmatch(
        rf"/uploads/products/{product_id}/{UUID_FILE}_thumb\.jpg", result["thumbnail_url"]
    )


@pytest.mark.asyncio
async def test_default_owner_type_is_products(storage):
    owner = str(uuid.uuid4())
    result = await storage.save_image(_jpeg(), "image/jpeg", owner)
    assert result["image_url"].startswith(f"/uploads/products/{owner}/")


@pytest.mark.asyncio
async def test_non_uuid_product_owner_still_accepted(storage):
    """The shop logo has always been stored as products/tenant-logo-<id>/."""
    owner = f"tenant-logo-{uuid.uuid4()}"
    result = await storage.save_image(_jpeg(), "image/jpeg", product_id=owner)
    assert result["image_url"].startswith(f"/uploads/products/{owner}/")


# ============================================
# Ideas and other owners
# ============================================


@pytest.mark.asyncio
async def test_idea_images_go_under_ideas(storage):
    idea_id = str(uuid.uuid4())
    result = await storage.save_image(_jpeg(), "image/jpeg", idea_id, owner_type="ideas")
    assert result["image_url"].startswith(f"/uploads/ideas/{idea_id}/")
    assert result["thumbnail_url"].startswith(f"/uploads/ideas/{idea_id}/")
    content, content_type = await storage.get_image(result["image_url"])
    assert content and content_type == "image/jpeg"


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_type", ["users", "", "../products"])
async def test_unknown_owner_type_refused(storage, owner_type):
    with pytest.raises(ImageStorageError, match="owner type"):
        await storage.save_image(_jpeg(), "image/jpeg", str(uuid.uuid4()), owner_type=owner_type)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_id", ["../etc", "a/b", "a\\b", "", None])
async def test_path_tricks_in_owner_id_refused(storage, owner_id):
    with pytest.raises(ImageStorageError, match="owner id"):
        await storage.save_image(_jpeg(), "image/jpeg", owner_id, owner_type="ideas")


@pytest.mark.asyncio
async def test_validation_unchanged_for_new_owners(storage):
    with pytest.raises(ImageStorageError, match="Invalid file type"):
        await storage.save_image(b"%PDF", "application/pdf", str(uuid.uuid4()), owner_type="ideas")
    with pytest.raises(ImageStorageError, match="too large"):
        await storage.save_image(
            b"x" * (MAX_FILE_SIZE + 1), "image/jpeg", str(uuid.uuid4()), owner_type="ideas"
        )


# ============================================
# Copy between owners
# ============================================


@pytest.mark.asyncio
async def test_copy_image_creates_an_independent_file(storage):
    idea_id, product_id = str(uuid.uuid4()), str(uuid.uuid4())
    source = await storage.save_image(_jpeg(), "image/jpeg", idea_id, owner_type="ideas")

    copy = await storage.copy_image(source["image_url"], "products", product_id)

    assert copy["image_url"].startswith(f"/uploads/products/{product_id}/")
    assert copy["image_url"] != source["image_url"]
    assert copy["content_type"] == "image/jpeg"
    await storage.delete_image(source["image_url"], source["thumbnail_url"])
    content, _ = await storage.get_image(copy["image_url"])
    assert content


@pytest.mark.asyncio
async def test_copy_of_missing_image_raises(storage):
    with pytest.raises(ImageStorageError):
        await storage.copy_image(
            f"/uploads/ideas/{uuid.uuid4()}/missing.jpg", "products", str(uuid.uuid4())
        )
