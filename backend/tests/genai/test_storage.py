"""The generated-file store (spec 008, R7, R11; T014, T090).

An S3 round trip against moto (never a real bucket), and the path tricks the
store refuses: an owner that would leave its directory, and a URL outside
``/uploads/generations/``.
"""

import boto3
import pytest
from moto import mock_aws

from app.services.genai.storage import GenAIFileStore, GenAIStorageError, _key, _owner_dir
from tests.utils.genai import glb_bytes, png_bytes

BUCKET = "batchivo-genai-test"


@pytest.fixture
def s3_store(genai_storage, monkeypatch):
    """The store on a moto bucket; the shared storage is restored afterwards."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        monkeypatch.setattr(genai_storage, "storage_type", "s3")
        monkeypatch.setattr(genai_storage, "_s3_client", client, raising=False)
        monkeypatch.setattr(genai_storage, "_bucket", BUCKET, raising=False)
        yield GenAIFileStore(), client


def _keys(client) -> set[str]:
    return {o["Key"] for o in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])}


async def test_s3_image_round_trip(s3_store):
    store, client = s3_store
    content = png_bytes(320, 200)

    saved = await store.save_image(content, "image/png", "job-1")

    assert saved["url"].startswith("/uploads/generations/job-1/")
    assert saved["thumbnail_url"].startswith("/uploads/generations/job-1/")
    assert (saved["width"], saved["height"], saved["file_size"]) == (320, 200, len(content))
    key = saved["url"][len("/uploads/") :]
    assert _keys(client) == {key, saved["thumbnail_url"][len("/uploads/") :]}
    assert client.head_object(Bucket=BUCKET, Key=key)["ContentType"] == "image/png"
    # Full size: the stored bytes are the bytes given, never resized.
    assert await store.get(saved["url"]) == content

    await store.delete(saved["url"])
    await store.delete(saved["thumbnail_url"])

    assert _keys(client) == set()
    with pytest.raises(GenAIStorageError) as caught:
        await store.get(saved["url"])
    assert caught.value.code == "not_found"


async def test_s3_mesh_round_trip(s3_store):
    store, client = s3_store
    saved = await store.save_mesh(glb_bytes(), "job-2")
    assert saved["content_type"] == "model/gltf-binary"
    assert await store.get(saved["url"]) == glb_bytes()
    await store.delete(saved["url"])
    assert _keys(client) == set()


@pytest.mark.parametrize("owner", ["..", "../other", "a/b", "a\\b", "x..y", ""])
def test_owner_cannot_leave_its_directory(owner):
    with pytest.raises(GenAIStorageError):
        _owner_dir(owner)


async def test_save_refuses_a_bad_owner(s3_store):
    store, client = s3_store
    with pytest.raises(GenAIStorageError):
        await store.save_image(png_bytes(), "image/png", "../products")
    assert _keys(client) == set()


def test_owner_dir_for_a_job_and_for_uploads():
    assert _owner_dir("job-1") == "generations/job-1"
    assert _owner_dir("uploads-abc") == "generations/uploads-abc"


@pytest.mark.parametrize(
    "url",
    [
        "/uploads/products/x/a.png",
        "/uploads/ideas/x/a.png",
        "/uploads/generations/../products/a.png",
        "/uploads/generations/job/../../secret",
        "generations/job/a.png",
        "https://example.com/uploads/generations/job/a.png",
        "/uploads/generationsX/a.png",
    ],
)
def test_url_outside_generations_is_refused(url):
    with pytest.raises(GenAIStorageError):
        _key(url)


def test_key_of_a_generation_url():
    assert _key("/uploads/generations/job-1/a.png") == "generations/job-1/a.png"


async def test_get_refuses_a_url_outside_generations(s3_store):
    store, client = s3_store
    client.put_object(Bucket=BUCKET, Key="products/p/a.png", Body=b"not yours")
    with pytest.raises(GenAIStorageError):
        await store.get("/uploads/products/p/a.png")
    # delete ignores such a URL and leaves the file alone.
    await store.delete("/uploads/products/p/a.png")
    assert _keys(client) == {"products/p/a.png"}
