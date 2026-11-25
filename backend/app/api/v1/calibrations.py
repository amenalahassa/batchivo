"""Fit calibration API (spec 009, contracts/api.md "Calibrations").

Calibrations are recorded and read, never edited or deleted: there is no PUT,
PATCH or DELETE route (principle VI). Viewers read; members and above record.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.schemas.calibration import (
    AtelierCalibrations,
    CalibrationCreate,
    CalibrationLookup,
    CalibrationResponse,
    FitType,
    Orientation,
)
from app.services.calibration_service import CalibrationError, CalibrationService

router = APIRouter()


def _error(exc: CalibrationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/printers/{printer_id}/calibrations", response_model=list[CalibrationResponse])
async def list_printer_calibrations(
    printer_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    current_only: bool = False,
    fit_type: Optional[FitType] = None,
    orientation: Optional[Orientation] = None,
    material_type_id: Optional[UUID] = None,
    filament_type_id: Optional[UUID] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> list[CalibrationResponse]:
    """A printer's calibrations, current and superseded, newest first."""
    service = CalibrationService(db, tenant, user)
    try:
        rows = await service.list_for_printer(
            printer_id,
            current_only=current_only,
            fit_type=fit_type,
            orientation=orientation,
            material_type_id=material_type_id,
            filament_type_id=filament_type_id,
            skip=skip,
            limit=limit,
        )
    except CalibrationError as exc:
        raise _error(exc) from exc
    return await service.to_responses(rows)


@router.post(
    "/printers/{printer_id}/calibrations",
    response_model=CalibrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_calibration(
    printer_id: UUID,
    data: CalibrationCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> CalibrationResponse:
    """Record a fit value; the current value of the same combination is superseded."""
    service = CalibrationService(db, tenant, user)
    try:
        calibration = await service.record(printer_id, data)
    except CalibrationError as exc:
        raise _error(exc) from exc
    await db.commit()
    await db.refresh(calibration)
    return (await service.to_responses([calibration]))[0]


@router.get("/calibrations/lookup", response_model=CalibrationLookup)
async def lookup_calibration(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    printer_id: UUID,
    fit_type: FitType,
    orientation: Orientation,
    material_type_id: Optional[UUID] = None,
    material: Optional[str] = Query(None, max_length=20, description="Material code, e.g. PLA"),
    filament_type_id: Optional[UUID] = None,
) -> CalibrationLookup:
    """The value that applies: filament-specific, else material-level, else none."""
    service = CalibrationService(db, tenant, user)
    try:
        found, matched_on = await service.lookup(
            printer_id, fit_type, orientation, material_type_id, material, filament_type_id
        )
    except CalibrationError as exc:
        raise _error(exc) from exc
    if found is None:
        return CalibrationLookup(found=False)
    response = (await service.to_responses([found]))[0]
    return CalibrationLookup(found=True, calibration=response, matched_on=matched_on)


@router.get("/calibrations/atelier", response_model=AtelierCalibrations)
async def export_atelier_calibrations(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    printer_id: Optional[UUID] = None,
) -> AtelierCalibrations:
    """Current values in the shape of Preflight's ``atelier.yaml`` ``calibrations:`` list."""
    service = CalibrationService(db, tenant, user)
    try:
        items = await service.atelier_export(printer_id)
    except CalibrationError as exc:
        raise _error(exc) from exc
    return AtelierCalibrations(calibrations=items)


@router.get("/calibrations/{calibration_id}", response_model=CalibrationResponse)
async def get_calibration(
    calibration_id: UUID, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> CalibrationResponse:
    """One calibration."""
    service = CalibrationService(db, tenant, user)
    try:
        calibration = await service.get(calibration_id)
    except CalibrationError as exc:
        raise _error(exc) from exc
    return (await service.to_responses([calibration]))[0]
