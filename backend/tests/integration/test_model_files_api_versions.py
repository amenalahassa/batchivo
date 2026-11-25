"""Model files in versions: compatibility, measuring source files, delete rules.

Covers T014 (existing clients keep working, FR-017, FR-031), T016 (a source
file is measured and a sliced plate says why it cannot be, FR-002 to FR-006)
and T023 (what may not be deleted, FR-015, research D9).
"""

from decimal import Decimal
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.model_file_note import ModelFileNote
from app.models.model_file_version import ModelFileVersion
from tests.fixtures.model_files import block_stl, plain_gcode, sliced_3mf

API = "/api/v1/models"


async def upload(client: AsyncClient, model_id, name: str, content: bytes, file_type: str, **form):
    data = {"file_type": file_type, **{k: str(v) for k, v in form.items()}}
    response = await client.post(
        f"{API}/{model_id}/files",
        files={"file": (name, content, "application/octet-stream")},
        data=data,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def versions(client: AsyncClient, model_id) -> list[dict]:
    response = await client.get(f"{API}/{model_id}/file-versions")
    assert response.status_code == 200, response.text
    return response.json()


# ============================================================================
# T014 - compatibility
# ============================================================================


class TestCompatibility:
    async def test_a_legacy_upload_lands_in_an_active_version_one(self, client, test_model):
        body = await upload(client, test_model.id, "part.stl", block_stl(), "source_stl")
        assert body["message"].startswith("File 'part.stl'")
        assert body["file"]["version"] == "1"
        assert body["file"]["version_id"] is not None
        assert body["version_created"] is True
        listed = await versions(client, test_model.id)
        assert [(v["label"], v["is_active"]) for v in listed] == [("1", True)]

    async def test_a_second_legacy_upload_joins_the_active_version(self, client, test_model):
        first = await upload(client, test_model.id, "part.stl", block_stl(), "source_stl")
        second = await upload(client, test_model.id, "plate.gcode", plain_gcode(), "gcode")
        assert second["file"]["version_id"] == first["file"]["version_id"]
        assert second["version_created"] is False

    async def test_a_legacy_version_text_names_a_version(self, client, test_model):
        await upload(client, test_model.id, "part.stl", block_stl(), "source_stl")
        body = await upload(
            client, test_model.id, "part_v2.stl", block_stl(), "source_stl", version="v2"
        )
        assert body["version_created"] is True
        listed = await versions(client, test_model.id)
        assert [(v["label"], v["is_active"]) for v in listed] == [("v2", False), ("1", True)]

    async def test_list_and_get_carry_the_new_fields(self, client, test_model):
        body = await upload(client, test_model.id, "plate.gcode", plain_gcode(), "gcode")
        listed = (await client.get(f"{API}/{test_model.id}/files")).json()["files"]
        assert listed[0]["is_sliced"] is True
        got = (await client.get(f"{API}/{test_model.id}/files/{body['file']['id']}")).json()
        assert got["version_id"] == body["file"]["version_id"]

    async def test_unknown_version_is_404(self, client, test_model):
        response = await client.post(
            f"{API}/{test_model.id}/files",
            files={"file": ("part.stl", block_stl(), "model/stl")},
            data={"file_type": "source_stl", "version_id": "00000000-0000-0000-0000-000000000009"},
        )
        assert response.status_code == 404

    async def test_unauthenticated_is_401(self, unauthenticated_client, test_model):
        response = await unauthenticated_client.get(f"{API}/{test_model.id}/files")
        assert response.status_code == 401


# ============================================================================
# T016 - measurable source file, and the sliced plate that is not
# ============================================================================


class TestMeasuringOnUpload:
    async def test_an_stl_gives_a_model_without_dimensions_its_size(
        self, client, test_model, db_session
    ):
        body = await upload(client, test_model.id, "block.stl", block_stl(), "source_stl")
        assert body["measurement"]["status"] == "done"
        assert "model" in body["measurement"]["applied_to"]
        await db_session.refresh(test_model)
        assert (test_model.length_mm, test_model.width_mm, test_model.height_mm) == (
            Decimal("40.0"),
            Decimal("30.0"),
            Decimal("20.0"),
        )
        assert test_model.dimensions_source == "measured"
        assert str(test_model.dimensions_source_file_id) == body["file"]["id"]

    async def test_entered_dimensions_are_kept_and_the_measurement_offered(
        self, client, test_model, db_session
    ):
        test_model.length_mm, test_model.width_mm, test_model.height_mm = (
            Decimal("10.0"),
            Decimal("10.0"),
            Decimal("10.0"),
        )
        test_model.dimensions_source = "entered"
        await db_session.commit()
        body = await upload(client, test_model.id, "block.stl", block_stl(), "source_stl")
        assert body["measurement"]["applied_to"] == []
        assert body["measurement"]["length_mm"] == "40.0"
        await db_session.refresh(test_model)
        assert test_model.length_mm == Decimal("10.0")

    async def test_a_sliced_plate_is_kept_and_says_why_it_cannot_be_measured(
        self, client, test_model
    ):
        body = await upload(
            client, test_model.id, "Lub Emptyer v4.gcode.3mf", sliced_3mf(), "source_3mf"
        )
        assert body["file"]["is_sliced"] is True
        assert body["measurement"]["status"] == "failed"
        assert body["measurement"]["reason"] == "no_geometry"


# ============================================================================
# T023 - delete rules
# ============================================================================


class TestDeleteRules:
    async def test_the_last_file_of_the_active_version_cannot_go(self, client, test_model):
        body = await upload(client, test_model.id, "part.stl", block_stl(), "source_stl")
        response = await client.delete(f"{API}/{test_model.id}/files/{body['file']['id']}")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "last_file_of_active_version"

    async def test_the_active_print_file_cannot_go_while_another_sliced_file_exists(
        self, client, test_model
    ):
        first = await upload(client, test_model.id, "a.gcode", plain_gcode(), "gcode")
        await upload(client, test_model.id, "b.gcode", plain_gcode(), "gcode")
        response = await client.delete(f"{API}/{test_model.id}/files/{first['file']['id']}")
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "active_print_file"

    async def test_an_inactive_versions_print_file_passes_to_its_newest_sliced_file(
        self, client, test_model, db_session
    ):
        await upload(client, test_model.id, "v1.stl", block_stl(), "source_stl")
        a = await upload(
            client, test_model.id, "a.gcode", plain_gcode(), "gcode", new_version_label="2"
        )
        version_id = a["file"]["version_id"]
        b = await upload(
            client, test_model.id, "b.gcode", plain_gcode(), "gcode", version_id=version_id
        )
        response = await client.delete(f"{API}/{test_model.id}/files/{a['file']['id']}")
        assert response.status_code == 204
        version = await db_session.get(ModelFileVersion, UUID(version_id))
        await db_session.refresh(version)
        assert str(version.print_file_id) == b["file"]["id"]

    async def test_an_emptied_inactive_version_is_removed(self, client, test_model, db_session):
        await upload(client, test_model.id, "v1.stl", block_stl(), "source_stl")
        only = await upload(
            client, test_model.id, "v2.stl", block_stl(), "source_stl", new_version_label="2"
        )
        response = await client.delete(f"{API}/{test_model.id}/files/{only['file']['id']}")
        assert response.status_code == 204
        assert [v["label"] for v in await versions(client, test_model.id)] == ["1"]

    async def test_a_deleted_files_notes_are_archived_not_dropped(
        self, client, test_model, db_session
    ):
        await upload(client, test_model.id, "keep.stl", block_stl(), "source_stl")
        doomed = await upload(client, test_model.id, "doomed.stl", block_stl(), "source_stl")
        note = await client.post(
            f"{API}/{test_model.id}/files/{doomed['file']['id']}/notes",
            json={"position": [1, 2, 3], "normal": [0, 0, 1], "text": "thin wall"},
        )
        assert note.status_code == 201
        response = await client.delete(f"{API}/{test_model.id}/files/{doomed['file']['id']}")
        assert response.status_code == 204
        db_session.expire_all()
        kept = (
            await db_session.execute(
                select(ModelFileNote).where(ModelFileNote.id == UUID(note.json()["id"]))
            )
        ).scalar_one()
        assert kept.archived_at is not None
        assert kept.status == "open"


@pytest.fixture(autouse=True)
def _local_storage(tmp_path, monkeypatch):
    """Keep uploaded bytes in a temporary folder."""
    monkeypatch.setenv("STORAGE_TYPE", "local")
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
