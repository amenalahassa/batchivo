"""The standard packaging catalogue and the one-time seeding notice (spec 006 US2).

Routes are thin: what is present, what to add and how is the seeding service's
(:mod:`app.services.catalogue_seed`). Reading is open to every role; adding the
catalogue changes operational figures, so it takes a member, as consumables do
(FR-008).
"""

import logging

from fastapi import APIRouter, HTTPException, status

from app.auth.dependencies import CurrentTenant, CurrentUser, RequireMember, TenantDB
from app.schemas.packaging_catalogue import (
    AcknowledgeRequest,
    CatalogueApplyRequest,
    CatalogueApplyResponse,
    CatalogueItemOut,
    CatalogueNoticeOut,
    PackagingCatalogueOut,
)
from app.services import catalogue_data, catalogue_seed

logger = logging.getLogger(__name__)

router = APIRouter()


def _catalogue_or_503() -> catalogue_data.PackagingCatalogue:
    try:
        return catalogue_data.load_packaging_catalogue()
    except catalogue_data.CatalogueDataError as exc:
        logger.error(f"Packaging catalogue unreadable: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The standard packaging catalogue could not be read; try again after an update",
        ) from exc


@router.get("/packaging/catalogue", response_model=PackagingCatalogueOut)
async def get_packaging_catalogue(
    user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> PackagingCatalogueOut:
    """The catalogue, each item marked present, or previously removed, for this shop."""
    catalogue = _catalogue_or_503()
    rows = await catalogue_seed.packaging_rows(db, tenant)
    present = {row.catalogue_key: row.id for row in rows if row.catalogue_key}
    seeded = set(catalogue_seed.seed_state(tenant, "packaging").get("seeded_keys", []))
    currency = (tenant.currency_code or "").upper()
    return PackagingCatalogueOut(
        version=catalogue.version,
        as_of=catalogue.as_of,
        currency=currency,
        items=[
            CatalogueItemOut(
                key=item.key,
                name=item.name,
                kind=item.kind,
                inner_length_mm=item.inner_length_mm,
                inner_width_mm=item.inner_width_mm,
                inner_height_mm=item.inner_height_mm,
                wall_mm=item.wall_mm,
                empty_weight_grams=item.empty_weight_grams,
                fill_volume_ml=item.fill_volume_ml,
                unit_of_measure=item.unit_of_measure,
                typical_cost=item.typical_cost.get(currency),
                source=item.source,
                present=item.key in present,
                present_as=present.get(item.key),
                previously_removed=item.key in seeded and item.key not in present,
            )
            for item in catalogue.items
        ],
    )


@router.post("/packaging/catalogue/apply", response_model=CatalogueApplyResponse)
async def apply_packaging_catalogue(
    payload: CatalogueApplyRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> CatalogueApplyResponse:
    """Add the chosen catalogue items (all when none are named). Requires a member."""
    _catalogue_or_503()
    try:
        result = await catalogue_seed.seed_packaging(db, tenant, payload.keys or None)
    except catalogue_seed.UnknownCatalogueKey as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    await db.commit()
    return CatalogueApplyResponse.model_validate({"added": result.added, "skipped": result.skipped})


@router.get(
    "/catalogue-notice", response_model=CatalogueNoticeOut, response_model_exclude_none=True
)
async def get_catalogue_notice(
    user: CurrentUser, tenant: CurrentTenant, db: TenantDB
) -> CatalogueNoticeOut:
    """What seeding added and skipped, for the parts not yet dismissed."""
    return CatalogueNoticeOut(**catalogue_seed.pending_notices(tenant))


@router.post("/catalogue-notice/acknowledge", status_code=status.HTTP_204_NO_CONTENT)
async def acknowledge_catalogue_notice(
    payload: AcknowledgeRequest,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> None:
    """Dismiss one notice (``packaging`` or ``postage``)."""
    await catalogue_seed.acknowledge(db, tenant, payload.part)
