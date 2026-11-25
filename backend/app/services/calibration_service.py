"""Fit calibrations: record, supersede, look up, export (spec 009, US3, research R6).

The one place that decides which fit value applies to a combination: the
current value recorded for the filament if one is given and exists, else the
current value for the material, else none -- the caller (Preflight's
``pf.py clearance``) then falls back to its generic rule. Measurement beats rule.

A calibration is never edited. Recording a value for a combination that has a
current one locks that row, inserts the new one and links the old one to it, in
one transaction; the partial unique index turns a concurrent duplicate into a
conflict the caller retries.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calibration import Calibration
from app.models.filament_type import FilamentType
from app.models.material import MaterialType
from app.models.print_job import PrintJob
from app.models.print_test_result import PrintTestResult
from app.models.printer import Printer
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.calibration import (
    AtelierCalibration,
    CalibrationCreate,
    CalibrationResponse,
)
from app.schemas.model_file_version import PersonRef

logger = logging.getLogger(__name__)


class CalibrationError(Exception):
    """A request the service refuses; ``status_code`` is the HTTP status to answer."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


async def resolve_material(
    db: AsyncSession, material_type_id: Optional[uuid.UUID], code: Optional[str]
) -> Optional[MaterialType]:
    """A material by id or by code (case-insensitive); None when neither is given."""
    if material_type_id is not None:
        material = await db.get(MaterialType, material_type_id)
        if material is None:
            raise CalibrationError("Unknown material", 422)
        return material
    if code:
        material = await db.scalar(
            select(MaterialType).where(func.lower(MaterialType.code) == code.strip().lower())
        )
        if material is None:
            raise CalibrationError(f"Unknown material code: {code}", 422)
        return material
    return None


def filament_label(filament: Optional[FilamentType]) -> Optional[str]:
    if filament is None:
        return None
    return f"{filament.brand} {filament.color}".strip()


class CalibrationService:
    """A tenant's fit calibrations."""

    def __init__(self, db: AsyncSession, tenant: Tenant, user: Optional[User] = None):
        self.db = db
        self.tenant = tenant
        self.user = user

    # ----------------------------------------------------------------- checks

    async def printer(self, printer_id: uuid.UUID) -> Printer:
        printer = await self.db.scalar(
            select(Printer).where(Printer.id == printer_id, Printer.tenant_id == self.tenant.id)
        )
        if printer is None:
            raise CalibrationError("Printer not found", 404)
        return printer

    async def filament(self, filament_type_id: Optional[uuid.UUID]) -> Optional[FilamentType]:
        if filament_type_id is None:
            return None
        filament = await self.db.scalar(
            select(FilamentType).where(
                FilamentType.id == filament_type_id, FilamentType.tenant_id == self.tenant.id
            )
        )
        if filament is None:
            raise CalibrationError("Filament type not found", 404)
        return filament

    async def _owned(self, model, row_id: Optional[uuid.UUID], label: str) -> None:
        if row_id is None:
            return
        found = await self.db.scalar(
            select(model.id).where(model.id == row_id, model.tenant_id == self.tenant.id)
        )
        if found is None:
            raise CalibrationError(f"{label} not found", 404)

    # ----------------------------------------------------------------- writes

    async def record(self, printer_id: uuid.UUID, data: CalibrationCreate) -> Calibration:
        """Record a value; the current one of the same combination becomes superseded."""
        await self.printer(printer_id)
        material = await resolve_material(self.db, data.material_type_id, data.material)
        filament = await self.filament(data.filament_type_id)
        if filament is not None and filament.material_type_id != material.id:
            raise CalibrationError("The filament type is not of that material", 422)
        await self._owned(PrintJob, data.source_print_job_id, "Print job")
        await self._owned(PrintTestResult, data.source_test_result_id, "Test result")

        query = (
            select(Calibration)
            .where(*self._combination(printer_id, material.id, filament, data))
            .where(Calibration.superseded_by_id.is_(None))
            .with_for_update()
        )
        current = await self.db.scalar(query)

        new = Calibration(
            id=uuid.uuid4(),
            tenant_id=self.tenant.id,
            printer_id=printer_id,
            material_type_id=material.id,
            filament_type_id=filament.id if filament else None,
            orientation=data.orientation,
            fit_type=data.fit_type,
            value_mm=data.value_mm,
            provenance=data.provenance,
            source_print_job_id=data.source_print_job_id,
            source_test_result_id=data.source_test_result_id,
            measured_at=data.measured_at or datetime.now(UTC),
            notes=data.notes,
            recorded_by_user_id=self.user.id if self.user else None,
        )
        try:
            if current is not None:
                # Three steps, so neither the foreign key nor the one-current-value
                # index (keyed on ``superseded_at IS NULL``) is ever broken: the old
                # row leaves the index, the new row arrives, then the link is set.
                current.superseded_at = datetime.now(UTC)
                await self.db.flush()
                self.db.add(new)
                await self.db.flush()
                current.superseded_by_id = new.id
                await self.db.flush()
            else:
                self.db.add(new)
                await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise CalibrationError(
                "Another value was recorded for this combination at the same time; try again",
                409,
            ) from exc
        logger.info(
            f"Recorded calibration {new.id} ({data.fit_type}, {data.orientation}) "
            f"on printer {printer_id}"
            + (f", superseding {current.id}" if current is not None else "")
        )
        return new

    def _combination(self, printer_id, material_id, filament, data) -> list:
        return [
            Calibration.tenant_id == self.tenant.id,
            Calibration.printer_id == printer_id,
            Calibration.material_type_id == material_id,
            (
                Calibration.filament_type_id == filament.id
                if filament is not None
                else Calibration.filament_type_id.is_(None)
            ),
            Calibration.orientation == data.orientation,
            Calibration.fit_type == data.fit_type,
        ]

    # ----------------------------------------------------------------- reads

    async def get(self, calibration_id: uuid.UUID) -> Calibration:
        calibration = await self.db.scalar(
            select(Calibration).where(
                Calibration.id == calibration_id, Calibration.tenant_id == self.tenant.id
            )
        )
        if calibration is None:
            raise CalibrationError("Calibration not found", 404)
        return calibration

    async def list_for_printer(
        self,
        printer_id: uuid.UUID,
        *,
        current_only: bool = False,
        fit_type: Optional[str] = None,
        orientation: Optional[str] = None,
        material_type_id: Optional[uuid.UUID] = None,
        filament_type_id: Optional[uuid.UUID] = None,
        skip: int = 0,
        limit: int = 200,
    ) -> list[Calibration]:
        await self.printer(printer_id)
        query = select(Calibration).where(
            Calibration.tenant_id == self.tenant.id, Calibration.printer_id == printer_id
        )
        if current_only:
            query = query.where(Calibration.superseded_by_id.is_(None))
        if fit_type is not None:
            query = query.where(Calibration.fit_type == fit_type)
        if orientation is not None:
            query = query.where(Calibration.orientation == orientation)
        if material_type_id is not None:
            query = query.where(Calibration.material_type_id == material_type_id)
        if filament_type_id is not None:
            query = query.where(Calibration.filament_type_id == filament_type_id)
        query = query.order_by(Calibration.created_at.desc(), Calibration.id).offset(skip)
        return list((await self.db.execute(query.limit(limit))).scalars())

    async def lookup(
        self,
        printer_id: uuid.UUID,
        fit_type: str,
        orientation: str,
        material_type_id: Optional[uuid.UUID],
        material_code: Optional[str],
        filament_type_id: Optional[uuid.UUID],
    ) -> tuple[Optional[Calibration], Optional[str]]:
        """The value that applies, and whether it matched on the filament or the material."""
        await self.printer(printer_id)
        material = await resolve_material(self.db, material_type_id, material_code)
        filament = await self.filament(filament_type_id)
        if material is None:
            if filament is None:
                raise CalibrationError("Give the material (`material` or `material_type_id`)")
            material = await self.db.get(MaterialType, filament.material_type_id)
        base = [
            Calibration.tenant_id == self.tenant.id,
            Calibration.printer_id == printer_id,
            Calibration.material_type_id == material.id,
            Calibration.orientation == orientation,
            Calibration.fit_type == fit_type,
            Calibration.superseded_by_id.is_(None),
        ]
        if filament is not None:
            found = await self.db.scalar(
                select(Calibration).where(*base, Calibration.filament_type_id == filament.id)
            )
            if found is not None:
                return found, "filament"
        found = await self.db.scalar(
            select(Calibration).where(*base, Calibration.filament_type_id.is_(None))
        )
        return (found, "material") if found is not None else (None, None)

    # ----------------------------------------------------------------- output

    async def to_responses(self, rows: list[Calibration]) -> list[CalibrationResponse]:
        printers = (
            {
                p.id: p.name
                for p in (
                    await self.db.execute(
                        select(Printer).where(Printer.id.in_({r.printer_id for r in rows}))
                    )
                ).scalars()
            }
            if rows
            else {}
        )
        materials = (
            {
                m.id: m.code
                for m in (
                    await self.db.execute(
                        select(MaterialType).where(
                            MaterialType.id.in_({r.material_type_id for r in rows})
                        )
                    )
                ).scalars()
            }
            if rows
            else {}
        )
        filament_ids = {r.filament_type_id for r in rows if r.filament_type_id}
        filaments = (
            {
                f.id: filament_label(f)
                for f in (
                    await self.db.execute(
                        select(FilamentType).where(FilamentType.id.in_(filament_ids))
                    )
                ).scalars()
            }
            if filament_ids
            else {}
        )
        user_ids = {r.recorded_by_user_id for r in rows if r.recorded_by_user_id}
        people = (
            {
                u.id: PersonRef(id=u.id, name=u.full_name or u.email)
                for u in (
                    await self.db.execute(select(User).where(User.id.in_(user_ids)))
                ).scalars()
            }
            if user_ids
            else {}
        )
        return [
            CalibrationResponse(
                id=r.id,
                printer_id=r.printer_id,
                printer_name=printers.get(r.printer_id),
                material_type_id=r.material_type_id,
                material_code=materials.get(r.material_type_id),
                filament_type_id=r.filament_type_id,
                filament_label=filaments.get(r.filament_type_id),
                orientation=r.orientation,
                fit_type=r.fit_type,
                value_mm=r.value_mm,
                provenance=r.provenance,
                source_print_job_id=r.source_print_job_id,
                source_test_result_id=r.source_test_result_id,
                measured_at=r.measured_at,
                notes=r.notes,
                recorded_by=people.get(r.recorded_by_user_id),
                superseded_by_id=r.superseded_by_id,
                superseded_at=r.superseded_at,
                is_current=r.superseded_by_id is None,
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def atelier_export(self, printer_id: Optional[uuid.UUID]) -> list[AtelierCalibration]:
        """Current values in the shape of Preflight's ``atelier.yaml`` ``calibrations:``."""
        query = select(Calibration).where(
            Calibration.tenant_id == self.tenant.id, Calibration.superseded_by_id.is_(None)
        )
        if printer_id is not None:
            await self.printer(printer_id)
            query = query.where(Calibration.printer_id == printer_id)
        rows = list(
            (
                await self.db.execute(
                    query.order_by(Calibration.printer_id, Calibration.created_at)
                )
            ).scalars()
        )
        return [
            AtelierCalibration(
                id=r.id,
                printer=response.printer_name or str(r.printer_id),
                printer_id=r.printer_id,
                material=response.material_code or "",
                filament=response.filament_label,
                orientation=r.orientation,
                fit=r.fit_type,
                value_mm=r.value_mm,
                provenance=r.provenance,
                measured_at=r.measured_at.isoformat(),
                source_print_job_id=r.source_print_job_id,
            )
            for r, response in zip(rows, await self.to_responses(rows))
        ]
