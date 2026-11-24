"""Ideas: create, read, update, archive, list (spec 007, User Story 1)."""

import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idea import Idea
from app.models.tenant import Tenant
from app.models.user import UserRole
from tests.utils.ideas import IDEAS, create_idea, idea_in, other_tenant

FULL_SCORES = {
    "frequency": 4,
    "frustration": 5,
    "printability": 3,
    "gap": 4,
    "willingness_to_pay": 2,
}


# ============================================
# Create
# ============================================


class TestCreateIdea:
    async def test_title_only_lands_in_inbox_unscored(self, client: AsyncClient):
        idea = await create_idea(client, title="  Sun visor clip  ")
        assert idea["title"] == "Sun visor clip"
        assert idea["status"] == "inbox"
        assert idea["source"] == "manual"
        assert idea["tags"] == []
        assert idea["score"] is None
        assert idea["score_source"] is None
        assert idea["current_iteration"] == 1
        assert idea["model"]["state"] == "none"
        assert idea["created_by"]["name"] == "Test User"

    async def test_five_scores_total_18(self, client: AsyncClient):
        idea = await create_idea(client, scores=FULL_SCORES)
        assert idea["score"] == 18
        assert idea["score_source"] == "scores"

    async def test_tags_are_trimmed_lowercased_and_deduplicated(self, client: AsyncClient):
        idea = await create_idea(client, tags=[" Car ", "car", "Sun  Visor"])
        assert idea["tags"] == ["car", "sun visor"]

    async def test_requires_authentication(self, unauthenticated_client: AsyncClient):
        response = await unauthenticated_client.post(IDEAS, json={"title": "x"})
        assert response.status_code == 401

    async def test_viewer_cannot_create(self, as_role):
        async with as_role(UserRole.VIEWER) as viewer:
            response = await viewer.post(IDEAS, json={"title": "x"})
        assert response.status_code == 403

    async def test_member_can_create(self, as_role):
        async with as_role(UserRole.MEMBER) as member:
            response = await member.post(IDEAS, json={"title": "x"})
        assert response.status_code == 201

    @pytest.mark.parametrize(
        "body, field",
        [
            ({"title": "   "}, "title"),
            ({"title": "x" * 201}, "title"),
            ({"title": "x", "scores": {"gap": 0}}, "gap"),
            ({"title": "x", "scores": {"frequency": 6}}, "frequency"),
            ({"title": "x", "source_url": "ftp://example.org/x"}, "source_url"),
            ({"title": "x", "source_url": "example.org"}, "source_url"),
            ({"title": "x", "status": "converted"}, "status"),
            ({"title": "x", "report_score": 26}, "report_score"),
            ({"title": "x", "source": "rumour"}, "source"),
        ],
    )
    async def test_validation(self, client: AsyncClient, body, field):
        response = await client.post(IDEAS, json=body)
        assert response.status_code == 422
        assert field in response.text


# ============================================
# Read, update, archive
# ============================================


class TestReadUpdateArchive:
    async def test_get_and_404s(self, client: AsyncClient, db_session: AsyncSession):
        idea = await create_idea(client)
        assert (await client.get(f"{IDEAS}/{idea['id']}")).status_code == 200
        assert (await client.get(f"{IDEAS}/{uuid.uuid4()}")).status_code == 404

        foreign = await idea_in(db_session, await other_tenant(db_session))
        for call in (
            client.get(f"{IDEAS}/{foreign.id}"),
            client.patch(f"{IDEAS}/{foreign.id}", json={"title": "mine now"}),
            client.delete(f"{IDEAS}/{foreign.id}"),
        ):
            assert (await call).status_code == 404

    async def test_get_requires_authentication(
        self, unauthenticated_client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ):
        idea = await idea_in(db_session, test_tenant)
        assert (await unauthenticated_client.get(f"{IDEAS}/{idea.id}")).status_code == 401

    async def test_viewer_reads_but_cannot_write(self, as_role, db_session, test_tenant):
        idea = await idea_in(db_session, test_tenant)
        async with as_role(UserRole.VIEWER) as viewer:
            assert (await viewer.get(f"{IDEAS}/{idea.id}")).status_code == 200
            assert (await viewer.get(IDEAS)).status_code == 200
            assert (
                await viewer.patch(f"{IDEAS}/{idea.id}", json={"title": "y"})
            ).status_code == 403
            assert (await viewer.delete(f"{IDEAS}/{idea.id}")).status_code == 403

    async def test_patch_moves_status_and_bumps_updated_at(self, client: AsyncClient):
        idea = await create_idea(client)
        time.sleep(0.01)
        response = await client.patch(
            f"{IDEAS}/{idea['id']}",
            json={"status": "exploring", "summary": "**clip** on", "tags": ["Car"]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "exploring"
        assert body["summary"] == "**clip** on"
        assert body["tags"] == ["car"]
        assert body["updated_at"] > idea["updated_at"]

    async def test_patch_refuses_converted(self, client: AsyncClient):
        idea = await create_idea(client)
        response = await client.patch(f"{IDEAS}/{idea['id']}", json={"status": "converted"})
        assert response.status_code == 422

    async def test_report_score_until_all_five_are_set(self, client: AsyncClient):
        idea = await create_idea(client, report_score=20, scores={"gap": 3})
        assert (idea["score"], idea["score_source"]) == (20, "report")

        response = await client.patch(
            f"{IDEAS}/{idea['id']}",
            json={
                "scores": {
                    "frequency": 3,
                    "frustration": 3,
                    "printability": 4,
                    "gap": 3,
                    "willingness_to_pay": 4,
                }
            },
        )
        body = response.json()
        assert (body["score"], body["score_source"]) == (17, "scores")
        # The report's figure is kept as it was given (FR-004a).
        assert body["report_score"] == 20

    async def test_archive_hides_and_restore_shows(self, client: AsyncClient):
        idea = await create_idea(client)
        archived = await client.delete(f"{IDEAS}/{idea['id']}")
        assert archived.status_code == 200 and archived.json()["archived"] is True

        assert (await client.get(IDEAS)).json()["total"] == 0
        listed = (await client.get(IDEAS, params={"archived": "true"})).json()
        assert [i["id"] for i in listed["items"]] == [idea["id"]]

        restored = await client.patch(f"{IDEAS}/{idea['id']}", json={"archived": False})
        assert restored.json()["archived"] is False
        assert (await client.get(IDEAS)).json()["total"] == 1

    async def test_duplicate_report_link_is_a_conflict(self, client: AsyncClient):
        body = {
            "title": "x",
            "source": "pain_point_report",
            "source_url": "https://forum.example.org/1",
        }
        await create_idea(client, **body)
        response = await client.post(IDEAS, json=body)
        assert response.status_code == 409


# ============================================
# List
# ============================================


class TestListIdeas:
    async def test_search_filters_sort_and_pagination(self, client: AsyncClient):
        await create_idea(client, title="Sun visor clip", tags=["car"], scores=FULL_SCORES)
        await create_idea(
            client, title="Key turner", summary="for the VISOR too", source="customer"
        )
        await create_idea(client, title="Cable tidy", tags=["home"], report_score=22)
        await create_idea(client, title="Unscored thing", status="parked")

        search = (await client.get(IDEAS, params={"search": "visor"})).json()
        assert {i["title"] for i in search["items"]} == {"Sun visor clip", "Key turner"}

        by_tag = (await client.get(IDEAS, params={"tag": "car"})).json()
        assert [i["title"] for i in by_tag["items"]] == ["Sun visor clip"]

        by_source = (await client.get(IDEAS, params={"source": "customer"})).json()
        assert [i["title"] for i in by_source["items"]] == ["Key turner"]

        by_status = (await client.get(IDEAS, params={"status": ["parked", "ready"]})).json()
        assert [i["title"] for i in by_status["items"]] == ["Unscored thing"]

        by_score = (await client.get(IDEAS, params={"sort": "score"})).json()["items"]
        assert [i["title"] for i in by_score][:2] == ["Cable tidy", "Sun visor clip"]
        assert by_score[-1]["score"] is None

        page = (await client.get(IDEAS, params={"limit": 2, "skip": 2})).json()
        assert page["total"] == 4 and len(page["items"]) == 2
        assert (page["skip"], page["limit"]) == (2, 2)

    async def test_tags_endpoint(self, client: AsyncClient):
        await create_idea(client, tags=["car", "clip"])
        await create_idea(client, tags=["home"])
        assert (await client.get(f"{IDEAS}/tags")).json() == ["car", "clip", "home"]

    async def test_other_tenants_ideas_never_listed(self, client, db_session: AsyncSession):
        await idea_in(db_session, await other_tenant(db_session), tags=["car"])
        assert (await client.get(IDEAS)).json()["total"] == 0
        assert (await client.get(f"{IDEAS}/tags")).json() == []

    async def test_validation_of_list_params(self, client: AsyncClient):
        assert (await client.get(IDEAS, params={"limit": 101})).status_code == 422
        assert (await client.get(IDEAS, params={"sort": "random"})).status_code == 422

    async def test_list_requires_authentication(self, unauthenticated_client: AsyncClient):
        assert (await unauthenticated_client.get(IDEAS)).status_code == 401

    async def test_500_ideas_first_page_fast(
        self, client: AsyncClient, db_session: AsyncSession, test_tenant: Tenant
    ):
        """SC-002: never loads all ideas; first page and a filtered search under 2 s."""
        db_session.add_all(
            Idea(
                id=uuid.uuid4(),
                tenant_id=test_tenant.id,
                title=f"Idea {n}",
                summary="visor" if n % 50 == 0 else None,
                tags=["car"] if n % 2 else ["home"],
                report_score=n % 26,
            )
            for n in range(500)
        )
        await db_session.commit()

        started = time.perf_counter()
        first = (await client.get(IDEAS, params={"sort": "score"})).json()
        filtered = (await client.get(IDEAS, params={"search": "visor", "tag": "home"})).json()
        elapsed = time.perf_counter() - started

        assert first["total"] == 500 and len(first["items"]) == 20
        assert first["items"][0]["score"] == 25
        assert filtered["total"] == 10
        assert elapsed < 2.0
