"""DesignBriefService rules (spec 009, T022): revisions on change only, idea → model."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.design_brief import DesignBriefRevision
from app.models.model import Model
from app.schemas.design_brief import DesignBriefStart, DesignBriefUpdate
from app.services.design_brief_service import BriefNotFound, DesignBriefService
from tests.fixtures.preflight import FILLED_INTENT
from tests.utils.ideas import idea_in


async def _revisions(db: AsyncSession, brief_id, part: str) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(DesignBriefRevision)
        .where(DesignBriefRevision.brief_id == brief_id, DesignBriefRevision.part == part)
    )


@pytest.fixture
def service(db_session, test_tenant, test_user) -> DesignBriefService:
    return DesignBriefService(db_session, test_tenant, test_user)


async def test_risk_part_is_replaced_as_a_whole(service, db_session, test_model):
    brief, _ = await service.start_on_model(test_model.id, DesignBriefStart())
    await service.update(
        brief,
        DesignBriefUpdate(risk={"risk_class": "moyen", "risk_md": "# R", "triage": {"s": 1}}),
    )
    created = await service.update(brief, DesignBriefUpdate(risk={"risk_class": "élevé"}))
    assert created == ["risk"]
    assert (brief.risk_class, brief.risk_md, brief.triage) == ("élevé", None, None)
    assert await _revisions(db_session, brief.id, "risk") == 2


async def test_unchanged_parts_make_no_revision(service, db_session, test_model):
    brief, _ = await service.start_on_model(test_model.id, DesignBriefStart(intent=FILLED_INTENT))
    assert await _revisions(db_session, brief.id, "intent") == 1
    created = await service.update(
        brief,
        DesignBriefUpdate(intent=FILLED_INTENT, plan_md=None, params={"a": 1}),
    )
    assert created == []  # plan None == None; params are not revisioned
    assert brief.params == {"a": 1} and brief.params_updated_at is not None


async def test_steps_are_stamped_and_merged(service, test_user, test_model):
    brief, _ = await service.start_on_model(test_model.id, DesignBriefStart())
    await service.update(brief, DesignBriefUpdate(steps={"intent": "done"}))
    await service.update(brief, DesignBriefUpdate(steps={"risk": "blocked"}))
    assert set(brief.step_status) == {"intent", "risk"}
    assert brief.step_status["intent"]["updated_by"] == str(test_user.id)
    response = await service.to_response(brief)
    states = {s.step: s.status for s in response.steps}
    assert states["intent"] == "done" and states["risk"] == "blocked"
    assert states["ship"] == "not_started"


async def test_model_reaches_its_source_idea_brief_without_writing(
    service, db_session, test_tenant
):
    idea = await idea_in(db_session, test_tenant, title="Porte-sac")
    brief, created = await service.start_on_idea(idea.id, DesignBriefStart())
    assert created
    model = Model(
        id=uuid.uuid4(),
        tenant_id=test_tenant.id,
        sku="SRC-1",
        name="From idea",
        source_idea_id=idea.id,
    )
    db_session.add(model)
    await db_session.commit()

    found = await service.find_for_model(model.id)
    assert found.id == brief.id and found.model_id is None
    started, created = await service.start_on_model(model.id, DesignBriefStart())
    assert not created and started.id == brief.id and started.model_id == model.id
    assert (await service.find_for_idea(idea.id)).id == brief.id


async def test_unknown_owner_or_brief(service):
    with pytest.raises(BriefNotFound):
        await service.find_for_idea(uuid.uuid4())
    with pytest.raises(BriefNotFound):
        await service.find_for_model(uuid.uuid4())
    with pytest.raises(BriefNotFound):
        await service.get(uuid.uuid4())
