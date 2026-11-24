"""Print send API: prepare, confirm and follow prints sent to Bambu printers (spec 011).

Mounted under ``/api/v1/printers``. Nothing here starts a print except
``POST /{printer_id}/prints/confirm`` with a token from a prepared summary;
an MCP client (spec 010) calls the same two endpoints as the web app.
See ``specs/011-bambu-print-send/contracts/print-send-api.md``.
"""

import json
import logging
from typing import NoReturn, Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.models.printer_connection import ConnectionType, PrinterConnection
from app.schemas.print_send import (
    AmsMapping,
    ConsumptionAccept,
    FileTransferTestResult,
    PrintSendConfirm,
    PrintSendListResponse,
    PrintSendPrepared,
    PrintSendResponse,
)
from app.services import bambu_ftps
from app.services.print_send_service import (
    PrintSendError,
    PrintSendService,
    summary_fields,
    to_response,
)
from app.services.printer_secrets import get_access_code

logger = logging.getLogger(__name__)

router = APIRouter()


def _raise(error: PrintSendError) -> NoReturn:
    raise HTTPException(
        status_code=error.status_code, detail={"code": error.code, "message": error.message}
    )


def _parse_mapping(raw: str) -> AmsMapping:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_mapping", "message": "ams_mapping must be JSON"},
        ) from None
    try:
        return AmsMapping(entries=data)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "invalid_mapping",
                "message": "; ".join(err["msg"] for err in e.errors()),
            },
        ) from None


# ============================================
# Prepare / confirm
# ============================================


@router.post(
    "/{printer_id}/prints/prepare",
    response_model=PrintSendPrepared,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_print_send(
    printer_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
    plate: int = Form(..., ge=1, description="Plate number in the sliced file"),
    ams_mapping: str = Form(..., description="JSON list of {filament_id, slot}"),
    model_file_id: Optional[UUID] = Form(None),
    attach_to_model_id: Optional[UUID] = Form(None),
    file: Optional[UploadFile] = File(None, description="Sliced .gcode.3mf"),
) -> PrintSendPrepared:
    """Build the summary of a send and return it with a single-use confirmation token.

    Sends nothing to the printer and creates no print job (FR-002).
    """
    mapping = _parse_mapping(ams_mapping)
    upload_content = await file.read() if file is not None else None
    service = PrintSendService(db, tenant, user)
    try:
        send, token = await service.prepare(
            printer_id,
            plate=plate,
            mapping=mapping,
            model_file_id=model_file_id,
            upload_name=file.filename if file is not None else None,
            upload_content=upload_content,
            attach_to_model_id=attach_to_model_id,
        )
    except PrintSendError as e:
        _raise(e)
    return PrintSendPrepared(**summary_fields(send), confirmation_token=token)


@router.post("/{printer_id}/prints/confirm", response_model=PrintSendResponse)
async def confirm_print_send(
    printer_id: UUID,
    body: PrintSendConfirm,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> PrintSendResponse:
    """Start the print of a prepared summary. The only route that starts a print."""
    service = PrintSendService(db, tenant, user)
    try:
        send = await service.confirm(
            printer_id, body.confirmation_token, acknowledge_warnings=body.acknowledge_warnings
        )
    except PrintSendError as e:
        _raise(e)
    return to_response(send)


# ============================================
# Reads
# ============================================


@router.get("/{printer_id}/prints", response_model=PrintSendListResponse)
async def list_print_sends(
    printer_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    limit: int = Query(20, ge=1, le=50),
) -> PrintSendListResponse:
    """Recent sends of a printer, newest first (never the tokens)."""
    service = PrintSendService(db, tenant, user)
    try:
        sends = await service.list_sends(printer_id, limit)
    except PrintSendError as e:
        _raise(e)
    return PrintSendListResponse(items=[to_response(s) for s in sends])


@router.get("/{printer_id}/prints/{send_id}", response_model=PrintSendResponse)
async def get_print_send(
    printer_id: UUID,
    send_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> PrintSendResponse:
    service = PrintSendService(db, tenant, user)
    try:
        send = await service.get_send(printer_id, send_id)
    except PrintSendError as e:
        _raise(e)
    return to_response(send)


# ============================================
# Spool deduction proposal (FR-020)
# ============================================


@router.post("/{printer_id}/prints/{send_id}/consumption/accept", response_model=PrintSendResponse)
async def accept_print_consumption(
    printer_id: UUID,
    send_id: UUID,
    body: ConsumptionAccept,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> PrintSendResponse:
    """Deduct the accepted grams from each spool, once."""
    service = PrintSendService(db, tenant, user)
    try:
        send = await service.accept_consumption(printer_id, send_id, body.lines)
    except PrintSendError as e:
        _raise(e)
    return to_response(send)


@router.post("/{printer_id}/prints/{send_id}/consumption/dismiss", response_model=PrintSendResponse)
async def dismiss_print_consumption(
    printer_id: UUID,
    send_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> PrintSendResponse:
    service = PrintSendService(db, tenant, user)
    try:
        send = await service.dismiss_consumption(printer_id, send_id)
    except PrintSendError as e:
        _raise(e)
    return to_response(send)


# ============================================
# Developer Mode: file transfer test (FR-012a)
# ============================================


@router.post("/{printer_id}/connection/test-file-transfer", response_model=FileTransferTestResult)
async def test_file_transfer(
    printer_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> FileTransferTestResult:
    """Check that the printer accepts a file connection. Writes nothing on the printer."""
    connection = (
        await db.execute(
            select(PrinterConnection).where(
                PrinterConnection.printer_id == printer_id,
                PrinterConnection.tenant_id == tenant.id,
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No connection configured for this printer",
        )
    if connection.connection_type != ConnectionType.BAMBU_LAN.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="File transfer is only available for Bambu LAN connections",
        )
    access_code = get_access_code(connection)
    if not connection.ip_address or not access_code:
        return FileTransferTestResult(
            ok=False, message="Set the printer's IP address and access code first"
        )
    ok, message = await bambu_ftps.check_login(connection.ip_address, access_code)
    return FileTransferTestResult(ok=ok, message=message)
