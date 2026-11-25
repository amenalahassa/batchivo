"""Database rules of the three genai tables (spec 008, T007, T088).

Each CHECK of ``generation_jobs``, ``genai_assets`` and ``genai_adoptions`` is
proven by a valid baseline row and the same row with one field changed, which
the database refuses under the constraint's own name. Deleting a job removes
its assets and their adoptions and clears ``idea_entries.generation_job_id``
(the foreign keys' ``ON DELETE``, exercised with a plain SQL delete).
"""

import uuid

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_job import GenAIAdoption, GenAIAsset, GenerationJob
from app.models.idea import IdeaEntry
from app.models.tenant import Tenant
from tests.utils.ideas import entry_in, idea_in


async def _expect_refused(db: AsyncSession, row, constraint: str) -> None:
    # A savepoint: a full rollback would expire the tenant the next lines read.
    savepoint = await db.begin_nested()
    db.add(row)
    with pytest.raises(IntegrityError) as caught:
        await db.flush()
    await savepoint.rollback()
    assert constraint in str(caught.value)


def _job(tenant: Tenant, **fields) -> GenerationJob:
    values = dict(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        capability="concept_image",
        provider="replicate",
        model_ref="owner/model",
        model_version="official",
        inputs={"prompt": "a clip"},
        seed=7,
        target_type="none",
        target_id=None,
        status="queued",
        estimated_cost=0,
        cost=None,
        cost_provenance=None,
        price_snapshot={},
    )
    values.update(fields)
    return GenerationJob(**values)


def _asset(tenant: Tenant, job_id, **fields) -> GenAIAsset:
    values = dict(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        job_id=job_id,
        source="output",
        kind="image",
        storage_url="/uploads/generations/x/a.png",
        content_type="image/png",
        ai_generated=True,
    )
    values.update(fields)
    return GenAIAsset(**values)


def _adoption(tenant: Tenant, asset_id, **fields) -> GenAIAdoption:
    values = dict(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        asset_id=asset_id,
        owner_type="idea",
        owner_id=uuid.uuid4(),
    )
    values.update(fields)
    return GenAIAdoption(**values)


async def _saved_job(db: AsyncSession, tenant: Tenant) -> GenerationJob:
    job = _job(tenant)
    db.add(job)
    await db.commit()
    return job


async def _saved_asset(db: AsyncSession, tenant: Tenant) -> GenAIAsset:
    job = await _saved_job(db, tenant)
    asset = _asset(tenant, job.id)
    db.add(asset)
    await db.commit()
    return asset


# ============================================
# generation_jobs
# ============================================


async def test_job_baseline_is_accepted(db_session: AsyncSession, test_tenant: Tenant):
    db_session.add(_job(test_tenant))
    db_session.add(
        _job(
            test_tenant,
            target_type="idea",
            target_id=uuid.uuid4(),
            status="succeeded",
            estimated_cost=0,
            cost=0,
            cost_provenance="computed",
        )
    )
    await db_session.commit()


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"capability": "video"}, "ck_generation_jobs_capability"),
        ({"target_type": "order", "target_id": uuid.uuid4()}, "ck_generation_jobs_target"),
        ({"target_type": "none", "target_id": uuid.uuid4()}, "ck_generation_jobs_target_id"),
        ({"target_type": "idea", "target_id": None}, "ck_generation_jobs_target_id"),
        ({"status": "paused"}, "ck_generation_jobs_status"),
        ({"estimated_cost": -1}, "ck_generation_jobs_estimate_positive"),
        ({"cost": -1}, "ck_generation_jobs_cost_positive"),
        ({"cost": 0, "cost_provenance": "guessed"}, "ck_generation_jobs_cost_provenance"),
    ],
)
async def test_job_constraints(db_session: AsyncSession, test_tenant: Tenant, fields, constraint):
    await _expect_refused(db_session, _job(test_tenant, **fields), constraint)


# ============================================
# genai_assets
# ============================================


async def test_asset_baseline_is_accepted(db_session: AsyncSession, test_tenant: Tenant):
    job = await _saved_job(db_session, test_tenant)
    db_session.add(_asset(test_tenant, job.id))
    # An upload belongs to no job and need not be marked as AI-generated.
    db_session.add(_asset(test_tenant, None, source="upload", ai_generated=False))
    await db_session.commit()


@pytest.mark.parametrize(
    ("fields", "no_job", "constraint"),
    [
        # Not an output, so tied to no job (only the source rule is broken).
        ({"source": "scraped", "ai_generated": False}, True, "ck_genai_assets_source"),
        ({"kind": "video"}, False, "ck_genai_assets_kind"),
        ({}, True, "ck_genai_assets_job"),  # an output without its job
        ({"source": "upload"}, False, "ck_genai_assets_job"),  # an upload tied to a job
        ({"ai_generated": False}, False, "ck_genai_assets_ai_generated"),
    ],
)
async def test_asset_constraints(
    db_session: AsyncSession, test_tenant: Tenant, fields, no_job, constraint
):
    job = await _saved_job(db_session, test_tenant)
    row = _asset(test_tenant, None if no_job else job.id, **fields)
    await _expect_refused(db_session, row, constraint)


# ============================================
# genai_adoptions
# ============================================


async def test_adoption_baseline_is_accepted(db_session: AsyncSession, test_tenant: Tenant):
    asset = await _saved_asset(db_session, test_tenant)
    entry = await entry_in(db_session, await idea_in(db_session, test_tenant))
    db_session.add(_adoption(test_tenant, asset.id, idea_entry_id=entry.id))
    await db_session.commit()


async def test_adoption_owner_type(db_session: AsyncSession, test_tenant: Tenant):
    asset = await _saved_asset(db_session, test_tenant)
    await _expect_refused(
        db_session,
        _adoption(test_tenant, asset.id, owner_type="order"),
        "ck_genai_adoptions_owner",
    )


async def test_adoption_names_at_most_one_result(db_session: AsyncSession, test_tenant: Tenant):
    asset = await _saved_asset(db_session, test_tenant)
    entry = await entry_in(db_session, await idea_in(db_session, test_tenant))
    # The CHECK is evaluated before the foreign keys, so its name is what is reported.
    await _expect_refused(
        db_session,
        _adoption(test_tenant, asset.id, idea_entry_id=entry.id, product_image_id=uuid.uuid4()),
        "ck_genai_adoptions_one_result",
    )


async def test_adoption_unique_per_target(db_session: AsyncSession, test_tenant: Tenant):
    asset = await _saved_asset(db_session, test_tenant)
    owner = uuid.uuid4()
    db_session.add(_adoption(test_tenant, asset.id, owner_id=owner))
    await db_session.commit()
    await _expect_refused(
        db_session,
        _adoption(test_tenant, asset.id, owner_id=owner),
        "uq_genai_adoptions_target",
    )
    # The same asset may be adopted into another owner, or as another owner type.
    db_session.add(_adoption(test_tenant, asset.id, owner_id=uuid.uuid4()))
    db_session.add(_adoption(test_tenant, asset.id, owner_type="product", owner_id=owner))
    await db_session.commit()


# ============================================
# Deleting a job
# ============================================


async def test_deleting_a_job_cascades_and_clears_idea_entries(
    db_session: AsyncSession, test_tenant: Tenant
):
    asset = await _saved_asset(db_session, test_tenant)
    job_id = asset.job_id
    idea = await idea_in(db_session, test_tenant)
    entry = await entry_in(db_session, idea, generation_job_id=job_id)
    adoption = _adoption(test_tenant, asset.id, owner_id=idea.id, idea_entry_id=entry.id)
    db_session.add(adoption)
    # An upload of the same tenant, tied to no job, must survive.
    upload = _asset(test_tenant, None, source="upload", ai_generated=False)
    db_session.add(upload)
    await db_session.commit()
    asset_id, adoption_id, upload_id, entry_id = asset.id, adoption.id, upload.id, entry.id

    # A plain SQL delete: the database's ON DELETE rules, not the ORM's cascade.
    await db_session.execute(delete(GenerationJob).where(GenerationJob.id == job_id))
    await db_session.commit()
    db_session.expire_all()

    assert await db_session.get(GenerationJob, job_id) is None
    assert await db_session.get(GenAIAsset, asset_id) is None
    assert await db_session.get(GenAIAdoption, adoption_id) is None
    assert await db_session.get(GenAIAsset, upload_id) is not None
    kept = await db_session.get(IdeaEntry, entry_id)
    assert kept is not None and kept.generation_job_id is None
