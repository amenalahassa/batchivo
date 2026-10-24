"""Admin return request (RMA) management API endpoints.

Handles return approval, receiving, and completion workflow.
Customer-facing return submission is in customer_account.py.
"""

import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, desc
from sqlalchemy.orm import selectinload

from app.auth.dependencies import (
    CurrentTenant,
    CurrentUser,
    RequireAdmin,
    RequireMember,
    TenantDB,
)
from app.services.refund_actuals import record_refund
from app.models.return_request import (
    ReturnItem,
    ReturnRequest,
    ReturnStatus,
)
from app.schemas.return_request import (
    ReturnItemResponse,
    ReturnRequestAdminListResponse,
    ReturnRequestAdminResponse,
    ReturnRequestApprove,
    ReturnRequestComplete,
    ReturnRequestReceive,
    ReturnRequestReject,
    ReturnRequestUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_item_response(item: ReturnItem) -> ReturnItemResponse:
    """Build return item response with order item info."""
    return ReturnItemResponse(
        id=item.id,
        order_item_id=item.order_item_id,
        quantity=item.quantity,
        reason=item.reason,
        condition_notes=item.condition_notes,
        is_restockable=item.is_restockable,
        product_name=item.order_item.product_name if item.order_item else None,
        product_sku=item.order_item.product_sku if item.order_item else None,
        unit_price=item.order_item.unit_price if item.order_item else None,
    )


def _build_admin_response(return_request: ReturnRequest) -> ReturnRequestAdminResponse:
    """Build admin return request response."""
    return ReturnRequestAdminResponse(
        id=return_request.id,
        tenant_id=return_request.tenant_id,
        rma_number=return_request.rma_number,
        order_id=return_request.order_id,
        customer_id=return_request.customer_id,
        customer_email=return_request.customer_email,
        customer_name=return_request.customer_name,
        status=return_request.status,
        reason=return_request.reason,
        reason_details=return_request.reason_details,
        requested_action=return_request.requested_action,
        admin_notes=return_request.admin_notes,
        rejection_reason=return_request.rejection_reason,
        approved_at=return_request.approved_at,
        approved_by=return_request.approved_by,
        received_at=return_request.received_at,
        received_by=return_request.received_by,
        completed_at=return_request.completed_at,
        completed_by=return_request.completed_by,
        refund_amount=return_request.refund_amount,
        refund_reference=return_request.refund_reference,
        replacement_order_id=return_request.replacement_order_id,
        return_tracking_number=return_request.return_tracking_number,
        return_label_url=return_request.return_label_url,
        created_at=return_request.created_at,
        updated_at=return_request.updated_at,
        items=[_build_item_response(item) for item in return_request.items],
        order_number=return_request.order.order_number if return_request.order else None,
        order_total=return_request.order.total if return_request.order else None,
    )


@router.get("", response_model=ReturnRequestAdminListResponse)
async def list_return_requests(
    db: TenantDB,
    status_filter: Literal[
        "all", "requested", "approved", "received", "completed", "rejected", "cancelled"
    ] = Query("all", alias="status", description="Filter by status"),
    order_id: UUID | None = Query(None, description="Filter by order"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
):
    """
    List all return requests for admin management.

    Filters:
    - status: all, requested, approved, received, completed, rejected, cancelled
    - order_id: Filter to specific order
    """
    # Base query
    query = (
        select(ReturnRequest)
        .where(ReturnRequest.tenant_id == tenant.id)
        .options(
            selectinload(ReturnRequest.items).selectinload(ReturnItem.order_item),
            selectinload(ReturnRequest.order),
        )
    )

    # Apply status filter
    if status_filter != "all":
        status_enum = ReturnStatus(status_filter)
        query = query.where(ReturnRequest.status == status_enum)

    # Filter by order
    if order_id:
        query = query.where(ReturnRequest.order_id == order_id)

    # Count total
    count_query = select(func.count(ReturnRequest.id)).where(ReturnRequest.tenant_id == tenant.id)
    if status_filter != "all":
        count_query = count_query.where(ReturnRequest.status == ReturnStatus(status_filter))
    if order_id:
        count_query = count_query.where(ReturnRequest.order_id == order_id)

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Get paginated results
    query = query.order_by(desc(ReturnRequest.created_at)).offset(skip).limit(limit)
    result = await db.execute(query)
    return_requests = result.scalars().all()

    return ReturnRequestAdminListResponse(
        items=[_build_admin_response(rr) for rr in return_requests],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{return_id}", response_model=ReturnRequestAdminResponse)
async def get_return_request(
    return_id: UUID,
    db: TenantDB,
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
):
    """Get a specific return request by ID."""
    result = await db.execute(
        select(ReturnRequest)
        .where(
            ReturnRequest.id == return_id,
            ReturnRequest.tenant_id == tenant.id,
        )
        .options(
            selectinload(ReturnRequest.items).selectinload(ReturnItem.order_item),
            selectinload(ReturnRequest.order),
        )
    )
    return_request = result.scalar_one_or_none()

    if not return_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Return request not found",
        )

    return _build_admin_response(return_request)


@router.put("/{return_id}", response_model=ReturnRequestAdminResponse)
async def update_return_request(
    return_id: UUID,
    data: ReturnRequestUpdate,
    _member: RequireMember,
    db: TenantDB,
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
):
    """Update a return request (admin notes, tracking, etc.)."""
    result = await db.execute(
        select(ReturnRequest)
        .where(
            ReturnRequest.id == return_id,
            ReturnRequest.tenant_id == tenant.id,
        )
        .options(
            selectinload(ReturnRequest.items).selectinload(ReturnItem.order_item),
            selectinload(ReturnRequest.order),
        )
    )
    return_request = result.scalar_one_or_none()

    if not return_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Return request not found",
        )

    # Update fields
    if data.admin_notes is not None:
        return_request.admin_notes = data.admin_notes
    if data.return_tracking_number is not None:
        return_request.return_tracking_number = data.return_tracking_number
    if data.return_label_url is not None:
        return_request.return_label_url = data.return_label_url

    return_request.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(return_request)

    return _build_admin_response(return_request)


@router.post("/{return_id}/approve", response_model=ReturnRequestAdminResponse)
async def approve_return_request(
    return_id: UUID,
    data: ReturnRequestApprove,
    _member: RequireMember,
    db: TenantDB,
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
):
    """Approve a return request."""
    result = await db.execute(
        select(ReturnRequest)
        .where(
            ReturnRequest.id == return_id,
            ReturnRequest.tenant_id == tenant.id,
        )
        .options(
            selectinload(ReturnRequest.items).selectinload(ReturnItem.order_item),
            selectinload(ReturnRequest.order),
        )
    )
    return_request = result.scalar_one_or_none()

    if not return_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Return request not found",
        )

    if return_request.status != ReturnStatus.REQUESTED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot approve return in status '{return_request.status.value}'",
        )

    return_request.status = ReturnStatus.APPROVED
    return_request.approved_at = datetime.now(timezone.utc)
    return_request.approved_by = user.id
    if data.admin_notes:
        return_request.admin_notes = data.admin_notes
    if data.return_label_url:
        return_request.return_label_url = data.return_label_url
    return_request.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(return_request)

    # Send approval email to customer with return instructions
    try:
        from app.services.email_service import get_email_service

        email_service = get_email_service()
        await email_service.send_return_approved(
            to_email=return_request.customer_email,
            customer_name=return_request.customer_name,
            rma_number=return_request.rma_number,
            order_number=return_request.order.order_number if return_request.order else "N/A",
            return_instructions=data.admin_notes,
            return_label_url=data.return_label_url,
        )
    except Exception as e:
        import logging

        logging.getLogger(__name__).error(f"Failed to send return approval email: {e}")

    return _build_admin_response(return_request)


@router.post("/{return_id}/receive", response_model=ReturnRequestAdminResponse)
async def receive_return_items(
    return_id: UUID,
    data: ReturnRequestReceive,
    _member: RequireMember,
    db: TenantDB,
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
):
    """Mark return items as received."""
    result = await db.execute(
        select(ReturnRequest)
        .where(
            ReturnRequest.id == return_id,
            ReturnRequest.tenant_id == tenant.id,
        )
        .options(
            selectinload(ReturnRequest.items).selectinload(ReturnItem.order_item),
            selectinload(ReturnRequest.order),
        )
    )
    return_request = result.scalar_one_or_none()

    if not return_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Return request not found",
        )

    if return_request.status != ReturnStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot receive return in status '{return_request.status.value}'",
        )

    return_request.status = ReturnStatus.RECEIVED
    return_request.received_at = datetime.now(timezone.utc)
    return_request.received_by = user.id
    if data.admin_notes:
        return_request.admin_notes = data.admin_notes
    return_request.updated_at = datetime.now(timezone.utc)

    # Update item conditions if provided
    if data.item_conditions:
        for condition in data.item_conditions:
            item_id = condition.get("item_id")
            if item_id:
                for item in return_request.items:
                    if str(item.id) == str(item_id):
                        if "condition_notes" in condition:
                            item.condition_notes = condition["condition_notes"]
                        if "is_restockable" in condition:
                            item.is_restockable = condition["is_restockable"]
                        break

    await db.commit()
    await db.refresh(return_request)

    return _build_admin_response(return_request)


@router.post("/{return_id}/complete", response_model=ReturnRequestAdminResponse)
async def complete_return_request(
    return_id: UUID,
    data: ReturnRequestComplete,
    _admin: RequireAdmin,
    db: TenantDB,
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
):
    """Complete a return request (issue refund/replacement).

    Admin only, as `POST /orders/{id}/refund` is: completing writes a
    `RefundActual`, which lowers the order's realised margin (FR-040, T241).
    """
    result = await db.execute(
        select(ReturnRequest)
        .where(
            ReturnRequest.id == return_id,
            ReturnRequest.tenant_id == tenant.id,
        )
        .options(
            selectinload(ReturnRequest.items).selectinload(ReturnItem.order_item),
            selectinload(ReturnRequest.order),
        )
    )
    return_request = result.scalar_one_or_none()

    if not return_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Return request not found",
        )

    if return_request.status != ReturnStatus.RECEIVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot complete return in status '{return_request.status.value}'",
        )

    return_request.status = ReturnStatus.COMPLETED
    return_request.completed_at = datetime.now(timezone.utc)
    return_request.completed_by = user.id
    if data.refund_amount is not None:
        return_request.refund_amount = data.refund_amount

        # Record it against the order as an actual, as well as on the RMA
        # (task T189).
        #
        # `refund_amount` here is the RMA's own record of what was agreed; the
        # pricing engine never opened this table, so a refunded order still
        # reported the margin it earned at sale. Writing a `RefundActual`
        # beside it is what makes `realised_margin` see the money going back
        # (FR-040, SC-001). The RMA row keeps its own figure -- the two answer
        # different questions and neither is derived from the other.
        if return_request.order is not None:
            await record_refund(
                db,
                tenant,
                return_request.order,
                amount=data.refund_amount,
                source="entered",
                reason=f"RMA {return_request.rma_number}",
                recorded_by_user_id=user.id,
            )
        else:
            logger.warning(
                f"RMA {return_request.rma_number} recorded a refund of "
                f"{data.refund_amount} with no order loaded, so nothing was "
                f"recorded against a settled order (FR-040)"
            )
    if data.refund_reference:
        return_request.refund_reference = data.refund_reference
    if data.replacement_order_id:
        return_request.replacement_order_id = data.replacement_order_id
    if data.admin_notes:
        return_request.admin_notes = data.admin_notes
    return_request.updated_at = datetime.now(timezone.utc)

    # Restock items if applicable
    for item in return_request.items:
        if item.is_restockable and item.order_item and item.order_item.product_id:
            from app.models.product import Product

            product_result = await db.execute(
                select(Product).where(Product.id == item.order_item.product_id)
            )
            product = product_result.scalar_one_or_none()
            if product:
                product.units_in_stock += item.quantity

    await db.commit()
    await db.refresh(return_request)

    # Send completion email to customer
    try:
        from app.services.email_service import get_email_service
        from app.models.order import Order

        # Get replacement order number if applicable
        replacement_order_number = None
        if return_request.replacement_order_id:
            order_result = await db.execute(
                select(Order).where(Order.id == return_request.replacement_order_id)
            )
            replacement_order = order_result.scalar_one_or_none()
            if replacement_order:
                replacement_order_number = replacement_order.order_number

        email_service = get_email_service()
        await email_service.send_return_completed(
            to_email=return_request.customer_email,
            customer_name=return_request.customer_name,
            rma_number=return_request.rma_number,
            order_number=return_request.order.order_number if return_request.order else "N/A",
            # The column is `Numeric`, so the read is already exact; the
            # `float()` was the one lossy step before the customer was told
            # what they were refunded (task T190, FR-047).
            refund_amount=return_request.refund_amount,
            replacement_order_number=replacement_order_number,
        )
    except Exception as e:
        import logging

        logging.getLogger(__name__).error(f"Failed to send return completion email: {e}")

    return _build_admin_response(return_request)


@router.post("/{return_id}/reject", response_model=ReturnRequestAdminResponse)
async def reject_return_request(
    return_id: UUID,
    data: ReturnRequestReject,
    _member: RequireMember,
    db: TenantDB,
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
):
    """Reject a return request."""
    result = await db.execute(
        select(ReturnRequest)
        .where(
            ReturnRequest.id == return_id,
            ReturnRequest.tenant_id == tenant.id,
        )
        .options(
            selectinload(ReturnRequest.items).selectinload(ReturnItem.order_item),
            selectinload(ReturnRequest.order),
        )
    )
    return_request = result.scalar_one_or_none()

    if not return_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Return request not found",
        )

    if return_request.status not in [ReturnStatus.REQUESTED, ReturnStatus.APPROVED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot reject return in status '{return_request.status.value}'",
        )

    return_request.status = ReturnStatus.REJECTED
    return_request.rejection_reason = data.rejection_reason
    if data.admin_notes:
        return_request.admin_notes = data.admin_notes
    return_request.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(return_request)

    # Send rejection email to customer
    try:
        from app.services.email_service import get_email_service

        email_service = get_email_service()
        await email_service.send_return_rejected(
            to_email=return_request.customer_email,
            customer_name=return_request.customer_name,
            rma_number=return_request.rma_number,
            order_number=return_request.order.order_number if return_request.order else "N/A",
            rejection_reason=data.rejection_reason,
        )
    except Exception as e:
        import logging

        logging.getLogger(__name__).error(f"Failed to send return rejection email: {e}")

    return _build_admin_response(return_request)


@router.delete("/{return_id}", status_code=204)
async def delete_return_request(
    return_id: UUID,
    _member: RequireMember,
    db: TenantDB,
    tenant: CurrentTenant = None,
    user: CurrentUser = None,
):
    """Delete a return request (only allowed for cancelled/rejected)."""
    result = await db.execute(
        select(ReturnRequest).where(
            ReturnRequest.id == return_id,
            ReturnRequest.tenant_id == tenant.id,
        )
    )
    return_request = result.scalar_one_or_none()

    if not return_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Return request not found",
        )

    if return_request.status not in [ReturnStatus.CANCELLED, ReturnStatus.REJECTED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete cancelled or rejected return requests",
        )

    await db.delete(return_request)
    await db.commit()
