"""Design brief API (spec 009, User Story 1 and the token rows of User Story 6)."""

import uuid

import pytest
import yaml
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.design_brief import DesignBrief, DesignBriefRevision
from app.models.model import Model
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from tests.api_token_helpers import bearer, jwt_headers, make_token
from tests.fixtures.preflight import FILLED_INTENT, INTENT_TEMPLATE
from tests.utils.ideas import IDEAS, create_idea, idea_in, other_tenant

BRIEFS = "/api/v1/design-briefs"
MODELS = "/api/v1/models"


@pytest.fixture(autouse=True)
def _storage(image_storage_fixture):
    return image_storage_fixture


async def _idea_brief(client: AsyncClient, **body) -> tuple[dict, dict]:
    idea = await create_idea(client, title="Porte-sac")
    response = await client.post(f"{IDEAS}/{idea['id']}/design-brief", json=body)
    assert response.status_code == 201, response.text
    return idea, response.json()


async def _revisions(db: AsyncSession, brief_id: str, part: str) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(DesignBriefRevision)
        .where(
            DesignBriefRevision.brief_id == uuid.UUID(brief_id),
            DesignBriefRevision.part == part,
        )
    )


# ============================================
# Start and read
# ============================================


class TestStartAndRead:
    async def test_start_on_idea_then_again_returns_the_same(self, client: AsyncClient):
        idea, brief = await _idea_brief(client)
        assert brief["idea_id"] == idea["id"] and brief["model_id"] is None
        assert brief["idea_title"] == "Porte-sac"
        assert [s["step"] for s in brief["steps"]][:3] == ["intent", "adopt", "clarify"]
        assert len(brief["steps"]) == 14
        assert {s["status"] for s in brief["steps"]} == {"not_started"}
        assert brief["revision_counts"] == {"intent": 0, "risk": 0, "plan": 0}

        again = await client.post(f"{IDEAS}/{idea['id']}/design-brief", json={})
        assert again.status_code == 200
        assert again.json()["id"] == brief["id"]

        shown = await client.get(f"{IDEAS}/{idea['id']}/design-brief")
        assert shown.status_code == 200 and shown.json()["id"] == brief["id"]
        by_id = await client.get(f"{BRIEFS}/{brief['id']}")
        assert by_id.json()["id"] == brief["id"]

    async def test_idea_without_brief_is_404(self, client: AsyncClient):
        idea = await create_idea(client)
        response = await client.get(f"{IDEAS}/{idea['id']}/design-brief")
        assert response.status_code == 404
        assert response.json()["detail"] == "No design brief yet"

    async def test_start_on_model(self, client: AsyncClient, test_model):
        response = await client.post(
            f"{MODELS}/{test_model.id}/design-brief", json={"intent": FILLED_INTENT}
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["model_id"] == str(test_model.id) and body["idea_id"] is None
        assert body["model_name"] == test_model.name
        assert body["intent"] == FILLED_INTENT
        assert body["intent_schema_version"] == 1
        assert body["revision_counts"]["intent"] == 1
        shown = await client.get(f"{MODELS}/{test_model.id}/design-brief")
        assert shown.json()["id"] == body["id"]

    async def test_template_round_trips_without_loss(self, client: AsyncClient):
        """SC-001: the skill's own template comes back as `yaml.safe_load` reads it."""
        _, brief = await _idea_brief(client, intent_yaml=INTENT_TEMPLATE)
        expected = yaml.safe_load(INTENT_TEMPLATE)
        assert brief["intent"] == expected
        again = await client.get(f"{BRIEFS}/{brief['id']}")
        assert again.json()["intent"] == expected
        validation = brief["validation"]
        assert "slug" in validation["to_clarify"]
        assert "loads[0].direction" in validation["to_clarify"]
        assert {"field": "loads[0]", "status": "déduit"} in validation["unconfirmed"]
        assert {"field": "interfaces[0]", "status": "estimée"} in validation["unconfirmed"]
        assert validation["missing"] == []

    async def test_unknown_keys_are_kept(self, client: AsyncClient):
        _, brief = await _idea_brief(client, intent=FILLED_INTENT)
        assert brief["intent"]["x_custom"] == {"kept": True}


# ============================================
# Idea → model / product conversion (FR-004)
# ============================================


class TestConversionKeepsOneBrief:
    @pytest.mark.parametrize("target", ["model", "product"])
    async def test_converted_model_reaches_the_idea_brief(
        self, client: AsyncClient, db_session: AsyncSession, target: str
    ):
        idea, brief = await _idea_brief(client, intent=FILLED_INTENT)
        converted = await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": target})
        assert converted.status_code == 201, converted.text
        model_id = converted.json()["model_id"]

        shown = await client.get(f"{MODELS}/{model_id}/design-brief")
        assert shown.status_code == 200
        assert shown.json()["id"] == brief["id"]
        assert shown.json()["model_id"] is None  # reads never write

        started = await client.post(f"{MODELS}/{model_id}/design-brief", json={})
        assert started.status_code == 200
        assert started.json()["id"] == brief["id"]
        assert started.json()["model_id"] == model_id
        assert started.json()["idea_id"] == idea["id"]
        count = await db_session.scalar(select(func.count()).select_from(DesignBrief))
        assert count == 1

    async def test_brief_outlives_a_soft_deleted_model(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        idea, brief = await _idea_brief(client)
        model_id = (
            await client.post(f"{IDEAS}/{idea['id']}/convert", json={"target": "model"})
        ).json()["model_id"]
        await client.post(f"{MODELS}/{model_id}/design-brief", json={})
        model = await db_session.get(Model, uuid.UUID(model_id))
        await client.delete(f"{MODELS}/{model.id}")
        assert (await client.get(f"{BRIEFS}/{brief['id']}")).status_code == 200


# ============================================
# Update and revisions (clarification Q1)
# ============================================


class TestUpdate:
    async def test_each_changed_part_gets_one_revision(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, brief = await _idea_brief(client, intent=FILLED_INTENT)
        response = await client.patch(
            f"{BRIEFS}/{brief['id']}",
            json={
                "risk": {"risk_class": "moyen", "risk_md": "# Risque", "triage": {"score": 3}},
                "plan_md": "# Plan",
                "params_yaml": "wall_mm: 1.6\n",
                "steps": {"intent": "done", "risk": "in_progress"},
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert sorted(body["created_revisions"]) == ["plan", "risk"]
        assert (body["risk_class"], body["risk_md"], body["plan_md"]) == (
            "moyen",
            "# Risque",
            "# Plan",
        )
        assert body["triage"] == {"score": 3}
        assert body["params"] == {"wall_mm": 1.6}
        assert body["params_updated_at"] is not None
        steps = {s["step"]: s for s in body["steps"]}
        assert steps["intent"]["status"] == "done"
        assert steps["intent"]["updated_by"]["name"] == "Test User"
        assert steps["risk"]["status"] == "in_progress"
        assert body["revision_counts"] == {"intent": 1, "risk": 1, "plan": 1}

        same = await client.patch(
            f"{BRIEFS}/{brief['id']}", json={"plan_md": "# Plan", "intent": FILLED_INTENT}
        )
        assert same.json()["created_revisions"] == []
        assert await _revisions(db_session, brief["id"], "plan") == 1
        assert await _revisions(db_session, brief["id"], "intent") == 1

    async def test_revisions_newest_first_and_filtered(self, client: AsyncClient):
        _, brief = await _idea_brief(client)
        for text in ("# v1", "# v2"):
            await client.patch(f"{BRIEFS}/{brief['id']}", json={"plan_md": text})
        await client.patch(f"{BRIEFS}/{brief['id']}", json={"intent": FILLED_INTENT})

        plans = (await client.get(f"{BRIEFS}/{brief['id']}/revisions?part=plan")).json()
        assert [r["content"]["plan_md"] for r in plans] == ["# v2", "# v1"]
        assert plans[0]["author"]["name"] == "Test User"
        everything = (await client.get(f"{BRIEFS}/{brief['id']}/revisions")).json()
        assert len(everything) == 3
        intent = [r for r in everything if r["part"] == "intent"][0]
        assert intent["schema_version"] == 1 and intent["content"] == FILLED_INTENT

    @pytest.mark.parametrize(
        "body,where",
        [
            ({}, None),
            ({"intent": FILLED_INTENT, "intent_yaml": "schema_version: 1"}, None),
            ({"params": {"a": 1}, "params_yaml": "a: 1"}, None),
            ({"steps": {"teleport": "done"}}, "steps"),
            ({"steps": {"risk": "finished"}}, "steps"),
            ({"risk": {"risk_class": "énorme"}}, "risk"),
            ({"intent": {**FILLED_INTENT, "schema_version": 2}}, "schema_version"),
            (
                {"intent": {**FILLED_INTENT, "loads": [{"duration": "forever"}]}},
                "duration",
            ),
            ({"intent_yaml": "- just\n- a list\n"}, "intent_yaml"),
            ({"intent_yaml": "a: [unclosed\n"}, "intent_yaml"),
            ({"plan_md": "x" * 100_001}, "plan_md"),
            ({"params": {"blob": "x" * 300_000}}, "params"),
        ],
    )
    async def test_invalid_updates_are_422(self, client: AsyncClient, body, where):
        _, brief = await _idea_brief(client)
        response = await client.patch(f"{BRIEFS}/{brief['id']}", json=body)
        assert response.status_code == 422, response.text
        if where:
            assert where in str(response.json()["detail"])

    async def test_invalid_intent_on_start_writes_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        idea = await create_idea(client)
        response = await client.post(
            f"{IDEAS}/{idea['id']}/design-brief",
            json={"intent": {**FILLED_INTENT, "sales_channel": "ebay"}},
        )
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["intent", "sales_channel"]
        assert await db_session.scalar(select(func.count()).select_from(DesignBrief)) == 0

    async def test_delete(self, client: AsyncClient, db_session: AsyncSession):
        _, brief = await _idea_brief(client, intent=FILLED_INTENT)
        response = await client.delete(f"{BRIEFS}/{brief['id']}")
        assert response.status_code == 204
        assert (await client.get(f"{BRIEFS}/{brief['id']}")).status_code == 404
        assert await _revisions(db_session, brief["id"], "intent") == 0


# ============================================
# Access
# ============================================


# A fixed id keeps the parametrize ids identical across xdist workers.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000009"


class TestAccess:
    async def test_other_tenant_is_404(self, client: AsyncClient, db_session: AsyncSession):
        theirs = await other_tenant(db_session)
        their_idea = await idea_in(db_session, theirs)
        brief = DesignBrief(tenant_id=theirs.id, idea_id=their_idea.id, step_status={})
        db_session.add(brief)
        await db_session.commit()

        assert (await client.get(f"{IDEAS}/{their_idea.id}/design-brief")).status_code == 404
        assert (
            await client.post(f"{IDEAS}/{their_idea.id}/design-brief", json={})
        ).status_code == 404
        assert (await client.get(f"{BRIEFS}/{brief.id}")).status_code == 404
        patched = await client.patch(f"{BRIEFS}/{brief.id}", json={"plan_md": "x"})
        assert patched.status_code == 404
        assert (await client.get(f"{BRIEFS}/{brief.id}/revisions")).status_code == 404
        assert (await client.delete(f"{BRIEFS}/{brief.id}")).status_code == 404
        assert (await client.get(f"{MODELS}/{uuid.uuid4()}/design-brief")).status_code == 404

    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", f"{BRIEFS}/{UNKNOWN_ID}"),
            ("PATCH", f"{BRIEFS}/{UNKNOWN_ID}"),
            ("GET", f"{IDEAS}/{UNKNOWN_ID}/design-brief"),
            ("POST", f"{MODELS}/{UNKNOWN_ID}/design-brief"),
            ("DELETE", f"{BRIEFS}/{UNKNOWN_ID}"),
        ],
    )
    async def test_signed_out_is_401(self, unauthenticated_client: AsyncClient, method, path):
        response = await unauthenticated_client.request(method, path, json={"plan_md": "x"})
        assert response.status_code == 401

    async def test_viewer_reads_but_does_not_write(self, client: AsyncClient, as_role):
        idea, brief = await _idea_brief(client)
        async with as_role(UserRole.VIEWER) as viewer:
            assert (await viewer.get(f"{BRIEFS}/{brief['id']}")).status_code == 200
            assert (await viewer.get(f"{BRIEFS}/{brief['id']}/revisions")).status_code == 200
            patched = await viewer.patch(f"{BRIEFS}/{brief['id']}", json={"plan_md": "x"})
            assert patched.status_code == 403
            started = await viewer.post(f"{IDEAS}/{idea['id']}/design-brief", json={})
            assert started.status_code == 403
            assert (await viewer.delete(f"{BRIEFS}/{brief['id']}")).status_code == 403


# ============================================
# Personal API tokens (US6, api_token_policy rows)
# ============================================


class TestTokens:
    async def _brief(self, db: AsyncSession, tenant: Tenant) -> DesignBrief:
        idea = await idea_in(db, tenant, title="Token idea")
        brief = DesignBrief(tenant_id=tenant.id, idea_id=idea.id, step_status={})
        db.add(brief)
        await db.commit()
        return brief

    async def test_read_token_reads_only(
        self,
        unauthenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_user: User,
    ):
        brief = await self._brief(db_session, test_tenant)
        _, secret = await make_token(db_session, test_tenant, test_user, ["read"])
        headers = bearer(secret)
        shown = await unauthenticated_client.get(f"{BRIEFS}/{brief.id}", headers=headers)
        assert shown.status_code == 200
        refused = await unauthenticated_client.patch(
            f"{BRIEFS}/{brief.id}", json={"plan_md": "x"}, headers=headers
        )
        assert refused.status_code == 403

    async def test_write_token_writes_but_never_deletes(
        self,
        unauthenticated_client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        test_user: User,
    ):
        brief = await self._brief(db_session, test_tenant)
        _, secret = await make_token(db_session, test_tenant, test_user, ["read", "write"])
        headers = bearer(secret)
        patched = await unauthenticated_client.patch(
            f"{BRIEFS}/{brief.id}",
            json={"intent": FILLED_INTENT, "steps": {"intent": "done"}},
            headers=headers,
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["created_revisions"] == ["intent"]
        deleted = await unauthenticated_client.delete(f"{BRIEFS}/{brief.id}", headers=headers)
        assert deleted.status_code == 403

        signed_in = await unauthenticated_client.delete(
            f"{BRIEFS}/{brief.id}", headers=jwt_headers(test_user, test_tenant)
        )
        assert signed_in.status_code == 204
