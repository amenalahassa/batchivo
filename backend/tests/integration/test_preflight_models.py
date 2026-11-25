"""The spec 009 tables: rows, relationships and constraints (T008)."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calibration import Calibration
from app.models.design_brief import DesignBrief, DesignBriefRevision
from app.models.print_job import JobPriority, JobStatus, PrintJob
from app.models.print_test_result import PrintTestResult
from tests.utils.ideas import idea_in


async def _refused(db: AsyncSession, row) -> None:
    db.add(row)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


def _calibration(tenant, printer, material, **fields) -> Calibration:
    values = {
        "id": uuid.uuid4(),
        "tenant_id": tenant.id,
        "printer_id": printer.id,
        "material_type_id": material.id,
        "orientation": "vertical",
        "fit_type": "slide",
        "value_mm": Decimal("0.150"),
        "provenance": "measured",
    }
    return Calibration(**{**values, **fields})


class TestDesignBriefs:
    async def test_brief_and_revisions(self, db_session: AsyncSession, test_tenant, test_model):
        brief = DesignBrief(tenant_id=test_tenant.id, model_id=test_model.id, step_status={})
        db_session.add(brief)
        await db_session.flush()
        db_session.add(
            DesignBriefRevision(
                tenant_id=test_tenant.id, brief_id=brief.id, part="plan", content={"plan_md": "x"}
            )
        )
        await db_session.commit()
        stored = await db_session.scalar(
            select(DesignBriefRevision).where(DesignBriefRevision.brief_id == brief.id)
        )
        assert stored.content == {"plan_md": "x"}

    async def test_one_brief_per_idea_and_per_model(
        self, db_session: AsyncSession, test_tenant, test_model
    ):
        # Plain ids: a refused flush rolls back and expires the fixtures' objects.
        tenant_id, model_id = test_tenant.id, test_model.id
        idea = await idea_in(db_session, test_tenant)
        idea_id = idea.id
        db_session.add(DesignBrief(tenant_id=tenant_id, idea_id=idea_id, step_status={}))
        db_session.add(DesignBrief(tenant_id=tenant_id, model_id=model_id, step_status={}))
        await db_session.commit()
        await _refused(
            db_session, DesignBrief(tenant_id=tenant_id, idea_id=idea_id, step_status={})
        )
        await _refused(
            db_session, DesignBrief(tenant_id=tenant_id, model_id=model_id, step_status={})
        )

    async def test_risk_class_check(self, db_session: AsyncSession, test_tenant, test_model):
        await _refused(
            db_session,
            DesignBrief(
                tenant_id=test_tenant.id,
                model_id=test_model.id,
                step_status={},
                risk_class="énorme",
            ),
        )

    async def test_revision_part_check(self, db_session: AsyncSession, test_tenant, test_model):
        brief = DesignBrief(tenant_id=test_tenant.id, model_id=test_model.id, step_status={})
        db_session.add(brief)
        await db_session.commit()
        await _refused(
            db_session,
            DesignBriefRevision(
                tenant_id=test_tenant.id, brief_id=brief.id, part="params", content={}
            ),
        )


class TestCalibrations:
    async def test_one_current_value_per_combination(
        self, db_session: AsyncSession, test_tenant, test_printer, test_material_type
    ):
        first = _calibration(test_tenant, test_printer, test_material_type)
        db_session.add(first)
        await db_session.commit()
        await _refused(db_session, _calibration(test_tenant, test_printer, test_material_type))

    async def test_a_superseded_value_leaves_room(
        self, db_session: AsyncSession, test_tenant, test_printer, test_material_type
    ):
        from datetime import UTC, datetime

        first = _calibration(test_tenant, test_printer, test_material_type)
        db_session.add(first)
        await db_session.commit()
        first.superseded_at = datetime.now(UTC)
        await db_session.flush()
        second = _calibration(test_tenant, test_printer, test_material_type)
        db_session.add(second)
        await db_session.flush()
        first.superseded_by_id = second.id
        await db_session.commit()
        assert first.is_current is False and second.is_current is True

    async def test_filament_and_material_values_coexist(
        self,
        db_session: AsyncSession,
        test_tenant,
        test_printer,
        test_material_type,
        test_filament_type,
    ):
        db_session.add(_calibration(test_tenant, test_printer, test_material_type))
        db_session.add(
            _calibration(
                test_tenant,
                test_printer,
                test_material_type,
                filament_type_id=test_filament_type.id,
            )
        )
        await db_session.commit()

    @pytest.mark.parametrize(
        "field,value",
        [
            ("value_mm", Decimal("2.001")),
            ("value_mm", Decimal("-0.001")),
            ("orientation", "diagonal"),
            ("fit_type", "glued"),
            ("provenance", "guessed"),
        ],
    )
    async def test_checks(
        self, db_session: AsyncSession, test_tenant, test_printer, test_material_type, field, value
    ):
        await _refused(
            db_session,
            _calibration(test_tenant, test_printer, test_material_type, **{field: value}),
        )


class TestPrintTestResults:
    async def test_row_and_checks(self, db_session: AsyncSession, test_tenant, test_model):
        result = PrintTestResult(
            tenant_id=test_tenant.id,
            kind="full_part",
            outcome="partial",
            model_id=test_model.id,
            measurements=[{"name": "gap", "value": "0.15"}],
        )
        db_session.add(result)
        await db_session.commit()
        assert result.measurements == [{"name": "gap", "value": "0.15"}]
        tenant_id = test_tenant.id
        for field, value in (("kind", "smoke"), ("outcome", "meh"), ("orientation", "diagonal")):
            row = {
                "tenant_id": tenant_id,
                "kind": "full_part",
                "outcome": "pass",
                "measurements": [],
            }
            await _refused(db_session, PrintTestResult(**{**row, field: value}))


class TestDeletions:
    """Spec 009 edge cases: what a deleted printer or print job leaves behind (T064).

    Run against the immutability triggers on PostgreSQL: a trigger that refused the
    ON DELETE SET NULL would make deleting a print job impossible.
    """

    async def test_a_deleted_job_leaves_its_results_and_calibrations_unlinked(
        self, db_session: AsyncSession, test_tenant, test_printer, test_material_type
    ):
        job = PrintJob(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            quantity=1,
            priority=JobPriority.NORMAL.value,
            status=JobStatus.PENDING.value,
        )
        db_session.add(job)
        await db_session.flush()
        result = PrintTestResult(
            id=uuid.uuid4(),
            tenant_id=test_tenant.id,
            kind="clearance_grid",
            outcome="pass",
            print_job_id=job.id,
            measurements=[],
        )
        db_session.add(result)
        await db_session.flush()
        calibration = _calibration(
            test_tenant,
            test_printer,
            test_material_type,
            source_print_job_id=job.id,
            source_test_result_id=result.id,
        )
        db_session.add(calibration)
        await db_session.commit()
        job_id, result_id, calibration_id = job.id, result.id, calibration.id

        await db_session.execute(text("DELETE FROM print_jobs WHERE id = :id"), {"id": job_id})
        await db_session.commit()
        db_session.expunge_all()

        kept = await db_session.get(PrintTestResult, result_id)
        assert kept is not None and kept.print_job_id is None
        cal = await db_session.get(Calibration, calibration_id)
        assert cal is not None and cal.source_print_job_id is None
        assert cal.value_mm == Decimal("0.150")

        await db_session.execute(
            text("DELETE FROM print_test_results WHERE id = :id"), {"id": result_id}
        )
        await db_session.commit()
        db_session.expunge_all()
        cal = await db_session.get(Calibration, calibration_id)
        assert cal is not None and cal.source_test_result_id is None

    async def test_a_deleted_printer_takes_its_calibrations(
        self, db_session: AsyncSession, test_tenant, test_printer, test_material_type
    ):
        printer_id = test_printer.id
        first = _calibration(test_tenant, test_printer, test_material_type)
        db_session.add(first)
        second = _calibration(test_tenant, test_printer, test_material_type, fit_type="press")
        db_session.add(second)
        await db_session.commit()

        await db_session.execute(text("DELETE FROM printers WHERE id = :id"), {"id": printer_id})
        await db_session.commit()
        left = await db_session.scalar(
            select(func.count())
            .select_from(Calibration)
            .where(Calibration.printer_id == printer_id)
        )
        assert left == 0
