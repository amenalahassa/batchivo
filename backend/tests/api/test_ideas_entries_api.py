"""Ideas timeline: entries, images, iterations, cover, private images (spec 007, US2)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idea import IdeaEntry
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services.image_storage import MAX_FILE_SIZE
from tests.utils.ideas import (
    signed_out,
    IDEAS,
    create_idea,
    entry_in,
    idea_in,
    image_file,
    other_tenant,
    upload_images,
)


@pytest.fixture(autouse=True)
def _storage(image_storage_fixture):
    """Every test here stores images in a temporary place (local or mocked S3)."""
    return image_storage_fixture


async def _entries(client: AsyncClient, idea_id: str, **params) -> dict:
    response = await client.get(f"{IDEAS}/{idea_id}/entries", params=params)
    assert response.status_code == 200
    return response.json()


# ============================================
# Text entries
# ============================================


class TestTextEntries:
    async def test_note_goes_to_iteration_1_with_author(self, client: AsyncClient):
        idea = await create_idea(client)
        response = await client.post(
            f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "# Heading\n- a"}
        )
        assert response.status_code == 201
        entry = response.json()
        assert (entry["kind"], entry["iteration"]) == ("note", 1)
        assert entry["author"]["name"] == "Test User"
        assert entry["image_path"] is None and entry["edited_at"] is None

    async def test_entry_bumps_idea_updated_at(self, client: AsyncClient):
        idea = await create_idea(client)
        await client.post(f"{IDEAS}/{idea['id']}/entries", json={"kind": "decision", "body": "go"})
        refreshed = (await client.get(f"{IDEAS}/{idea['id']}")).json()
        assert refreshed["updated_at"] > idea["updated_at"]

    @pytest.mark.parametrize(
        "body",
        [
            {"kind": "link"},
            {"kind": "link", "link_url": "javascript:alert(1)"},
            {"kind": "note", "body": "   "},
            {"kind": "measurement"},
            {"kind": "generation", "body": "x"},
            {"kind": "image", "body": "x"},
            {"kind": "brief", "body": "x"},
        ],
    )
    async def test_invalid_entries(self, client: AsyncClient, body):
        idea = await create_idea(client)
        response = await client.post(f"{IDEAS}/{idea['id']}/entries", json=body)
        assert response.status_code == 422

    async def test_link_and_measurement(self, client: AsyncClient):
        idea = await create_idea(client)
        link = await client.post(
            f"{IDEAS}/{idea['id']}/entries",
            json={"kind": "link", "link_url": "https://example.org/x", "body": "competitor"},
        )
        measure = await client.post(
            f"{IDEAS}/{idea['id']}/entries",
            json={"kind": "measurement", "body": "visor 4.2 mm"},
        )
        assert link.status_code == measure.status_code == 201
        assert link.json()["link_url"] == "https://example.org/x"

    async def test_edit_pin_archive_restore(self, client: AsyncClient):
        idea = await create_idea(client)
        first = (
            await client.post(f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "a"})
        ).json()
        second = (
            await client.post(f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "b"})
        ).json()
        url = f"{IDEAS}/{idea['id']}/entries/{first['id']}"

        edited = (await client.patch(url, json={"body": "a, edited"})).json()
        assert edited["body"] == "a, edited" and edited["edited_at"] is not None

        pinned = (await client.patch(url, json={"pinned": True})).json()
        assert pinned["pinned"] is True
        ids = [e["id"] for e in (await _entries(client, idea["id"]))["items"]]
        assert ids == [first["id"], second["id"]]  # pinned first within the iteration

        assert (await client.delete(url)).json()["archived"] is True
        assert [e["id"] for e in (await _entries(client, idea["id"]))["items"]] == [second["id"]]
        archived = await _entries(client, idea["id"], archived=True)
        assert len(archived["items"]) == 2

        assert (await client.patch(url, json={"archived": False})).json()["archived"] is False

    async def test_blanking_a_note_is_refused(self, client: AsyncClient):
        idea = await create_idea(client)
        note = (
            await client.post(f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "a"})
        ).json()
        response = await client.patch(
            f"{IDEAS}/{idea['id']}/entries/{note['id']}", json={"body": " "}
        )
        assert response.status_code == 422

    async def test_note_cannot_become_a_sketch(self, client: AsyncClient):
        idea = await create_idea(client)
        note = (
            await client.post(f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "a"})
        ).json()
        response = await client.patch(
            f"{IDEAS}/{idea['id']}/entries/{note['id']}", json={"kind": "sketch"}
        )
        assert response.status_code == 422


# ============================================
# Iterations
# ============================================


class TestIterations:
    async def test_next_iteration_with_note_groups_the_timeline(self, client: AsyncClient):
        idea = await create_idea(client)
        await client.post(f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "v1"})

        response = await client.post(
            f"{IDEAS}/{idea['id']}/iterations", json={"note": "clip-on instead of screw"}
        )
        assert response.status_code == 201
        timeline = response.json()
        assert timeline["current_iteration"] == 2
        assert [(e["iteration"], e["body"]) for e in timeline["items"]] == [
            (2, "clip-on instead of screw"),
            (1, "v1"),
        ]

        later = await client.post(
            f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "after"}
        )
        assert later.json()["iteration"] == 2
        assert (await client.get(f"{IDEAS}/{idea['id']}")).json()["current_iteration"] == 2

    async def test_next_iteration_without_note(self, client: AsyncClient):
        idea = await create_idea(client)
        response = await client.post(f"{IDEAS}/{idea['id']}/iterations", json={})
        assert response.json() == {"items": [], "current_iteration": 2}


# ============================================
# Images
# ============================================


class TestImages:
    async def test_several_images_at_once(self, client: AsyncClient):
        idea = await create_idea(client)
        response = await upload_images(
            client, idea["id"], image_file("a.jpg"), image_file("b.jpg"), image_file("c.jpg")
        )
        assert response.status_code == 201
        created = response.json()["created"]
        assert [e["original_filename"] for e in created] == ["a.jpg", "b.jpg", "c.jpg"]
        assert all(e["kind"] == "image" and e["thumbnail_path"] for e in created)
        assert created[0]["image_path"].startswith(f"/api/v1/ideas/{idea['id']}/entries/")

    async def test_bad_files_refused_one_by_one(self, client: AsyncClient):
        idea = await create_idea(client)
        response = await upload_images(
            client,
            idea["id"],
            image_file("ok.jpg"),
            image_file("doc.pdf", b"%PDF-1.4", "application/pdf"),
            image_file("huge.jpg", b"x" * (MAX_FILE_SIZE + 1)),
        )
        assert response.status_code == 201
        body = response.json()
        assert [e["original_filename"] for e in body["created"]] == ["ok.jpg"]
        refused = {r["filename"]: r["reason"] for r in body["refused"]}
        assert "Invalid file type" in refused["doc.pdf"]
        assert "too large" in refused["huge.jpg"]

    async def test_all_refused_is_422(self, client: AsyncClient):
        idea = await create_idea(client)
        response = await upload_images(
            client, idea["id"], image_file("doc.pdf", b"%PDF", "application/pdf")
        )
        assert response.status_code == 422
        assert "doc.pdf" in response.text

    async def test_too_many_files(self, client: AsyncClient):
        idea = await create_idea(client)
        files = [image_file(f"{n}.jpg") for n in range(11)]
        assert (await upload_images(client, idea["id"], *files)).status_code == 422

    async def test_sketch_kind_and_switch_back(self, client: AsyncClient):
        idea = await create_idea(client)
        sketch = (await upload_images(client, idea["id"], kind="sketch")).json()["created"][0]
        assert sketch["kind"] == "sketch"
        back = await client.patch(
            f"{IDEAS}/{idea['id']}/entries/{sketch['id']}", json={"kind": "image"}
        )
        assert back.json()["kind"] == "image"

    async def test_image_served_to_members_and_viewers(self, client: AsyncClient, as_role):
        idea = await create_idea(client)
        entry = (await upload_images(client, idea["id"])).json()["created"][0]

        full = await client.get(entry["image_path"])
        assert full.status_code == 200
        assert full.headers["content-type"] == "image/jpeg"
        assert full.headers["cache-control"].startswith("private")
        thumb = await client.get(entry["thumbnail_path"])
        assert thumb.status_code == 200 and thumb.content != full.content
        cached = await client.get(
            entry["image_path"], headers={"If-None-Match": full.headers["etag"]}
        )
        assert cached.status_code == 304

        async with as_role(UserRole.VIEWER) as viewer:
            assert (await viewer.get(entry["image_path"])).status_code == 200

    async def test_image_refused_without_sign_in(
        self, client: AsyncClient, unauthenticated_client: AsyncClient
    ):
        idea = await create_idea(client)
        entry = (await upload_images(client, idea["id"])).json()["created"][0]
        with signed_out():
            response = await unauthenticated_client.get(entry["image_path"])
        assert response.status_code == 401

    async def test_idea_images_have_no_public_uploads_route(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        idea = await create_idea(client)
        entry = (await upload_images(client, idea["id"])).json()["created"][0]
        row = await db_session.get(IdeaEntry, uuid.UUID(entry["id"]))
        assert row.image_url.startswith(f"/uploads/ideas/{idea['id']}/")
        assert (await client.get(row.image_url)).status_code == 404

    async def test_missing_file_and_note_without_image_are_404(
        self, client: AsyncClient, db_session: AsyncSession, image_storage_fixture
    ):
        idea = await create_idea(client)
        entry = (await upload_images(client, idea["id"])).json()["created"][0]
        note = (
            await client.post(f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "a"})
        ).json()
        assert (
            await client.get(f"{IDEAS}/{idea['id']}/entries/{note['id']}/image")
        ).status_code == 404

        # The stored file is deleted by hand: the entry stays, its image is "not found".
        row = await db_session.get(IdeaEntry, uuid.UUID(entry["id"]))
        await image_storage_fixture.delete_image(row.image_url)
        assert (await client.get(entry["image_path"])).status_code == 404
        assert len((await _entries(client, idea["id"]))["items"]) == 2

    async def test_viewer_cannot_upload(self, client: AsyncClient, as_role):
        idea = await create_idea(client)
        async with as_role(UserRole.VIEWER) as viewer:
            assert (await upload_images(viewer, idea["id"])).status_code == 403


# ============================================
# Cover
# ============================================


class TestCover:
    async def test_set_cover_shows_on_card_and_archiving_clears_it(self, client: AsyncClient):
        idea = await create_idea(client)
        image = (await upload_images(client, idea["id"])).json()["created"][0]

        covered = await client.patch(f"{IDEAS}/{idea['id']}", json={"cover_entry_id": image["id"]})
        assert covered.status_code == 200
        assert covered.json()["cover_image_path"].endswith("variant=full")
        listed = (await client.get(IDEAS)).json()["items"][0]
        assert listed["cover_thumbnail_path"].endswith("variant=thumb")
        assert (await client.get(listed["cover_thumbnail_path"])).status_code == 200

        await client.delete(f"{IDEAS}/{idea['id']}/entries/{image['id']}")
        assert (await client.get(f"{IDEAS}/{idea['id']}")).json()["cover_entry_id"] is None

    async def test_no_cover_until_chosen(self, client: AsyncClient):
        idea = await create_idea(client)
        await upload_images(client, idea["id"])
        assert (await client.get(IDEAS)).json()["items"][0]["cover_thumbnail_path"] is None

    async def test_cover_must_be_an_image_of_this_idea(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ):
        idea = await create_idea(client)
        note = (
            await client.post(f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "a"})
        ).json()
        other = await idea_in(db_session, test_tenant)
        other_image = await entry_in(
            db_session, other, kind="image", body=None, image_url="/uploads/ideas/x/y.jpg"
        )
        for cover in (note["id"], str(other_image.id), str(uuid.uuid4())):
            response = await client.patch(f"{IDEAS}/{idea['id']}", json={"cover_entry_id": cover})
            assert response.status_code == 422

    async def test_clear_cover(self, client: AsyncClient):
        idea = await create_idea(client)
        image = (await upload_images(client, idea["id"])).json()["created"][0]
        await client.patch(f"{IDEAS}/{idea['id']}", json={"cover_entry_id": image["id"]})
        cleared = await client.patch(f"{IDEAS}/{idea['id']}", json={"cover_entry_id": None})
        assert cleared.json()["cover_entry_id"] is None


# ============================================
# Isolation and auth on every route
# ============================================


class TestIsolation:
    async def test_other_tenants_entries_are_not_found(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        foreign = await idea_in(db_session, await other_tenant(db_session))
        foreign_entry = await entry_in(
            db_session, foreign, kind="image", body=None, image_url="/uploads/ideas/x/y.jpg"
        )
        base = f"{IDEAS}/{foreign.id}"
        calls = [
            client.get(f"{base}/entries"),
            client.post(f"{base}/entries", json={"kind": "note", "body": "x"}),
            upload_images(client, str(foreign.id)),
            client.patch(f"{base}/entries/{foreign_entry.id}", json={"pinned": True}),
            client.delete(f"{base}/entries/{foreign_entry.id}"),
            client.get(f"{base}/entries/{foreign_entry.id}/image"),
            client.post(f"{base}/iterations", json={}),
        ]
        for call in calls:
            assert (await call).status_code == 404

    async def test_unknown_entry_of_own_idea(self, client: AsyncClient):
        idea = await create_idea(client)
        response = await client.patch(
            f"{IDEAS}/{idea['id']}/entries/{uuid.uuid4()}", json={"pinned": True}
        )
        assert response.status_code == 404

    async def test_viewer_cannot_write_entries(self, client: AsyncClient, as_role):
        idea = await create_idea(client)
        async with as_role(UserRole.VIEWER) as viewer:
            assert (
                await viewer.post(
                    f"{IDEAS}/{idea['id']}/entries", json={"kind": "note", "body": "x"}
                )
            ).status_code == 403
            assert (
                await viewer.post(f"{IDEAS}/{idea['id']}/iterations", json={})
            ).status_code == 403
            assert (await viewer.get(f"{IDEAS}/{idea['id']}/entries")).status_code == 200

    async def test_entries_require_authentication(
        self, unauthenticated_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ):
        idea = await idea_in(db_session, test_tenant)
        response = await unauthenticated_client.get(f"{IDEAS}/{idea.id}/entries")
        assert response.status_code == 401
