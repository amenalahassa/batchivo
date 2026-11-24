"""Idea and IdeaEntry: CRUD, constraints, derived score, links (spec 007)."""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.idea import Idea, IdeaEntry
from app.models.model import Model
from app.models.product import Product
from app.models.tenant import Tenant
from tests.utils.ideas import entry_in, idea_in

FIVE = dict(
    score_frequency=4,
    score_frustration=5,
    score_printability=3,
    score_gap=4,
    score_willingness_to_pay=2,
)


async def _expect_refused(db: AsyncSession, row) -> None:
    # A savepoint: a full rollback would expire the tenant the next lines read.
    savepoint = await db.begin_nested()
    db.add(row)
    with pytest.raises(IntegrityError):
        await db.flush()
    await savepoint.rollback()


class TestIdeaRows:
    async def test_crud_and_defaults(self, db_session: AsyncSession, test_tenant: Tenant):
        idea = await idea_in(db_session, test_tenant, title="Clip", tags=["car"])
        stored = await db_session.get(Idea, idea.id)
        assert (stored.status, stored.source, stored.current_iteration) == ("inbox", "manual", 1)
        assert stored.tags == ["car"] and stored.archived_at is None

        stored.status = "ready"
        await db_session.commit()
        assert (await db_session.get(Idea, idea.id)).status == "ready"

        await db_session.delete(stored)
        await db_session.commit()
        assert await db_session.get(Idea, idea.id) is None

    @pytest.mark.parametrize(
        "fields",
        [
            {"title": "   "},
            {"status": "foo"},
            {"source": "rumour"},
            {"score_gap": 0},
            {"score_frequency": 6},
            {"report_score": 26},
            {"current_iteration": 0},
        ],
    )
    async def test_constraints(self, db_session: AsyncSession, test_tenant: Tenant, fields):
        row = Idea(id=uuid.uuid4(), tenant_id=test_tenant.id, tags=[], **{"title": "x", **fields})
        await _expect_refused(db_session, row)

    async def test_score_in_python_and_sql(self, db_session: AsyncSession, test_tenant: Tenant):
        full = await idea_in(db_session, test_tenant, title="full", report_score=3, **FIVE)
        partial = await idea_in(
            db_session, test_tenant, title="partial", report_score=21, score_gap=2
        )
        none = await idea_in(db_session, test_tenant, title="none")

        assert (full.score, full.score_source) == (18, "scores")
        assert (partial.score, partial.score_source) == (21, "report")
        assert (none.score, none.score_source) == (None, None)

        rows = await db_session.execute(
            select(Idea.title, Idea.score)
            .where(Idea.tenant_id == test_tenant.id)
            .order_by(Idea.score.desc().nullslast())
        )
        assert list(rows) == [("partial", 21), ("full", 18), ("none", None)]

    async def test_report_link_unique_per_tenant(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        link = "https://forum.example.org/1"
        await idea_in(db_session, test_tenant, source="pain_point_report", source_url=link)
        await _expect_refused(
            db_session,
            Idea(
                id=uuid.uuid4(),
                tenant_id=test_tenant.id,
                title="dup",
                tags=[],
                source="pain_point_report",
                source_url=link,
            ),
        )
        # A manual idea may carry the same link.
        await idea_in(db_session, test_tenant, source="manual", source_url=link)


class TestEntryRows:
    @pytest.mark.parametrize(
        "fields",
        [
            {"kind": "brief", "body": "x"},
            {"kind": "image", "body": None},
            {"kind": "sketch", "body": None},
            {"kind": "link", "body": "x"},
            {"kind": "note", "body": "  "},
            {"kind": "decision", "body": None},
            {"kind": "note", "body": "x", "iteration": 0},
        ],
    )
    async def test_constraints(self, db_session: AsyncSession, test_tenant: Tenant, fields):
        idea = await idea_in(db_session, test_tenant)
        row = IdeaEntry(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            idea_id=idea.id,
            **{"iteration": 1, **fields},
        )
        await _expect_refused(db_session, row)

    async def test_generation_entry_has_room_for_a_job(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        """Feature 008 writes these; the kind and job reference exist from 007 on."""
        idea = await idea_in(db_session, test_tenant)
        job = uuid.uuid4()
        entry = await entry_in(
            db_session,
            idea,
            kind="generation",
            body=None,
            image_url="/uploads/ideas/x/y.jpg",
            generation_job_id=job,
        )
        assert (await db_session.get(IdeaEntry, entry.id)).generation_job_id == job

    async def test_cover_cleared_when_entry_deleted_and_entries_go_with_idea(
        self, db_session: AsyncSession, test_tenant: Tenant
    ):
        idea = await idea_in(db_session, test_tenant)
        image = await entry_in(
            db_session, idea, kind="image", body=None, image_url="/uploads/ideas/x/y.jpg"
        )
        idea.cover_entry_id = image.id
        await db_session.commit()

        await db_session.execute(text("DELETE FROM idea_entries WHERE id = :id"), {"id": image.id})
        await db_session.commit()
        await db_session.refresh(idea)
        assert idea.cover_entry_id is None

        note = await entry_in(db_session, idea)
        await db_session.execute(text("DELETE FROM ideas WHERE id = :id"), {"id": idea.id})
        await db_session.commit()
        db_session.expunge_all()
        assert await db_session.get(IdeaEntry, note.id) is None


class TestSourceIdeaOnModelsAndProducts:
    async def test_set_null_when_idea_row_goes(self, db_session: AsyncSession, test_tenant: Tenant):
        idea = await idea_in(db_session, test_tenant)
        model = Model(
            id=uuid.uuid4(), tenant_id=test_tenant.id, sku="M-1", name="m", source_idea_id=idea.id
        )
        product = Product(
            id=uuid.uuid4(), tenant_id=test_tenant.id, sku="P-1", name="p", source_idea_id=idea.id
        )
        db_session.add_all([model, product])
        await db_session.commit()

        await db_session.execute(text("DELETE FROM ideas WHERE id = :id"), {"id": idea.id})
        await db_session.commit()
        await db_session.refresh(model)
        await db_session.refresh(product)
        assert model.source_idea_id is None and product.source_idea_id is None


async def test_rls_policies_exist(db_session: AsyncSession):
    """The migration's policies, when the schema comes from Alembic on PostgreSQL."""
    if db_session.bind.dialect.name != "postgresql":
        pytest.skip("RLS is PostgreSQL only")
    rows = await db_session.execute(
        text("SELECT tablename FROM pg_policies WHERE tablename IN ('ideas', 'idea_entries')")
    )
    found = {r[0] for r in rows}
    if not found:
        pytest.skip("schema built from the models, not from the migration")
    assert found == {"ideas", "idea_entries"}
