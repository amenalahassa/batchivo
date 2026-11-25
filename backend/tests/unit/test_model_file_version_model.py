"""Constraints of model file versions and pinned notes (data-model.md, T009)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.model import Model
from app.models.model_file import ModelFile
from app.models.model_file_note import ModelFileNote
from app.models.model_file_version import ModelFileVersion


async def _model(db, tenant) -> Model:
    model = Model(id=uuid4(), tenant_id=tenant.id, sku=f"M-{uuid4().hex[:6]}", name="Part")
    db.add(model)
    await db.commit()
    return model


def _version(tenant, model, sequence, active=False) -> ModelFileVersion:
    return ModelFileVersion(
        tenant_id=tenant.id,
        model_id=model.id,
        sequence=sequence,
        label=str(sequence),
        is_active=active,
    )


def _note(tenant, model, version, model_file=None, **kw) -> ModelFileNote:
    base = dict(
        tenant_id=tenant.id,
        model_id=model.id,
        version_id=version.id,
        model_file_id=model_file.id if model_file else None,
        number=1,
        pos_x=1.0,
        pos_y=2.0,
        pos_z=3.0,
        normal_x=0.0,
        normal_y=0.0,
        normal_z=1.0,
        text="sags here",
    )
    base.update(kw)
    return ModelFileNote(**base)


class TestVersionConstraints:
    async def test_two_active_versions_for_one_model_are_refused(self, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        db_session.add(_version(test_tenant, model, 1, active=True))
        await db_session.commit()
        db_session.add(_version(test_tenant, model, 2, active=True))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_inactive_versions_may_be_many(self, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        db_session.add_all([_version(test_tenant, model, 1, True), _version(test_tenant, model, 2)])
        db_session.add(_version(test_tenant, model, 3))
        await db_session.commit()

    async def test_a_sequence_is_unique_per_model(self, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        db_session.add(_version(test_tenant, model, 1))
        await db_session.commit()
        db_session.add(_version(test_tenant, model, 1))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_versions_go_with_their_model(self, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        db_session.add(_version(test_tenant, model, 1, True))
        await db_session.commit()
        await db_session.delete(model)
        await db_session.commit()
        remaining = (await db_session.execute(select(ModelFileVersion))).scalars().all()
        assert [v for v in remaining if v.model_id == model.id] == []


class TestNoteConstraints:
    async def test_status_must_be_known(self, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        version = _version(test_tenant, model, 1, True)
        db_session.add(version)
        await db_session.flush()
        db_session.add(_note(test_tenant, model, version, status="maybe"))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_resolved_needs_the_version_it_was_resolved_in(self, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        version = _version(test_tenant, model, 1, True)
        db_session.add(version)
        await db_session.flush()
        db_session.add(_note(test_tenant, model, version, status="resolved"))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_deleting_the_file_keeps_the_note(self, db_session, test_tenant):
        model = await _model(db_session, test_tenant)
        version = _version(test_tenant, model, 1, True)
        db_session.add(version)
        await db_session.flush()
        model_file = ModelFile(
            tenant_id=test_tenant.id,
            model_id=model.id,
            version_id=version.id,
            file_type="source_stl",
            original_filename="part.stl",
            uploaded_at=datetime.now(UTC),
        )
        db_session.add(model_file)
        await db_session.flush()
        note = _note(test_tenant, model, version, model_file)
        db_session.add(note)
        await db_session.commit()
        note_id = note.id

        await db_session.delete(model_file)
        await db_session.commit()
        db_session.expire_all()
        kept = await db_session.get(ModelFileNote, note_id)
        assert kept is not None
        assert kept.model_file_id is None
