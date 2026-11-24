"""Creating ideas in bulk from the pain-point report (spec 007, User Story 4)."""

from pathlib import Path

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserRole
from tests.utils.ideas import IDEAS, idea_in, other_tenant, signed_out

REPORT = Path(__file__).resolve().parents[1] / "fixtures" / "pain_point_report_sample.md"
IMPORT = f"{IDEAS}/import"


def _items(count: int, start: int = 0) -> list[dict]:
    return [
        {
            "title": f"Problem {n}",
            "summary": f"Product idea {n}",
            "report_score": 10 + n % 15,
            "tags": ["Car"],
            "source_url": f"https://forum.example.org/thread/{n}",
        }
        for n in range(start, start + count)
    ]


class TestImport:
    async def test_ten_created_then_ten_skipped(self, client: AsyncClient):
        first = await client.post(IMPORT, json={"items": _items(10)})
        assert first.status_code == 200
        body = first.json()
        assert (len(body["created"]), len(body["skipped"]), len(body["refused"])) == (10, 0, 0)

        ideas = (await client.get(IDEAS, params={"limit": 100})).json()["items"]
        assert len(ideas) == 10
        sample = next(i for i in ideas if i["title"] == "Problem 3")
        assert sample["status"] == "inbox"
        assert sample["source"] == "pain_point_report"
        assert sample["source_url"] == "https://forum.example.org/thread/3"
        assert (sample["score"], sample["score_source"], sample["tags"]) == (13, "report", ["car"])

        again = (await client.post(IMPORT, json={"items": _items(10)})).json()
        assert (len(again["created"]), len(again["skipped"])) == (0, 10)
        assert {s["title"] for s in again["skipped"]} == {f"Problem {n}" for n in range(10)}
        assert all(s["existing_idea_id"] for s in again["skipped"])

    async def test_archived_and_converted_ideas_still_count_as_imported(self, client: AsyncClient):
        await client.post(IMPORT, json={"items": _items(2)})
        ideas = (await client.get(IDEAS)).json()["items"]
        await client.delete(f"{IDEAS}/{ideas[0]['id']}")
        await client.post(f"{IDEAS}/{ideas[1]['id']}/convert", json={"target": "model"})

        body = (await client.post(IMPORT, json={"items": _items(10)})).json()
        assert (len(body["created"]), len(body["skipped"])) == (8, 2)

    async def test_invalid_items_refused_others_created(self, client: AsyncClient):
        items: list = _items(3)
        items[1] = {"title": "", "source_url": "https://x.example.org/1"}
        items.append({"title": "Too high", "report_score": 30})
        items.append("not an object")
        response = await client.post(IMPORT, json={"items": items})
        assert response.status_code == 422  # a non-object item is refused by the schema

        items.pop()
        body = (await client.post(IMPORT, json={"items": items})).json()
        assert len(body["created"]) == 2
        assert sorted(r["index"] for r in body["refused"]) == [1, 3]
        assert all(r["reason"] for r in body["refused"])

    async def test_duplicate_link_inside_one_payload(self, client: AsyncClient):
        items = _items(1) + _items(1)
        body = (await client.post(IMPORT, json={"items": items})).json()
        assert (len(body["created"]), len(body["skipped"])) == (1, 1)

    async def test_dry_run_writes_nothing(self, client: AsyncClient):
        body = (await client.post(IMPORT, json={"items": _items(4), "dry_run": True})).json()
        assert len(body["created"]) == 4 and all(c["id"] is None for c in body["created"])
        assert (await client.get(IDEAS)).json()["total"] == 0

    async def test_other_tenant_links_do_not_cause_skips(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        tenant = await other_tenant(db_session)
        await idea_in(
            db_session,
            tenant,
            source="pain_point_report",
            source_url="https://forum.example.org/thread/0",
        )
        body = (await client.post(IMPORT, json={"items": _items(1)})).json()
        assert len(body["created"]) == 1

    async def test_explicit_scores_are_kept(self, client: AsyncClient):
        item = {
            "title": "Scored",
            "scores": {
                "frequency": 5,
                "frustration": 5,
                "printability": 5,
                "gap": 5,
                "willingness_to_pay": 5,
            },
        }
        await client.post(IMPORT, json={"items": [item]})
        idea = (await client.get(IDEAS)).json()["items"][0]
        assert (idea["score"], idea["score_source"]) == (25, "scores")

    async def test_validation_and_access(
        self, client: AsyncClient, unauthenticated_client: AsyncClient, as_role
    ):
        assert (await client.post(IMPORT, json={"items": []})).status_code == 422
        assert (await client.post(IMPORT, json={"items": _items(201)})).status_code == 422
        with signed_out():
            anonymous = await unauthenticated_client.post(IMPORT, json={"items": _items(1)})
        assert anonymous.status_code == 401
        async with as_role(UserRole.VIEWER) as viewer:
            assert (await viewer.post(IMPORT, json={"items": _items(1)})).status_code == 403


class TestParseReport:
    async def test_report_file_becomes_items(self, client: AsyncClient):
        response = await client.post(
            f"{IMPORT}/parse-report", json={"text": REPORT.read_text(encoding="utf-8")}
        )
        assert response.status_code == 200
        body = response.json()
        assert [i["report_score"] for i in body["items"]] == [20, 19, 18, 15]
        assert body["items"][0]["source_url"] == "https://forum-a.example.org/thread/1"
        assert body["warnings"] == []

        # The preview's next step: classify, then import.
        preview = await client.post(IMPORT, json={"items": body["items"], "dry_run": True})
        assert len(preview.json()["created"]) == 4
        done = (await client.post(IMPORT, json={"items": body["items"]})).json()
        assert len(done["created"]) == 4
        again = (await client.post(IMPORT, json={"items": body["items"]})).json()
        assert len(again["skipped"]) == 4

    async def test_text_without_problems(self, client: AsyncClient):
        body = (
            await client.post(f"{IMPORT}/parse-report", json={"text": "# Notes\nnothing here"})
        ).json()
        assert body["items"] == [] and body["warnings"]

    async def test_validation_and_access(
        self, client: AsyncClient, unauthenticated_client: AsyncClient, as_role
    ):
        url = f"{IMPORT}/parse-report"
        assert (await client.post(url, json={"text": ""})).status_code == 422
        with signed_out():
            assert (await unauthenticated_client.post(url, json={"text": "x"})).status_code == 401
        async with as_role(UserRole.VIEWER) as viewer:
            assert (await viewer.post(url, json={"text": "x"})).status_code == 403
