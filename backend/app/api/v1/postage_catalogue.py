"""Carrier postage: the carrier, its services, tariff updates and the default service (spec 006 US3).

Postage is monetary policy, so writing it takes an admin or owner, as the
shipping profiles do (FR-007a); reading is open to every role. The routes stay
thin: which carrier fits a shop is :func:`catalogue_data.carrier_for`, and
seeding, superseding and removing are :mod:`app.services.catalogue_seed`'s.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireAdmin, TenantDB
from app.schemas.postage_catalogue import (
    CarrierApplyRequest,
    CarrierApplyResponse,
    CarrierOut,
    CarrierServiceOut,
    CarriersResponse,
    CurrentPostageOut,
    PostageSettingsOut,
    PostageSettingsUpdate,
    TariffUpdateOut,
    TariffUpdatesResponse,
)
from app.services import catalogue_data as cd
from app.services import catalogue_seed

logger = logging.getLogger(__name__)

router = APIRouter()


def _postage_settings(tenant) -> dict:
    return dict((tenant.settings or {}).get("postage") or {})


@router.get("/postage/carriers", response_model=CarriersResponse)
async def list_carriers(user: CurrentUser, tenant: CurrentTenant, db: TenantDB) -> CarriersResponse:
    """The carrier proposed for this shop, and every catalogue carrier with its services."""
    choice = cd.carrier_for_tenant(tenant)
    currency = (tenant.currency_code or "").upper()
    settings = _postage_settings(tenant)
    current_carrier = settings.get("carrier")
    carriers: list[CarrierOut] = []
    current_version = None
    for key, name in cd.CARRIER_NAMES.items():
        latest = cd.latest_tariff(key)
        seeded = await catalogue_seed.seeded_services(db, tenant, key)
        carriers.append(
            CarrierOut(
                key=key,
                name=name,
                currency=cd.CARRIER_CURRENCY[key],
                usable=cd.CARRIER_CURRENCY[key] == currency,
                latest_tariff=latest.effective_date if latest else None,
                source=latest.source if latest else None,
                services=[
                    CarrierServiceOut(
                        key=s.key,
                        name=s.name,
                        seeded=s.key in seeded,
                        has_size_limits=s.has_size_limits,
                    )
                    for s in (latest.services if latest else ())
                ],
            )
        )
    if current_carrier:
        versions = [
            p.tariff_version
            for p in await catalogue_seed.tenant_profiles(db, tenant)
            if p.catalogue_carrier == current_carrier
            and p.tariff_version
            and p.effective_to is None
        ]
        current_version = max(versions) if versions else None
    return CarriersResponse(
        suggested_carrier=choice.carrier,
        candidate_carrier=choice.candidate,
        chosen_from=choice.chosen_from,
        reason=choice.reason,  # type: ignore[arg-type]
        current=CurrentPostageOut(
            carrier=current_carrier,
            default_service=settings.get("default_service"),
            tariff_version=current_version,
        ),
        carriers=carriers,
    )


@router.post("/postage/carriers/apply", response_model=CarrierApplyResponse)
async def apply_carrier(
    payload: CarrierApplyRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> CarrierApplyResponse:
    """Seed a carrier's services; supersedes another carrier's or an older tariff's rows."""
    try:
        result = await catalogue_seed.seed_postage(
            db, tenant, payload.carrier, payload.services or None, payload.tariff_version
        )
    except catalogue_seed.TariffNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except catalogue_seed.CatalogueSeedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    await db.commit()
    return CarrierApplyResponse.model_validate(
        {"added": len(result.added), "superseded": result.superseded, "skipped": result.skipped}
    )


@router.get("/postage/tariff-updates", response_model=TariffUpdatesResponse)
async def list_tariff_updates(
    user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> TariffUpdatesResponse:
    """Newer shipped tariffs than the seeded postage in force; nothing changes until accepted."""
    updates = await catalogue_seed.pending_tariff_updates(db, tenant)
    return TariffUpdatesResponse(updates=[TariffUpdateOut(**update.__dict__) for update in updates])


@router.delete("/postage/carriers/services/{service}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_service(
    service: str,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> None:
    """Stop a seeded service: its rows are superseded, operator rows untouched (FR-018)."""
    try:
        await catalogue_seed.remove_postage_service(db, tenant, service)
    except catalogue_seed.ServiceNotSeeded as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await db.commit()


@router.put("/settings/postage", response_model=PostageSettingsOut)
async def update_postage_settings(
    payload: PostageSettingsUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _admin: RequireAdmin,
    db: TenantDB,
) -> PostageSettingsOut:
    """Choose the shop's default service (null: the cheapest the parcel fits, FR-023a)."""
    if payload.default_service is not None and payload.default_service not in (
        await catalogue_seed.services_in_force(db, tenant)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"No postage profile in force prices {payload.default_service}",
        )
    value = await catalogue_seed.write_postage_settings(
        db, tenant, _postage_settings(tenant).get("carrier"), payload.default_service
    )
    await db.commit()
    return PostageSettingsOut(**value)
