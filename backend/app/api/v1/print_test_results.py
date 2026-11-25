"""Print test result API (spec 009, contracts/api.md "Print test results").

Viewers read; members and above record and correct. The photo is served only
to signed-in users of the shop (``Cache-Control: private``), like idea images.
"""

from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile, status

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.schemas.print_test_result import (
    PrintTestKind,
    PrintTestOutcome,
    PrintTestResultCreate,
    PrintTestResultList,
    PrintTestResultResponse,
    PrintTestResultUpdate,
)
from app.services.print_test_result_service import PrintTestResultService, TestResultError

router = APIRouter()


def _error(exc: TestResultError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


async def _one(service: PrintTestResultService, result) -> PrintTestResultResponse:
    return (await service.to_responses([result]))[0]


@router.post(
    "/print-test-results",
    response_model=PrintTestResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_test_result(
    data: PrintTestResultCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> PrintTestResultResponse:
    """Record how a printed test piece did."""
    service = PrintTestResultService(db, tenant, user)
    try:
        result = await service.create(data)
    except TestResultError as exc:
        raise _error(exc) from exc
    await db.commit()
    await db.refresh(result)
    return await _one(service, result)


@router.get("/print-test-results", response_model=PrintTestResultList)
async def list_test_results(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    model_id: Optional[UUID] = None,
    model_file_version_id: Optional[UUID] = None,
    print_job_id: Optional[UUID] = None,
    printer_id: Optional[UUID] = None,
    outcome: Optional[PrintTestOutcome] = None,
    kind: Optional[PrintTestKind] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PrintTestResultList:
    """Test results, newest first."""
    service = PrintTestResultService(db, tenant, user)
    rows, total = await service.list_results(
        model_id=model_id,
        model_file_version_id=model_file_version_id,
        print_job_id=print_job_id,
        printer_id=printer_id,
        outcome=outcome,
        kind=kind,
        skip=skip,
        limit=limit,
    )
    return PrintTestResultList(items=await service.to_responses(rows), total=total)


@router.get("/print-test-results/{result_id}", response_model=PrintTestResultResponse)
async def get_test_result(
    result_id: UUID, user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> PrintTestResultResponse:
    """One test result."""
    service = PrintTestResultService(db, tenant, user)
    try:
        result = await service.get(result_id)
    except TestResultError as exc:
        raise _error(exc) from exc
    return await _one(service, result)


@router.patch("/print-test-results/{result_id}", response_model=PrintTestResultResponse)
async def update_test_result(
    result_id: UUID,
    data: PrintTestResultUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> PrintTestResultResponse:
    """Correct a result's outcome, measurements, failure mode or notes."""
    service = PrintTestResultService(db, tenant, user)
    try:
        result = await service.get(result_id)
        await service.update(result, data)
    except TestResultError as exc:
        raise _error(exc) from exc
    await db.commit()
    await db.refresh(result)
    return await _one(service, result)


@router.post("/print-test-results/{result_id}/photo", response_model=PrintTestResultResponse)
async def upload_test_result_photo(
    result_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
    file: UploadFile = File(...),
) -> PrintTestResultResponse:
    """Attach (or replace) the result's photo."""
    service = PrintTestResultService(db, tenant, user)
    try:
        result = await service.get(result_id)
        await service.save_photo(result, file)
    except TestResultError as exc:
        raise _error(exc) from exc
    await db.commit()
    await db.refresh(result)
    return await _one(service, result)


@router.get("/print-test-results/{result_id}/photo")
async def get_test_result_photo(
    result_id: UUID,
    request: Request,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    variant: Literal["full", "thumb"] = "full",
) -> Response:
    """The result's photo, only for a signed-in user of the shop."""
    service = PrintTestResultService(db, tenant, user)
    try:
        result = await service.get(result_id)
        content, content_type = await service.open_photo(result, variant)
    except TestResultError as exc:
        raise _error(exc) from exc
    etag = f'"{result.id}-{variant}-{int(result.updated_at.timestamp())}"'
    headers = {"Cache-Control": "private, max-age=3600", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(content=content, media_type=content_type, headers=headers)
