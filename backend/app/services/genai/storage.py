"""Storage for the files the genai layer keeps (research R7, R11).

Outputs are kept at full resolution: ``ImageStorage.save_image`` resizes to its
800 px display size, which would undo an upscale. Files live under
``generations/…`` in the same local directory or S3 bucket as ``ImageStorage``,
with the same ``/uploads/<key>`` URL form, so ``ImageStorage.copy_image`` can
copy an output to an idea or a product on adoption. No public route serves
``generations/``: the API serves them to signed-in members of the tenant only.
"""

import logging
import uuid
from io import BytesIO
from pathlib import Path
from typing import Optional

from botocore.exceptions import ClientError
from PIL import Image

from app.services.genai.errors import GenAIError
from app.services.image_storage import THUMBNAIL_SIZE, get_image_storage

logger = logging.getLogger(__name__)

PREFIX = "generations"
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
#: the image formats accepted, read from the file itself (never from the declared type)
FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
MESH_TYPES = {"model/gltf-binary": ".glb"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_MESH_BYTES = 200 * 1024 * 1024


class GenAIStorageError(GenAIError):
    """A file could not be stored or read."""

    code = "storage_error"
    http_status = 500


def _owner_dir(owner: str) -> str:
    owner = str(owner)
    if not owner or "/" in owner or "\\" in owner or ".." in owner:
        raise GenAIStorageError("Invalid storage owner")
    return f"{PREFIX}/{owner}"


def _key(url: str) -> str:
    if not url.startswith(f"/uploads/{PREFIX}/") or ".." in url:
        raise GenAIStorageError("Invalid generation file URL")
    return url[len("/uploads/") :]


class GenAIFileStore:
    """Raw files under ``generations/{owner}/``, local or S3 like ``ImageStorage``."""

    def __init__(self) -> None:
        storage = get_image_storage()
        self._images = storage
        self.storage_type = storage.storage_type
        self.base_path = Path(storage.base_path)

    # ------------------------------------------------------------------ bytes

    def _put(self, key: str, content: bytes, content_type: str) -> None:
        if self.storage_type == "local":
            path = self.base_path / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return
        try:
            self._images._s3_client.put_object(  # noqa: SLF001 - same bucket and client
                Bucket=self._images._bucket, Key=key, Body=content, ContentType=content_type
            )
        except ClientError as exc:
            raise GenAIStorageError(f"Could not store the file: {exc}") from exc

    async def get(self, url: str) -> bytes:
        key = _key(url)
        if self.storage_type == "local":
            path = self.base_path / key
            if not path.exists():
                raise GenAIStorageError("File not found", code="not_found")
            return path.read_bytes()
        try:
            response = self._images._s3_client.get_object(  # noqa: SLF001
                Bucket=self._images._bucket, Key=key
            )
            return response["Body"].read()
        except ClientError as exc:
            raise GenAIStorageError("File not found", code="not_found") from exc

    async def delete(self, url: Optional[str]) -> None:
        if not url:
            return
        try:
            key = _key(url)
        except GenAIStorageError:
            return
        try:
            if self.storage_type == "local":
                (self.base_path / key).unlink(missing_ok=True)
            else:
                self._images._s3_client.delete_object(  # noqa: SLF001
                    Bucket=self._images._bucket, Key=key
                )
        except (OSError, ClientError) as exc:
            logger.warning(f"Could not delete generation file {url}: {exc}")

    # ------------------------------------------------------------------ typed saves

    async def save_image(self, content: bytes, content_type: str, owner: str) -> dict:
        """Store an image at full size plus a thumbnail; returns urls and dimensions."""
        if len(content) > MAX_IMAGE_BYTES:
            raise GenAIStorageError("Image larger than 10 MB", code="too_large")
        try:
            img = Image.open(BytesIO(content))
            img.load()
        except Exception as exc:  # noqa: BLE001 - Pillow raises many types
            raise GenAIStorageError(f"Not a readable image: {exc}", code="invalid_file") from exc
        fmt = (img.format or "").upper()
        if fmt not in FORMATS:
            # GIF, BMP, TIFF…: refused rather than converted (contract, uploads).
            raise GenAIStorageError(
                "Only JPEG, PNG and WebP images are accepted", code="unsupported_type"
            )
        content_type = FORMATS[fmt]
        ext = IMAGE_TYPES[content_type]
        name = str(uuid.uuid4())
        owner_dir = _owner_dir(owner)
        key = f"{owner_dir}/{name}{ext}"
        thumb_key = f"{owner_dir}/{name}_thumb{ext}"
        thumb = img.copy()
        thumb.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        if content_type == "image/jpeg" and thumb.mode in ("RGBA", "P", "LA"):
            thumb = thumb.convert("RGB")
        thumb_buffer = BytesIO()
        thumb.save(thumb_buffer, format=fmt)
        self._put(key, content, content_type)
        try:
            self._put(thumb_key, thumb_buffer.getvalue(), content_type)
        except GenAIStorageError:
            await self.delete(f"/uploads/{key}")
            raise
        return {
            "url": f"/uploads/{key}",
            "thumbnail_url": f"/uploads/{thumb_key}",
            "content_type": content_type,
            "file_size": len(content),
            "width": img.width,
            "height": img.height,
        }

    async def save_mesh(self, content: bytes, owner: str) -> dict:
        """Store a GLB mesh."""
        if len(content) > MAX_MESH_BYTES:
            raise GenAIStorageError("Mesh larger than 200 MB", code="too_large")
        if content[:4] != b"glTF":
            raise GenAIStorageError("The 3D output is not a GLB file", code="invalid_file")
        key = f"{_owner_dir(owner)}/{uuid.uuid4()}.glb"
        self._put(key, content, "model/gltf-binary")
        return {
            "url": f"/uploads/{key}",
            "thumbnail_url": None,
            "content_type": "model/gltf-binary",
            "file_size": len(content),
            "width": None,
            "height": None,
        }


__all__ = [
    "GenAIFileStore",
    "GenAIStorageError",
    "MAX_IMAGE_BYTES",
    "MAX_MESH_BYTES",
]
