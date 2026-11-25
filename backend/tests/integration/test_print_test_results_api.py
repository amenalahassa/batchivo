"""Print test results (spec 009, User Story 4).

A result names the print job or the model version it tested, or both; a
critical-zone or full-part test names its version (clarification Q3). The
measurements are kept exactly as written; the photo is private to the shop.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.image_storage import MAX_FILE_SIZE
from app.models.model import Model
from app.models.print_job import JobPriority, JobStatus, PrintJob
from app.models.user import User, UserRole
from tests.api_token_helpers import bearer, make_token
from tests.fixtures.model_files import block_stl
from tests.integration.test_model_files_api_versions import upload
from tests.utils.ideas import jpeg_bytes, other_tenant, signed_out

RESULTS = "/api/v1/print-test-results"
MEASUREMENTS = [
    {"name": "load_kg", "value": 7, "unit": "kg", "expected": 5},
    {"name": "gap", "value": "0.15", "unit": "mm", "x_note": "peigne 3"},
]


@pytest.fixture(autouse=True)
def _storage(image_storage_fixture):
    return image_storage_fixture


async def _version(client: AsyncClient, model_id) -> dict:
    return (await upload(client, model_id, "hook.stl", block_stl(), "source_stl"))["file"]


async def _job(db: AsyncSession, tenant, model_id=None, printer_id=None) -> PrintJob:
    job = PrintJob(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        quantity=1,
        priority=JobPriority.NORMAL.value,
        status=JobStatus.PENDING.value,
        model_id=model_id,
        assigned_printer_id=printer_id,
    )
    db.add(job)
    await db.commit()
    return job


async def _record(client: AsyncClient, **body) -> dict:
    response = await client.post(RESULTS, json=body)
    assert response.status_code == 201, response.text
    return response.json()


class TestRecord:
    async def test_critical_zone_on_a_version(self, client: AsyncClient, test_model):
        file = await _version(client, test_model.id)
        body = await _record(
            client,
            kind="critical_zone",
            outcome="fail",
            model_file_version_id=file["version_id"],
            material="PLA",
            orientation="horizontal",
            measurements=MEASUREMENTS,
            failure_mode="rupture à l'encastrement à 7 kg",
        )
        assert body["model_id"] == str(test_model.id)
        assert body["model_name"] == test_model.name
        assert body["model_file_version_id"] == file["version_id"]
        assert body["material_code"] == "PLA"
        assert body["measurements"] == MEASUREMENTS
        assert body["failure_mode"] == "rupture à l'encastrement à 7 kg"
        assert body["photo_available"] is False
        assert body["recorded_by"]["name"] == "Test User"

    async def test_clearance_grid_on_a_job_takes_its_model_and_printer(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant, test_model, test_printer
    ):
        job = await _job(db_session, test_tenant, test_model.id, test_printer.id)
        body = await _record(
            client, kind="clearance_grid", outcome="pass", print_job_id=str(job.id)
        )
        assert body["model_id"] == str(test_model.id)
        assert body["printer_id"] == str(test_printer.id)
        assert body["measurements"] == []

    @pytest.mark.parametrize("kind", ["critical_zone", "full_part"])
    async def test_part_test_needs_a_version(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant, kind
    ):
        job = await _job(db_session, test_tenant)
        response = await client.post(
            RESULTS, json={"kind": kind, "outcome": "pass", "print_job_id": str(job.id)}
        )
        assert response.status_code == 422
        assert "version" in response.json()["detail"]

    async def test_needs_a_job_or_a_version(self, client: AsyncClient):
        response = await client.post(RESULTS, json={"kind": "clearance_grid", "outcome": "pass"})
        assert response.status_code == 422

    async def test_version_of_another_model_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant, test_model
    ):
        file = await _version(client, test_model.id)
        other = Model(id=uuid.uuid4(), tenant_id=test_tenant.id, sku="OTHER-1", name="Other model")
        db_session.add(other)
        await db_session.commit()
        response = await client.post(
            RESULTS,
            json={
                "kind": "full_part",
                "outcome": "pass",
                "model_file_version_id": file["version_id"],
                "model_id": str(other.id),
            },
        )
        assert response.status_code == 422
        job = await _job(db_session, test_tenant, other.id)
        response = await client.post(
            RESULTS,
            json={
                "kind": "full_part",
                "outcome": "pass",
                "model_file_version_id": file["version_id"],
                "print_job_id": str(job.id),
            },
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "bad",
        [
            {"kind": "smoke_test"},
            {"outcome": "meh"},
            {"orientation": "diagonal"},
            {"measurements": [{"name": f"m{i}", "value": i} for i in range(201)]},
            {"measurements": [{"blob": "x" * 70_000}]},
            {"failure_mode": "x" * 2001},
            {"material": "PLA", "material_type_id": str(uuid.uuid4())},
            {"material": "UNOBTAINIUM"},
        ],
    )
    async def test_bad_values_are_422(self, client: AsyncClient, test_model, bad):
        file = await _version(client, test_model.id)
        body = {"kind": "full_part", "outcome": "pass", "model_file_version_id": file["version_id"]}
        response = await client.post(RESULTS, json={**body, **bad})
        assert response.status_code == 422, response.text

    @pytest.mark.parametrize(
        "field", ["model_file_version_id", "print_job_id", "printer_id", "filament_type_id"]
    )
    async def test_unknown_ids_are_404(self, client: AsyncClient, test_model, field):
        file = await _version(client, test_model.id)
        body = {
            "kind": "clearance_grid",
            "outcome": "pass",
            "model_file_version_id": file["version_id"],
        }
        response = await client.post(RESULTS, json={**body, field: str(uuid.uuid4())})
        assert response.status_code == 404, field


class TestCorrectAndList:
    async def test_correct_outcome_and_measurements(self, client: AsyncClient, test_model):
        file = await _version(client, test_model.id)
        result = await _record(
            client, kind="full_part", outcome="partial", model_file_version_id=file["version_id"]
        )
        response = await client.patch(
            f"{RESULTS}/{result['id']}",
            json={"outcome": "pass", "measurements": MEASUREMENTS, "notes": "Re-mesuré"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["outcome"], body["measurements"], body["notes"]) == (
            "pass",
            MEASUREMENTS,
            "Re-mesuré",
        )
        assert body["updated_by"]["name"] == "Test User"
        assert (
            await client.patch(f"{RESULTS}/{result['id']}", json={"outcome": None})
        ).status_code == 422
        assert (
            await client.patch(f"{RESULTS}/{uuid.uuid4()}", json={"outcome": "pass"})
        ).status_code == 404

    async def test_list_filters_newest_first(self, client: AsyncClient, test_model):
        file = await _version(client, test_model.id)
        version = file["version_id"]
        first = await _record(
            client, kind="full_part", outcome="fail", model_file_version_id=version
        )
        second = await _record(
            client, kind="full_part", outcome="pass", model_file_version_id=version
        )
        everything = (await client.get(RESULTS, params={"model_id": str(test_model.id)})).json()
        assert everything["total"] == 2
        assert [r["id"] for r in everything["items"]] == [second["id"], first["id"]]
        passed = (await client.get(RESULTS, params={"outcome": "pass"})).json()
        assert [r["id"] for r in passed["items"]] == [second["id"]]
        paged = (await client.get(RESULTS, params={"limit": 1, "skip": 1})).json()
        assert paged["total"] == 2 and [r["id"] for r in paged["items"]] == [first["id"]]
        assert (await client.get(RESULTS, params={"outcome": "meh"})).status_code == 422


class TestPhoto:
    async def test_photo_upload_and_private_download(self, client: AsyncClient, test_model):
        file = await _version(client, test_model.id)
        result = await _record(
            client, kind="full_part", outcome="fail", model_file_version_id=file["version_id"]
        )
        response = await client.post(
            f"{RESULTS}/{result['id']}/photo",
            files={"file": ("break.jpg", jpeg_bytes(), "image/jpeg")},
        )
        assert response.status_code == 200, response.text
        assert response.json()["photo_available"] is True

        photo = await client.get(f"{RESULTS}/{result['id']}/photo")
        assert photo.status_code == 200
        assert photo.headers["cache-control"].startswith("private")
        assert photo.content[:2] == b"\xff\xd8"
        again = await client.get(
            f"{RESULTS}/{result['id']}/photo", headers={"If-None-Match": photo.headers["etag"]}
        )
        assert again.status_code == 304
        thumb = await client.get(f"{RESULTS}/{result['id']}/photo", params={"variant": "thumb"})
        assert thumb.status_code == 200

    async def test_not_an_image_is_refused(self, client: AsyncClient, test_model):
        file = await _version(client, test_model.id)
        result = await _record(
            client, kind="full_part", outcome="fail", model_file_version_id=file["version_id"]
        )
        response = await client.post(
            f"{RESULTS}/{result['id']}/photo",
            files={"file": ("notes.txt", b"not an image", "text/plain")},
        )
        assert response.status_code == 422
        assert (await client.get(f"{RESULTS}/{result['id']}/photo")).status_code == 404

    async def test_a_photo_over_the_size_limit_is_refused(self, client: AsyncClient, test_model):
        """Edge case: over the image size limit, refused and nothing stored (T065)."""
        file = await _version(client, test_model.id)
        result = await _record(
            client, kind="full_part", outcome="fail", model_file_version_id=file["version_id"]
        )
        too_big = bytes([0xFF, 0xD8, 0xFF]) + b"0" * (MAX_FILE_SIZE + 1)
        response = await client.post(
            f"{RESULTS}/{result['id']}/photo",
            files={"file": ("break.jpg", too_big, "image/jpeg")},
        )
        assert response.status_code == 422
        assert "too large" in response.text.lower()
        assert (await client.get(f"{RESULTS}/{result['id']}/photo")).status_code == 404
        assert (await client.get(f"{RESULTS}/{result['id']}")).json()["photo_available"] is False


class TestAccess:
    async def test_other_tenant_is_404(
        self, client: AsyncClient, db_session: AsyncSession, test_model
    ):
        file = await _version(client, test_model.id)
        result = await _record(
            client, kind="full_part", outcome="fail", model_file_version_id=file["version_id"]
        )
        theirs = await other_tenant(db_session)
        their_job = await _job(db_session, theirs)
        response = await client.post(
            RESULTS,
            json={"kind": "clearance_grid", "outcome": "pass", "print_job_id": str(their_job.id)},
        )
        assert response.status_code == 404

        from app.models.print_test_result import PrintTestResult

        row = await db_session.get(PrintTestResult, uuid.UUID(result["id"]))
        row.tenant_id = theirs.id
        await db_session.commit()
        assert (await client.get(f"{RESULTS}/{result['id']}")).status_code == 404
        assert (await client.get(RESULTS)).json()["total"] == 0

    async def test_signed_out_is_401(self, unauthenticated_client: AsyncClient):
        assert (await unauthenticated_client.get(RESULTS)).status_code == 401

    async def test_viewer_reads_but_does_not_record(self, client: AsyncClient, test_model, as_role):
        file = await _version(client, test_model.id)
        body = {"kind": "full_part", "outcome": "pass", "model_file_version_id": file["version_id"]}
        result = await _record(client, **body)
        async with as_role(UserRole.VIEWER) as viewer:
            assert (await viewer.get(f"{RESULTS}/{result['id']}")).status_code == 200
            assert (await viewer.post(RESULTS, json=body)).status_code == 403
            patched = await viewer.patch(f"{RESULTS}/{result['id']}", json={"outcome": "fail"})
            assert patched.status_code == 403

    async def test_tokens(
        self,
        client: AsyncClient,
        unauthenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_tenant,
        test_user: User,
        test_model,
    ):
        file = await _version(client, test_model.id)
        body = {"kind": "full_part", "outcome": "pass", "model_file_version_id": file["version_id"]}
        _, reader = await make_token(db_session, test_tenant, test_user, ["read"])
        _, writer = await make_token(db_session, test_tenant, test_user, ["read", "write"])
        with signed_out():  # `client` signed the shared overrides in
            refused = await unauthenticated_client.post(RESULTS, json=body, headers=bearer(reader))
            assert refused.status_code == 403
            recorded = await unauthenticated_client.post(RESULTS, json=body, headers=bearer(writer))
            assert recorded.status_code == 201, recorded.text
            listed = await unauthenticated_client.get(RESULTS, headers=bearer(reader))
            assert listed.json()["total"] == 1
