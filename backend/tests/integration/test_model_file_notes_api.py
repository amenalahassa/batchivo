"""Pinned notes and how they travel between versions (T044, T045; FR-025 to FR-030).

A carried note is a new note on the newer version, linked to the original; the
original keeps its place and text and reads "carried forward" (clarification Q2).
"""

from uuid import uuid4

import pytest

from app.models.user import UserRole
from tests.fixtures.model_files import block_stl, plain_gcode
from tests.integration.test_model_files_api_versions import upload

API = "/api/v1/models"
PIN = {"position": [12.5, 3.0, 40.2], "normal": [0, 0, 1], "text": "overhang sags here"}


async def _v1_and_v2(client, model_id) -> tuple[dict, dict]:
    v1 = await upload(client, model_id, "v1.stl", block_stl(), "source_stl")
    v2 = await upload(client, model_id, "v2.stl", block_stl(), "source_stl", new_version_label="2")
    return v1["file"], v2["file"]


async def _pin(client, model_id, file_id, **overrides) -> dict:
    response = await client.post(
        f"{API}/{model_id}/files/{file_id}/notes", json={**PIN, **overrides}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _notes(client, model_id, **params) -> list[dict]:
    response = await client.get(f"{API}/{model_id}/file-notes", params=params)
    assert response.status_code == 200, response.text
    return response.json()


class TestPinning:
    async def test_pins_are_numbered_per_file_and_name_their_author(self, client, test_model):
        f1, _ = await _v1_and_v2(client, test_model.id)
        first = await _pin(client, test_model.id, f1["id"])
        second = await _pin(client, test_model.id, f1["id"], text="seam")
        assert (first["number"], second["number"]) == (1, 2)
        assert first["position"] == [12.5, 3.0, 40.2]
        assert first["status"] == "open"
        assert first["author"]["name"]
        assert first["version_id"] == f1["version_id"]

    async def test_a_note_on_a_sliced_file_keeps_its_layer(self, client, test_model):
        g = await upload(client, test_model.id, "p.gcode", plain_gcode(), "gcode")
        note = await _pin(client, test_model.id, g["file"]["id"], layer=87)
        assert note["layer"] == 87

    @pytest.mark.parametrize(
        "bad",
        [
            {"normal": [0, 0, 2]},
            {"text": ""},
            {"text": "x" * 2001},
            {"layer": -1},
            {"position": [1, 2]},
        ],
    )
    async def test_bad_pins_are_422(self, client, test_model, bad):
        f1, _ = await _v1_and_v2(client, test_model.id)
        response = await client.post(
            f"{API}/{test_model.id}/files/{f1['id']}/notes", json={**PIN, **bad}
        )
        assert response.status_code == 422

    async def test_unknown_file_is_404(self, client, test_model):
        response = await client.post(f"{API}/{test_model.id}/files/{uuid4()}/notes", json=PIN)
        assert response.status_code == 404


class TestAcrossVersions:
    async def test_earlier_open_notes_show_as_ghosts_on_a_newer_file(self, client, test_model):
        f1, f2 = await _v1_and_v2(client, test_model.id)
        await _pin(client, test_model.id, f1["id"])
        resolved = await _pin(client, test_model.id, f1["id"], text="already fixed")
        await client.patch(
            f"{API}/{test_model.id}/file-notes/{resolved['id']}",
            json={"status": "resolved", "resolved_in_version_id": f1["version_id"]},
        )
        own = await _pin(client, test_model.id, f2["id"], text="new issue")
        shown = await _notes(client, test_model.id, ghosts_for_file_id=f2["id"])
        assert [(n["text"], n["ghost"]) for n in shown] == [
            ("new issue", False),
            ("overhang sags here", True),
        ]
        assert own["number"] == 1
        # Viewing version 1 shows no ghosts: nothing is older.
        older = await _notes(client, test_model.id, ghosts_for_file_id=f1["id"])
        assert all(not n["ghost"] for n in older)

    async def test_resolve_in_this_version(self, client, test_model):
        f1, f2 = await _v1_and_v2(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"])
        response = await client.patch(
            f"{API}/{test_model.id}/file-notes/{note['id']}",
            json={"status": "resolved", "resolved_in_version_id": f2["version_id"]},
        )
        assert response.status_code == 200
        assert response.json()["resolved_in_version_id"] == f2["version_id"]
        assert await _notes(client, test_model.id, ghosts_for_file_id=f2["id"]) == []

    async def test_resolving_needs_a_version_not_older_than_the_note(self, client, test_model):
        f1, f2 = await _v1_and_v2(client, test_model.id)
        note = await _pin(client, test_model.id, f2["id"])
        missing = await client.patch(
            f"{API}/{test_model.id}/file-notes/{note['id']}", json={"status": "resolved"}
        )
        assert missing.status_code == 422
        older = await client.patch(
            f"{API}/{test_model.id}/file-notes/{note['id']}",
            json={"status": "resolved", "resolved_in_version_id": f1["version_id"]},
        )
        assert older.status_code == 422

    async def test_carry_forward_makes_a_linked_note_and_leaves_the_original(
        self, client, test_model
    ):
        f1, f2 = await _v1_and_v2(client, test_model.id)
        original = await _pin(client, test_model.id, f1["id"], layer=3)
        response = await client.post(
            f"{API}/{test_model.id}/file-notes/{original['id']}/carry-forward",
            json={"target_file_id": f2["id"]},
        )
        assert response.status_code == 201, response.text
        carried = response.json()
        assert carried["carried_from_note_id"] == original["id"]
        assert carried["version_id"] == f2["version_id"]
        assert (carried["text"], carried["position"], carried["layer"], carried["status"]) == (
            original["text"],
            original["position"],
            3,
            "open",
        )
        before = {n["id"]: n for n in await _notes(client, test_model.id, file_id=f1["id"])}
        kept = before[original["id"]]
        assert kept["status"] == "carried_forward"
        assert kept["carried_to_version_id"] == f2["version_id"]
        assert kept["position"] == original["position"]

        # The carried note can be moved onto the reshaped part; the original cannot change.
        moved = await client.patch(
            f"{API}/{test_model.id}/file-notes/{carried['id']}",
            json={"position": [13.0, 3.0, 41.0]},
        )
        assert moved.json()["position"] == [13.0, 3.0, 41.0]
        frozen = await client.patch(
            f"{API}/{test_model.id}/file-notes/{original['id']}", json={"text": "edit"}
        )
        assert frozen.status_code == 409
        assert frozen.json()["detail"]["code"] == "note_carried_forward"

    async def test_carry_forward_only_to_a_newer_version_and_only_when_open(
        self, client, test_model
    ):
        f1, f2 = await _v1_and_v2(client, test_model.id)
        newer_note = await _pin(client, test_model.id, f2["id"])
        backwards = await client.post(
            f"{API}/{test_model.id}/file-notes/{newer_note['id']}/carry-forward",
            json={"target_file_id": f1["id"]},
        )
        assert backwards.status_code == 422
        note = await _pin(client, test_model.id, f1["id"])
        await client.post(
            f"{API}/{test_model.id}/file-notes/{note['id']}/carry-forward",
            json={"target_file_id": f2["id"]},
        )
        twice = await client.post(
            f"{API}/{test_model.id}/file-notes/{note['id']}/carry-forward",
            json={"target_file_id": f2["id"]},
        )
        assert twice.status_code == 409

    async def test_filter_by_status(self, client, test_model):
        f1, f2 = await _v1_and_v2(client, test_model.id)
        a = await _pin(client, test_model.id, f1["id"])
        await _pin(client, test_model.id, f1["id"], text="b")
        await client.patch(
            f"{API}/{test_model.id}/file-notes/{a['id']}",
            json={"status": "resolved", "resolved_in_version_id": f2["version_id"]},
        )
        assert [n["text"] for n in await _notes(client, test_model.id, status="open")] == ["b"]


class TestAccess:
    async def test_unauthenticated_is_401(self, unauthenticated_client, test_model):
        response = await unauthenticated_client.get(f"{API}/{test_model.id}/file-notes")
        assert response.status_code == 401

    async def test_another_tenants_model_is_404(self, client):
        assert (await client.get(f"{API}/{uuid4()}/file-notes")).status_code == 404

    async def test_unknown_note_is_404(self, client, test_model):
        response = await client.patch(
            f"{API}/{test_model.id}/file-notes/{uuid4()}", json={"text": "x"}
        )
        assert response.status_code == 404

    async def test_a_viewer_reads_notes_but_cannot_write_them(self, as_role, test_model):
        async with as_role(UserRole.MEMBER) as member:
            f1 = (await upload(member, test_model.id, "a.stl", block_stl(), "source_stl"))["file"]
            note = await _pin(member, test_model.id, f1["id"])
        async with as_role(UserRole.VIEWER) as viewer:
            assert len(await _notes(viewer, test_model.id)) == 1
            created = await viewer.post(f"{API}/{test_model.id}/files/{f1['id']}/notes", json=PIN)
            edited = await viewer.patch(
                f"{API}/{test_model.id}/file-notes/{note['id']}", json={"text": "x"}
            )
            carried = await viewer.post(
                f"{API}/{test_model.id}/file-notes/{note['id']}/carry-forward",
                json={"target_file_id": f1["id"]},
            )
        assert (created.status_code, edited.status_code, carried.status_code) == (403, 403, 403)
