"""
CSV Export API endpoints.

Provides endpoints to download products, orders, and inventory
in Shopify-compatible CSV format.

Every handler queries on the tenant-scoped session. The orders export streams
each order's subtotal, shipping, discount, tax and total out of the system, and
on `get_db` it did so with `app.current_tenant_id` unset -- the application
filter inside the service was the only belt (Constitution I).
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.auth.dependencies import CurrentTenant, TenantDB
from app.services.export_service import get_export_service

router = APIRouter()


@router.get("/products")
async def export_products_csv(
    db: TenantDB,
    tenant: CurrentTenant,
):
    """
    Export all products in Shopify-compatible CSV format.

    Returns a CSV file that can be directly imported into Shopify
    using their product import feature.
    """
    service = get_export_service(db, tenant)
    csv_content = await service.export_products_csv()

    filename = f"products_{date.today().isoformat()}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


@router.get("/inventory")
async def export_inventory_csv(
    db: TenantDB,
    tenant: CurrentTenant,
    location: str = Query("Default", description="Inventory location name"),
):
    """
    Export inventory in Shopify-compatible CSV format.

    Returns a CSV file for updating stock levels in Shopify.
    """
    service = get_export_service(db, tenant)
    csv_content = await service.export_inventory_csv(location=location)

    filename = f"inventory_{date.today().isoformat()}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


@router.get("/orders")
async def export_orders_csv(
    db: TenantDB,
    tenant: CurrentTenant,
    start_date: Optional[date] = Query(None, description="Filter orders from this date"),
    end_date: Optional[date] = Query(None, description="Filter orders to this date"),
    status: Optional[str] = Query(None, description="Filter by order status"),
    format: str = Query("shopify", description="Export format: 'shopify' or 'accounting'"),
):
    """
    Export orders in CSV format.

    Supports two formats:
    - shopify: Full Shopify-compatible order export
    - accounting: Simplified format for accounting software (Xero, QuickBooks)

    Date filters are inclusive.
    """
    service = get_export_service(db, tenant)

    if format == "accounting":
        csv_content = await service.export_orders_accounting_csv(
            start_date=start_date,
            end_date=end_date,
        )
        filename = f"orders_accounting_{date.today().isoformat()}.csv"
    else:
        csv_content = await service.export_orders_csv(
            start_date=start_date,
            end_date=end_date,
            status=status,
        )
        filename = f"orders_{date.today().isoformat()}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )
