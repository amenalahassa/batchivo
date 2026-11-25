"""Typed notes: Preflight findings pinned on a model file (spec 009, User Story 2).

Typing is additive: a note written without type fields reads as a person's
note at "info" severity, exactly as before (FR-008). A note can be dismissed
with a written reason, then reopened (clarification Q2).
"""

import pytest

from app.models.user import UserRole
from tests.fixtures.model_files import block_stl
from tests.integration.test_model_files_api_versions import upload

API = "/api/v1/models"
PIN = {"position": [12.5, 3.0, 40.2], "normal": [0, 0, 1], "text": "Paroi trop fine"}
FINDING = {
    "source": "preflight",
    "rule_id": "dfam.wall.extrusion-multiple",
    "severity": "failure",
    "measured_value": "0.6",
    "expected_value": "0.9",
    "value_unit": "mm",
}


async def _two_files(client, model_id) -> tuple[dict, dict]:
    v1 = await upload(client, model_id, "v1.stl", block_stl(), "source_stl")
    v2 = await upload(client, model_id, "v2.stl", block_stl(), "source_stl", new_version_label="2")
    return v1["file"], v2["file"]


async def _pin(client, model_id, file_id, **fields) -> dict:
    response = await client.post(f"{API}/{model_id}/files/{file_id}/notes", json={**PIN, **fields})
    assert response.status_code == 201, response.text
    return response.json()


async def _notes(client, model_id, **params) -> list[dict]:
    response = await client.get(f"{API}/{model_id}/file-notes", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def _patch(client, model_id, note_id, **body):
    return await client.patch(f"{API}/{model_id}/file-notes/{note_id}", json=body)


class TestTyping:
    async def test_untyped_note_reads_as_before(self, client, test_model):
        f1, _ = await _two_files(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"])
        assert (note["source"], note["severity"]) == ("person", "info")
        for field in ("rule_id", "measured_value", "expected_value", "value_unit"):
            assert note[field] is None
        assert note["dismissal_reason"] is None

    async def test_a_finding_keeps_its_type(self, client, test_model):
        f1, _ = await _two_files(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"], **FINDING)
        assert {k: note[k] for k in FINDING} == FINDING

    @pytest.mark.parametrize(
        "given,stored", [("attention", "warning"), ("échec", "failure"), ("echec", "failure")]
    )
    async def test_preflight_severity_words_are_accepted(self, client, test_model, given, stored):
        f1, _ = await _two_files(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"], source="preflight", severity=given)
        assert note["severity"] == stored

    @pytest.mark.parametrize(
        "bad",
        [
            {"severity": "catastrophe"},
            {"source": "robot"},
            {"rule_id": "x" * 101},
            {"value_unit": "x" * 21},
            {"measured_value": "thin"},
        ],
    )
    async def test_bad_types_are_422(self, client, test_model, bad):
        f1, _ = await _two_files(client, test_model.id)
        response = await client.post(
            f"{API}/{test_model.id}/files/{f1['id']}/notes", json={**PIN, **bad}
        )
        assert response.status_code == 422

    async def test_type_fields_can_be_corrected_but_not_blanked(self, client, test_model):
        f1, _ = await _two_files(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"], **FINDING)
        response = await _patch(
            client, test_model.id, note["id"], severity="warning", measured_value=None
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["severity"], body["measured_value"]) == ("warning", None)
        assert body["rule_id"] == FINDING["rule_id"]
        cleared = await _patch(client, test_model.id, note["id"], source=None, severity=None)
        assert cleared.status_code == 200, cleared.text
        assert (cleared.json()["source"], cleared.json()["severity"]) == ("preflight", "warning")

    async def test_filters_by_source_and_severity(self, client, test_model):
        f1, _ = await _two_files(client, test_model.id)
        await _pin(client, test_model.id, f1["id"], text="mine")
        await _pin(client, test_model.id, f1["id"], text="fail", **FINDING)
        await _pin(
            client, test_model.id, f1["id"], text="warn", source="preflight", severity="warning"
        )
        preflight = await _notes(client, test_model.id, source="preflight")
        assert sorted(n["text"] for n in preflight) == ["fail", "warn"]
        failures = await _notes(client, test_model.id, severity="failure")
        assert [n["text"] for n in failures] == ["fail"]
        bad = await client.get(f"{API}/{test_model.id}/file-notes", params={"source": "robot"})
        assert bad.status_code == 422

    async def test_filters_apply_to_ghosts(self, client, test_model):
        f1, f2 = await _two_files(client, test_model.id)
        await _pin(client, test_model.id, f1["id"], text="old person note")
        await _pin(client, test_model.id, f1["id"], text="old finding", **FINDING)
        shown = await _notes(client, test_model.id, ghosts_for_file_id=f2["id"], source="preflight")
        assert [(n["text"], n["ghost"]) for n in shown] == [("old finding", True)]

    async def test_carry_forward_keeps_the_type(self, client, test_model):
        f1, f2 = await _two_files(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"], **FINDING)
        response = await client.post(
            f"{API}/{test_model.id}/file-notes/{note['id']}/carry-forward",
            json={"target_file_id": f2["id"]},
        )
        assert response.status_code == 201, response.text
        assert {k: response.json()[k] for k in FINDING} == FINDING


class TestDismiss:
    async def test_dismiss_needs_a_reason_then_reopen_keeps_it(self, client, test_model):
        f1, _ = await _two_files(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"], **FINDING)

        missing = await _patch(client, test_model.id, note["id"], status="dismissed")
        assert missing.status_code == 422
        blank = await _patch(
            client, test_model.id, note["id"], status="dismissed", dismissal_reason="  "
        )
        assert blank.status_code == 422

        dismissed = await _patch(
            client,
            test_model.id,
            note["id"],
            status="dismissed",
            dismissal_reason="Cosmetic face, no load",
        )
        assert dismissed.status_code == 200, dismissed.text
        body = dismissed.json()
        assert body["status"] == "dismissed"
        assert body["dismissal_reason"] == "Cosmetic face, no load"
        assert body["dismissed_at"] is not None
        assert body["dismissed_by"]["name"] == "Test User"
        assert [n["id"] for n in await _notes(client, test_model.id, status="dismissed")] == [
            note["id"]
        ]

        again = await _patch(
            client, test_model.id, note["id"], status="dismissed", dismissal_reason="again"
        )
        assert again.status_code == 409
        resolve = await _patch(
            client,
            test_model.id,
            note["id"],
            status="resolved",
            resolved_in_version_id=f1["version_id"],
        )
        assert resolve.status_code == 409

        reopened = await _patch(client, test_model.id, note["id"], status="open")
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "open"
        assert reopened.json()["dismissal_reason"] == "Cosmetic face, no load"

    async def test_only_an_open_note_is_dismissed(self, client, test_model):
        f1, _ = await _two_files(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"])
        await _patch(
            client,
            test_model.id,
            note["id"],
            status="resolved",
            resolved_in_version_id=f1["version_id"],
        )
        response = await _patch(
            client, test_model.id, note["id"], status="dismissed", dismissal_reason="why"
        )
        assert response.status_code == 409

    async def test_a_dismissed_note_does_not_ghost(self, client, test_model):
        f1, f2 = await _two_files(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"], **FINDING)
        await _patch(
            client, test_model.id, note["id"], status="dismissed", dismissal_reason="accepted"
        )
        assert await _notes(client, test_model.id, ghosts_for_file_id=f2["id"]) == []

    async def test_viewer_cannot_dismiss(self, client, test_model, as_role):
        f1, _ = await _two_files(client, test_model.id)
        note = await _pin(client, test_model.id, f1["id"], **FINDING)
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.patch(
                f"{API}/{test_model.id}/file-notes/{note['id']}",
                json={"status": "dismissed", "dismissal_reason": "no"},
            )
        assert response.status_code == 403
