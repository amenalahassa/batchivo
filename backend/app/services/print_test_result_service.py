"""Print test results: record, correct, list, photo (spec 009, US4, research R7).

Rules (clarification Q3): a result names a print job, a model file version, or
both; a critical-zone or full-part test must name the version it tested. Every
id must belong to the shop; a version must belong to the model given, and to
the print job's model when the job has one. The model is taken from the
version, else the job. The photo goes through ``ImageStorage`` under the
``print_tests`` owner type and is served to signed-in users of the shop only.
"""

import logging
import uuid
from typing import Optional

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.filament_type import FilamentType
from app.models.material import MaterialType
from app.models.model import Model
from app.models.model_file_version import ModelFileVersion
from app.models.print_job import PrintJob
from app.models.print_test_result import PART_TEST_KINDS, PrintTestResult
from app.models.printer import Printer
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.model_file_version import PersonRef
from app.schemas.print_test_result import (
    PrintTestResultCreate,
    PrintTestResultResponse,
    PrintTestResultUpdate,
)
from app.services.calibration_service import CalibrationError, resolve_material
from app.services.image_storage import ImageStorage, ImageStorageError, get_image_storage

logger = logging.getLogger(__name__)

PHOTO_OWNER_TYPE = "print_tests"


class TestResultError(Exception):
    """A request the service refuses; ``status_code`` is the HTTP status to answer."""

    __test__ = False  # not a pytest class

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class PrintTestResultService:
    """A tenant's print test results."""

    def __init__(
        self,
        db: AsyncSession,
        tenant: Tenant,
        user: Optional[User] = None,
        storage: Optional[ImageStorage] = None,
    ):
        self.db = db
        self.tenant = tenant
        self.user = user
        self.storage = storage or get_image_storage()

    async def _owned(self, model, row_id: Optional[uuid.UUID], label: str):
        if row_id is None:
            return None
        row = await self.db.scalar(
            select(model).where(model.id == row_id, model.tenant_id == self.tenant.id)
        )
        if row is None:
            raise TestResultError(f"{label} not found", 404)
        return row

    async def create(self, data: PrintTestResultCreate) -> PrintTestResult:
        if data.model_file_version_id is None and data.print_job_id is None:
            raise TestResultError("Name the print job or the model version that was tested")
        if data.kind in PART_TEST_KINDS and data.model_file_version_id is None:
            raise TestResultError("A critical-zone or full-part test must name the model version")

        version = await self._owned(ModelFileVersion, data.model_file_version_id, "Model version")
        job = await self._owned(PrintJob, data.print_job_id, "Print job")
        model = await self._owned(Model, data.model_id, "Model")
        await self._owned(Printer, data.printer_id, "Printer")
        await self._owned(FilamentType, data.filament_type_id, "Filament type")
        try:
            material = await resolve_material(self.db, data.material_type_id, data.material)
        except CalibrationError as exc:
            raise TestResultError(exc.message, exc.status_code) from exc

        model_id = model.id if model else None
        if version is not None:
            if model_id is not None and version.model_id != model_id:
                raise TestResultError("That version is not one of this model's")
            if job is not None and job.model_id is not None and job.model_id != version.model_id:
                raise TestResultError("The print job printed another model than that version's")
            model_id = version.model_id
        elif job is not None and job.model_id is not None:
            if model_id is not None and job.model_id != model_id:
                raise TestResultError("The print job printed another model")
            model_id = job.model_id

        user_id = self.user.id if self.user else None
        result = PrintTestResult(
            tenant_id=self.tenant.id,
            kind=data.kind,
            outcome=data.outcome,
            model_id=model_id,
            model_file_version_id=data.model_file_version_id,
            print_job_id=data.print_job_id,
            printer_id=data.printer_id or (job.assigned_printer_id if job else None),
            material_type_id=material.id if material else None,
            filament_type_id=data.filament_type_id,
            orientation=data.orientation,
            measurements=data.measurements,
            failure_mode=data.failure_mode,
            notes=data.notes,
            recorded_by_user_id=user_id,
            updated_by_user_id=user_id,
        )
        self.db.add(result)
        await self.db.flush()
        logger.info(f"Recorded {data.outcome} test result {result.id} ({data.kind})")
        return result

    async def get(self, result_id: uuid.UUID) -> PrintTestResult:
        return await self._owned(PrintTestResult, result_id, "Test result")

    async def update(self, result: PrintTestResult, data: PrintTestResultUpdate) -> None:
        for field in ("outcome", "measurements", "failure_mode", "notes"):
            if field in data.model_fields_set:
                value = getattr(data, field)
                if value is None and field in ("outcome", "measurements"):
                    raise TestResultError(f"{field} cannot be empty")
                setattr(result, field, value)
        result.updated_by_user_id = self.user.id if self.user else None
        await self.db.flush()

    async def list_results(
        self,
        *,
        model_id: Optional[uuid.UUID] = None,
        model_file_version_id: Optional[uuid.UUID] = None,
        print_job_id: Optional[uuid.UUID] = None,
        printer_id: Optional[uuid.UUID] = None,
        outcome: Optional[str] = None,
        kind: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[PrintTestResult], int]:
        filters = [PrintTestResult.tenant_id == self.tenant.id]
        for column, value in (
            (PrintTestResult.model_id, model_id),
            (PrintTestResult.model_file_version_id, model_file_version_id),
            (PrintTestResult.print_job_id, print_job_id),
            (PrintTestResult.printer_id, printer_id),
            (PrintTestResult.outcome, outcome),
            (PrintTestResult.kind, kind),
        ):
            if value is not None:
                filters.append(column == value)
        total = await self.db.scalar(
            select(func.count()).select_from(PrintTestResult).where(*filters)
        )
        rows = (
            await self.db.execute(
                select(PrintTestResult)
                .where(*filters)
                .order_by(PrintTestResult.created_at.desc(), PrintTestResult.id)
                .offset(skip)
                .limit(limit)
            )
        ).scalars()
        return list(rows), int(total or 0)

    # ----------------------------------------------------------------- photo

    async def save_photo(self, result: PrintTestResult, upload: UploadFile) -> None:
        """Store the photo (replacing an earlier one); a bad file is refused, nothing stored."""
        content = await upload.read()
        try:
            stored = await self.storage.save_image(
                content,
                upload.content_type or "application/octet-stream",
                str(result.id),
                original_filename=upload.filename,
                owner_type=PHOTO_OWNER_TYPE,
            )
        except ImageStorageError as exc:
            raise TestResultError(str(exc)) from exc
        previous = (result.photo_url, result.photo_thumbnail_url)
        result.photo_url = stored["image_url"]
        result.photo_thumbnail_url = stored["thumbnail_url"]
        result.photo_content_type = stored["content_type"]
        result.photo_original_filename = (upload.filename or "")[:255] or None
        result.updated_by_user_id = self.user.id if self.user else None
        await self.db.flush()
        if previous[0]:
            await self.storage.delete_image(previous[0], previous[1])

    async def open_photo(self, result: PrintTestResult, variant: str) -> tuple[bytes, str]:
        url = result.photo_thumbnail_url if variant == "thumb" else result.photo_url
        if not url:
            raise TestResultError("This result has no photo", 404)
        try:
            content, content_type = await self.storage.get_image(url)
        except ImageStorageError as exc:
            raise TestResultError("Photo not found", 404) from exc
        return content, result.photo_content_type or content_type

    # ----------------------------------------------------------------- output

    async def to_responses(self, rows: list[PrintTestResult]) -> list[PrintTestResultResponse]:
        async def names(model, column, ids):
            ids = {i for i in ids if i}
            if not ids:
                return {}
            found = await self.db.execute(select(model.id, column).where(model.id.in_(ids)))
            return dict(found.all())

        models = await names(Model, Model.name, (r.model_id for r in rows))
        versions = await names(
            ModelFileVersion, ModelFileVersion.label, (r.model_file_version_id for r in rows)
        )
        materials = await names(MaterialType, MaterialType.code, (r.material_type_id for r in rows))
        user_ids = {r.recorded_by_user_id for r in rows} | {r.updated_by_user_id for r in rows}
        user_ids.discard(None)
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
            PrintTestResultResponse(
                id=r.id,
                kind=r.kind,
                outcome=r.outcome,
                model_id=r.model_id,
                model_name=models.get(r.model_id),
                model_file_version_id=r.model_file_version_id,
                version_label=versions.get(r.model_file_version_id),
                print_job_id=r.print_job_id,
                printer_id=r.printer_id,
                material_type_id=r.material_type_id,
                material_code=materials.get(r.material_type_id),
                filament_type_id=r.filament_type_id,
                orientation=r.orientation,
                measurements=r.measurements or [],
                failure_mode=r.failure_mode,
                notes=r.notes,
                photo_available=bool(r.photo_url),
                recorded_by=people.get(r.recorded_by_user_id),
                updated_by=people.get(r.updated_by_user_id),
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
