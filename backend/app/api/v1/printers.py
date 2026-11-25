"""Printer management API endpoints."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.provenance_http import (
    record_operator_origins,
    refuse_observed_or_409,
    served_origins,
)
from app.auth.dependencies import (
    CurrentTenant,
    CurrentUser,
    RequireAdmin,
    RequireMember,
    TenantDB,
    role_in_tenant,
)
from app.schemas.printer import (
    PowerReadingBatch,
    PowerReadingResult,
    PrinterCostPolicyResponse,
    PrinterCostPolicyUpdate,
    PrinterCreate,
    PrinterListResponse,
    PrinterModelResponse,
    PrinterResponse,
    PrinterUpdate,
)
from app.services.printer_service import PrinterService
from app.tasks.power import PowerReading, ingest_power_readings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models", response_model=list[PrinterModelResponse])
async def list_printer_models() -> list[PrinterModelResponse]:
    """
    List all known printer models from the registry.

    Returns model metadata including connection type, AMS support, and toolhead
    changer info.  No authentication required — these are static registry entries.
    """
    from app.services.printer_registry import list_printer_models as _list_models

    return [
        PrinterModelResponse(
            model_key=m.model_key,
            display_name=m.display_name,
            manufacturer=m.manufacturer,
            connection_type=m.connection_type,
            has_toolhead_changer=m.has_toolhead_changer,
            has_ams=m.has_ams,
        )
        for m in _list_models()
    ]


@router.post("", response_model=PrinterResponse, status_code=status.HTTP_201_CREATED)
async def create_printer(
    printer_data: PrinterCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> PrinterResponse:
    """
    Create a new printer.

    Requires authentication.
    Printer will be associated with current tenant.
    """
    service = PrinterService(db, tenant, user)
    printer = await service.create_printer(printer_data)
    return PrinterResponse.model_validate(printer)


@router.get("", response_model=PrinterListResponse)
async def list_printers(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max items to return"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
) -> PrinterListResponse:
    """
    List all printers for current tenant with pagination.

    Supports:
    - Pagination (skip, limit)
    - Filter by active status
    """
    service = PrinterService(db, tenant, user)
    return await service.list_printers(skip=skip, limit=limit, is_active=is_active)


@router.get("/{printer_id}", response_model=PrinterResponse)
async def get_printer(
    printer_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> PrinterResponse:
    """
    Get printer details by ID.

    Requires authentication.
    Printer must belong to current tenant.
    """
    service = PrinterService(db, tenant, user)
    printer = await service.get_printer(printer_id)

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found",
        )

    return PrinterResponse.model_validate(printer)


@router.put("/{printer_id}", response_model=PrinterResponse)
async def update_printer(
    printer_id: UUID,
    printer_data: PrinterUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> PrinterResponse:
    """
    Update an existing printer.

    Requires authentication.
    Printer must belong to current tenant.
    """
    service = PrinterService(db, tenant, user)
    printer = await service.update_printer(printer_id, printer_data)

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found",
        )

    return PrinterResponse.model_validate(printer)


@router.delete("/{printer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_printer(
    printer_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
):
    """
    Delete a printer (soft delete by setting is_active=False).

    Requires authentication.
    Printer must belong to current tenant.
    """
    service = PrinterService(db, tenant, user)
    result = await service.delete_printer(printer_id)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found",
        )


# ============================================================================
# Machine cost policy (task T046)
# ============================================================================


#: The machine cost policy's figures, in the order the form shows them.
COST_POLICY_FIELDS: tuple[str, ...] = (
    "purchase_price",
    "expected_lifetime_hours",
    "maintenance_reserve_total",
    "measured_watts",
    "electricity_rate_per_kwh",
)


async def _cost_policy_response(
    printer,
    db: AsyncSession,
    tenant,
) -> PrinterCostPolicyResponse:
    """Derive the machine rate, with the tenant policy as the rate fallback."""
    from app.services.pricing_policy import resolve_cost_policy

    policy = await resolve_cost_policy(db, tenant)
    derived = printer.machine_rate_components(policy.electricity_rate_per_kwh)

    effective_rate = printer.electricity_rate_per_kwh
    if effective_rate is None:
        effective_rate = policy.electricity_rate_per_kwh

    return PrinterCostPolicyResponse(
        printer_id=printer.id,
        purchase_price=printer.purchase_price,
        expected_lifetime_hours=printer.expected_lifetime_hours,
        maintenance_reserve_total=printer.maintenance_reserve_total,
        measured_watts=printer.measured_watts,
        electricity_rate_per_kwh=printer.electricity_rate_per_kwh,
        effective_electricity_rate_per_kwh=effective_rate,
        machine_rate_per_hour=derived["total"],
        components=derived["components"],
        missing=derived["missing"],
        origins=await served_origins(
            db,
            tenant,
            entity_type="printer",
            entity_id=printer.id,
            fields=COST_POLICY_FIELDS,
            staleness_threshold_days=policy.staleness_threshold_days,
        ),
    )


@router.get("/{printer_id}/cost-policy", response_model=PrinterCostPolicyResponse)
async def get_printer_cost_policy(
    printer_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> PrinterCostPolicyResponse:
    """This printer's machine cost policy and the hourly rate it implies.

    Readable by every role: a figure nobody can see is a figure nobody can
    check. The response carries the rate's component parts so it can be
    explained without being recomputed (FR-018), and names any input the
    operator has not supplied rather than costing it at zero (FR-019).
    """
    service = PrinterService(db, tenant, user)
    printer = await service.get_printer(printer_id)

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found",
        )

    return await _cost_policy_response(printer, db, tenant)


@router.put("/{printer_id}/cost-policy", response_model=PrinterCostPolicyResponse)
async def update_printer_cost_policy(
    printer_id: UUID,
    policy_data: PrinterCostPolicyUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> PrinterCostPolicyResponse:
    """Set this printer's machine cost policy. Requires admin or owner.

    Fields the body does not name are left alone, so entering the power draw
    later does not erase the purchase price entered today.

    Each figure that moves records where it came from (FR-001, task T229): the
    purchase price, lifetime, maintenance reserve and electricity rate as
    `policy` with the administrator's role, and the measured draw as
    `measured`. A draw telemetry has observed is refused rather than typed
    over (FR-004) -- it is refreshed by the plug, through the variance path.
    """
    service = PrinterService(db, tenant, user)
    printer = await service.get_printer(printer_id)

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found",
        )

    changes = policy_data.model_dump(exclude_none=True)
    fields = await refuse_observed_or_409(
        db, tenant, entity_type="printer", entity=printer, changes=changes
    )
    for field, value in changes.items():
        setattr(printer, field, value)

    db.add(printer)
    await record_operator_origins(
        db,
        tenant,
        entity_type="printer",
        entity_id=printer.id,
        fields=fields,
        user=user,
        role=await role_in_tenant(db, user.id, tenant.id),
    )
    await db.commit()
    await db.refresh(printer)
    logger.info(
        f"Updated cost policy for printer {printer.id} "
        f"(fields: {', '.join(sorted(changes)) or 'none'})"
    )

    return await _cost_policy_response(printer, db, tenant)


@router.post(
    "/{printer_id}/power-readings",
    response_model=PowerReadingResult,
    status_code=status.HTTP_200_OK,
)
async def record_power_readings(
    printer_id: UUID,
    batch: PowerReadingBatch,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> PowerReadingResult:
    """Record smart-plug readings of this machine's draw. Any member may.

    A measured draw is a measurement rather than a decision, so FR-007b puts
    it with the member who takes it. It is the one cost input where a cheap
    sensor beats any estimate: a printer's nameplate rating is roughly twice
    its printing draw, so an operator who typed the nameplate is over-costing
    every print on that machine.

    The readings do not overwrite the figure. They go through
    `variance_service` like any other observation -- a rolling average once
    enough of them agree (FR-042a), held as a proposal beyond the operator's
    divergence threshold (FR-042b), and never touching a figure the operator
    set themselves (FR-042g). A plug reporting kilowatts where watts were
    expected lands in the second case, which is the whole reason a reading
    does not simply overwrite.

    Before this route the ingestion existed and nothing called it: no
    endpoint, no schedule, no caller in `app/`, so `measured_watts` could
    never acquire an observed origin and the power-draw share SC-010 counts
    was unreachable in a running system (task T159).

    Done in the request rather than queued. The work is a handful of rows and
    an operator posting a reading wants the answer -- applied, or held, and
    why -- rather than a job id; the Celery task over the same function stays
    the entry point for a bulk plug integration.
    """
    service = PrinterService(db, tenant, user)
    printer = await service.get_printer(printer_id)

    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Printer not found",
        )

    readings: list[PowerReading] = [
        (entry.source_id, entry.watts, entry.observed_on) for entry in batch.readings
    ]
    decision = await ingest_power_readings(db, tenant, printer, readings, user=user)
    await db.commit()
    await db.refresh(printer)

    logger.info(
        f"Printer {printer.id}: considered {len(readings)} power reading(s) -- "
        f"{'applied' if decision.applied else 'not applied'}: {decision.reason}"
    )

    return PowerReadingResult(
        printer_id=printer.id,
        readings_accepted=len(decision.run_ids),
        applied=decision.applied,
        reason=decision.reason,
        observed_value=decision.observed_value,
        divergence_pct=decision.divergence,
        proposal_id=decision.proposal.id if decision.proposal is not None else None,
        superseded_proposal_id=decision.superseded_id,
        measured_watts=printer.measured_watts,
    )
