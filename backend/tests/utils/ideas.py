"""Shared builders for the Ideas tests (spec 007)."""

import uuid
from contextlib import contextmanager
from io import BytesIO
from typing import Optional

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idea import Idea, IdeaEntry
from app.models.tenant import Tenant

IDEAS = "/api/v1/ideas"


@contextmanager
def signed_out():
    """Drop the signed-in overrides for one call.

    ``client`` and ``unauthenticated_client`` share ``app.dependency_overrides``;
    when a test takes both, the anonymous client is still signed in unless the
    user and tenant overrides are lifted for its request.
    """
    from app.auth.dependencies import get_current_tenant, get_current_user
    from app.main import app

    saved = {
        dep: app.dependency_overrides.pop(dep)
        for dep in (get_current_user, get_current_tenant)
        if dep in app.dependency_overrides
    }
    try:
        yield
    finally:
        app.dependency_overrides.update(saved)


def jpeg_bytes(width: int = 64, height: int = 48, color: str = "green") -> bytes:
    """A small valid JPEG."""
    buffer = BytesIO()
    Image.new("RGB", (width, height), color=color).save(buffer, format="JPEG")
    return buffer.getvalue()


def image_file(name: str = "photo.jpg", content: Optional[bytes] = None, ctype="image/jpeg"):
    """One multipart ``files`` part."""
    return ("files", (name, content if content is not None else jpeg_bytes(), ctype))


async def other_tenant(db: AsyncSession) -> Tenant:
    """A second shop, to prove ideas never cross tenants."""
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Other Shop",
        slug=f"other-{uuid.uuid4().hex[:8]}",
        settings={"currency": "GBP"},
    )
    db.add(tenant)
    await db.commit()
    return tenant


async def idea_in(db: AsyncSession, tenant: Tenant, **fields) -> Idea:
    """An idea written straight to the database for ``tenant``."""
    idea = Idea(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        title=fields.pop("title", "Foreign idea"),
        tags=fields.pop("tags", []),
        **fields,
    )
    db.add(idea)
    await db.commit()
    return idea


async def entry_in(db: AsyncSession, idea: Idea, **fields) -> IdeaEntry:
    """A timeline entry written straight to the database."""
    entry = IdeaEntry(
        id=uuid.uuid4(),
        tenant_id=idea.tenant_id,
        idea_id=idea.id,
        kind=fields.pop("kind", "note"),
        iteration=fields.pop("iteration", 1),
        body=fields.pop("body", "A note"),
        **fields,
    )
    db.add(entry)
    await db.commit()
    return entry


async def create_idea(client, **body) -> dict:
    """Create an idea through the API and return its JSON."""
    body.setdefault("title", "Sun visor clip")
    response = await client.post(IDEAS, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def upload_images(client, idea_id: str, *files, kind: str = "image"):
    """Upload images to an idea; returns the response."""
    return await client.post(
        f"{IDEAS}/{idea_id}/entries/images",
        files=list(files) or [image_file()],
        data={"kind": kind},
    )
