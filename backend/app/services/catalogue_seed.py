"""The one seeding service for the packaging catalogue and carrier postage (spec 006).

Onboarding step 5, the "Add standard packaging" and carrier routes, and the
release step (``python -m app.cli.seed_catalogues``) all call these functions,
so a shop seeded at sign-up and one seeded at release get the same rows by the
same rules (Constitution III).

The rules (research D3-D8):

- **Insert only.** Seeding never updates a row. A catalogue item is present when
  a row carries its ``catalogue_key``, or when an active row of the same kind
  has the same name (``name_in_use``): the operator's own item is kept.
- **Assumed, and dated.** Every figure seeded is recorded ``assumed`` in the
  provenance table, dated the catalogue's ``as_of`` or the tariff's effective
  date, so the margin's observed share says so (FR-013, FR-014, FR-019).
- **All or nothing.** Each call runs in a savepoint: a failure leaves no row and
  no notice for the part that failed (FR-015).
- **Supersede, never edit.** A newer tariff, or another carrier, closes the
  seeded rows in force (``effective_to``) and inserts new ones. Operator rows --
  those without ``catalogue_carrier`` -- are never touched (FR-020, D8).
- **Never overlap.** A seeded profile that would claim a parcel an existing
  profile claims is skipped and reported, by the rule the shipping-profile
  route enforces (:mod:`app.services.shipping_profile_rules`).

What happened is written once to ``tenant.settings["catalogue_seed"][part]``
with ``acknowledged: false``; the Packaging page and Settings -> Postage show it
until the operator dismisses it.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Iterable, Literal, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.models.consumable import PACKAGING_KINDS, ConsumableType
from app.models.shipping_profile import ShippingProfile
from app.services import catalogue_data as cd
from app.services.provenance import record_origin, registered_fields
from app.services.shipping_profile_rules import (
    Candidate,
    first_overlap,
    has_been_used,
    service_key,
    size_class,
)
from app.services.tenant_settings import TenantSettingsService

if TYPE_CHECKING:
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

NoticePart = Literal["packaging", "postage"]
NOTICE_PARTS: tuple[str, ...] = ("packaging", "postage")

#: Why a catalogue item or a profile was not added.
ALREADY_PRESENT = "already_present"
NAME_IN_USE = "name_in_use"
OVERLAPS_EXISTING = "overlaps_existing"

#: The figures of a consumable seeded from the catalogue whose origin is recorded.
PACKAGING_FIGURES = (
    "inner_length_mm",
    "inner_width_mm",
    "inner_height_mm",
    "wall_mm",
    "empty_weight_grams",
    "fill_volume_ml",
    "current_cost_per_unit",
)

#: The figures of a seeded shipping profile whose origin is recorded ``assumed``
#: explicitly -- the registry default for a profile is ``policy``, which would
#: claim the operator decided them (research D4).
PROFILE_FIGURES = (
    "postage_cost",
    "weight_bracket_min_grams",
    "weight_bracket_max_grams",
    "max_length_mm",
    "max_width_mm",
    "max_height_mm",
    "volumetric_divisor",
)


# ============================================
# Errors (the routes turn them into 422 / 404)
# ============================================


class CatalogueSeedError(ValueError):
    """A request the catalogue cannot satisfy."""


class UnknownCatalogueKey(CatalogueSeedError):
    def __init__(self, keys: Sequence[str]):
        self.keys = list(keys)
        super().__init__(f"Unknown catalogue item: {', '.join(self.keys)}")


class UnknownCarrier(CatalogueSeedError):
    def __init__(self, carrier: str):
        self.carrier = carrier
        super().__init__(f"Unknown carrier: {carrier}")


class UnknownService(CatalogueSeedError):
    def __init__(self, carrier: str, services: Sequence[str]):
        self.services = list(services)
        super().__init__(
            f"{cd.CARRIER_NAMES.get(carrier, carrier)} has no service {', '.join(self.services)}"
        )


class CarrierCurrencyMismatch(CatalogueSeedError):
    def __init__(self, carrier: str, currency: str):
        super().__init__(
            f"{cd.CARRIER_NAMES[carrier]} is priced in {cd.CARRIER_CURRENCY[carrier]}, "
            f"but the books are kept in {currency}; prices are never converted"
        )


class TariffNotFound(LookupError):
    def __init__(self, carrier: str, version: date):
        super().__init__(f"No {cd.CARRIER_NAMES.get(carrier, carrier)} tariff dated {version}")


class ServiceNotSeeded(LookupError):
    def __init__(self, service: str):
        super().__init__(f"No seeded postage in force for service {service}")


# ============================================
# Results
# ============================================


@dataclass
class SeedResult:
    """What one seeding call did: rows added, superseded and skipped, with reasons.

    ``reason`` is set when nothing could be seeded for the part at all (a shop
    with no catalogue carrier, FR-022); ``not_due`` when the release step found
    the tenant already seeded.
    """

    part: NoticePart
    added: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    superseded: int = 0
    reason: Optional[str] = None
    not_due: bool = False
    carrier: Optional[str] = None
    chosen_from: Optional[str] = None
    tariff_version: Optional[date] = None
    version: Optional[int] = None


# ============================================
# Notices (tenant.settings["catalogue_seed"])
# ============================================


def _seed_settings(tenant: "Tenant") -> dict[str, Any]:
    return dict((tenant.settings or {}).get("catalogue_seed") or {})


def seed_state(tenant: "Tenant", part: str) -> dict[str, Any]:
    """The recorded state of one part, or ``{}`` if it was never seeded."""
    return dict(_seed_settings(tenant).get(part) or {})


async def _write_seed_part(db: AsyncSession, tenant: "Tenant", part: str, value: dict) -> None:
    seed = _seed_settings(tenant)
    seed[part] = value
    await TenantSettingsService(db).write_settings_part(tenant, "catalogue_seed", seed)


async def record_notice(
    db: AsyncSession, tenant: "Tenant", part: NoticePart, result: SeedResult
) -> dict[str, Any]:
    """Store what a seeding call did as an unacknowledged notice (not committed)."""
    previous = seed_state(tenant, part)
    today = clock.today().isoformat()
    if part == "packaging":
        added_keys = [row["key"] for row in result.added]
        notice: dict[str, Any] = {
            "version": result.version,
            "applied_at": today,
            "added": added_keys,
            "skipped": result.skipped,
            # Every key ever seeded, so a removed one is recognised (edge case).
            "seeded_keys": sorted(set(previous.get("seeded_keys", [])) | set(added_keys)),
            "acknowledged": False,
        }
    else:
        notice = {
            "carrier": result.carrier,
            "chosen_from": result.chosen_from,
            "tariff_version": result.tariff_version.isoformat() if result.tariff_version else None,
            "applied_at": today,
            "added": len(result.added),
            "superseded": result.superseded,
            "skipped": result.skipped,
            "reason": result.reason,
            "acknowledged": False,
        }
    await _write_seed_part(db, tenant, part, notice)
    return notice


def pending_notices(tenant: "Tenant") -> dict[str, Any]:
    """The parts whose notice the operator has not dismissed yet."""
    return {
        part: value
        for part, value in _seed_settings(tenant).items()
        if part in NOTICE_PARTS and isinstance(value, dict) and not value.get("acknowledged")
    }


async def acknowledge(db: AsyncSession, tenant: "Tenant", part: NoticePart) -> None:
    """Dismiss one notice. Its record stays; only ``acknowledged`` changes."""
    if part not in NOTICE_PARTS:
        raise CatalogueSeedError(f"Unknown notice part: {part}")
    state = seed_state(tenant, part)
    if not state:
        return
    state["acknowledged"] = True
    await _write_seed_part(db, tenant, part, state)
    await db.commit()


# ============================================
# Packaging
# ============================================


async def _record_assumed(
    db: AsyncSession,
    tenant: "Tenant",
    entity_type: str,
    entity: object,
    names: Iterable[str],
    as_of: date,
) -> None:
    allowed = registered_fields(entity_type)
    for name in names:
        if name in allowed and getattr(entity, name, None) is not None:
            await record_origin(
                db,
                tenant,
                entity_type=entity_type,
                entity_id=entity.id,  # type: ignore[attr-defined]
                field_name=name,
                source="assumed",
                as_of=as_of,
            )


def _sku_for(key: str, taken: set[str]) -> str:
    base = f"PKG-{key.upper()}"[:50]
    candidate, n = base, 2
    while candidate in taken:
        suffix = f"-{n}"
        candidate = f"{base[: 50 - len(suffix)]}{suffix}"
        n += 1
    taken.add(candidate)
    return candidate


async def packaging_rows(db: AsyncSession, tenant: "Tenant") -> list[ConsumableType]:
    """The tenant's packaging consumables and catalogue-keyed rows."""
    result = await db.execute(
        select(ConsumableType).where(
            ConsumableType.tenant_id == tenant.id,
            (ConsumableType.packaging_kind.in_(PACKAGING_KINDS))
            | (ConsumableType.catalogue_key.is_not(None)),
        )
    )
    return list(result.scalars().all())


async def seed_packaging(
    db: AsyncSession,
    tenant: "Tenant",
    keys: Optional[Sequence[str]] = None,
    *,
    release: bool = False,
) -> SeedResult:
    """Add the catalogue items ``keys`` (all when None) the tenant does not have yet.

    ``release`` is the automatic release step: a tenant already at the shipped
    catalogue version is left alone, and a key seeded earlier and since deleted
    is not re-created -- only an explicit apply restores it (spec edge case).
    Nothing is committed; the caller commits.
    """
    catalogue = cd.load_packaging_catalogue()
    by_key = catalogue.by_key()
    if keys:
        unknown = sorted(set(keys) - set(by_key))
        if unknown:
            raise UnknownCatalogueKey(unknown)
        selected = [by_key[k] for k in dict.fromkeys(keys)]
    else:
        selected = list(catalogue.items)

    result = SeedResult(part="packaging", version=catalogue.version)
    state = seed_state(tenant, "packaging")
    if release and (state.get("version") or 0) >= catalogue.version:
        result.not_due = True
        return result
    previously_seeded = set(state.get("seeded_keys", [])) if release else set()

    async with db.begin_nested():
        existing = await packaging_rows(db, tenant)
        present = {row.catalogue_key: row for row in existing if row.catalogue_key}
        names = {
            (row.packaging_kind, row.name.strip().casefold())
            for row in existing
            if row.is_active and row.packaging_kind
        }
        taken = set(
            (
                await db.execute(
                    select(ConsumableType.sku).where(ConsumableType.tenant_id == tenant.id)
                )
            )
            .scalars()
            .all()
        )
        currency = (tenant.currency_code or "").upper()
        inserted: list[tuple[ConsumableType, cd.PackagingCatalogueItem]] = []
        for item in selected:
            if item.key in present:
                result.skipped.append({"key": item.key, "reason": ALREADY_PRESENT})
                continue
            if item.key in previously_seeded:
                # Deleted by the operator after an earlier seeding: the release
                # step does not bring it back.
                result.skipped.append({"key": item.key, "reason": ALREADY_PRESENT})
                continue
            if (item.kind, item.name.strip().casefold()) in names:
                result.skipped.append({"key": item.key, "reason": NAME_IN_USE})
                continue
            row = ConsumableType(
                tenant_id=tenant.id,
                sku=_sku_for(item.key, taken),
                name=item.name,
                description=f"Standard packaging (catalogue default). {item.source}"[:2000],
                category="packaging",
                unit_of_measure=item.unit_of_measure,
                current_cost_per_unit=item.typical_cost.get(currency),
                quantity_on_hand=0,
                is_active=True,
                packaging_kind=item.kind,
                inner_length_mm=item.inner_length_mm,
                inner_width_mm=item.inner_width_mm,
                inner_height_mm=item.inner_height_mm,
                wall_mm=item.wall_mm,
                empty_weight_grams=item.empty_weight_grams,
                fill_volume_ml=item.fill_volume_ml,
                catalogue_key=item.key,
                catalogue_version=catalogue.version,
            )
            db.add(row)
            inserted.append((row, item))
        await db.flush()
        for row, item in inserted:
            await _record_assumed(
                db, tenant, "consumable_type", row, PACKAGING_FIGURES, catalogue.as_of
            )
            result.added.append({"key": item.key, "id": row.id})
        await record_notice(db, tenant, "packaging", result)
    logger.info(
        f"Seeded packaging for tenant {tenant.id}: {len(result.added)} added, "
        f"{len(result.skipped)} skipped"
    )
    return result


# ============================================
# Postage
# ============================================


def _postage_settings(tenant: "Tenant") -> dict[str, Any]:
    return dict((tenant.settings or {}).get("postage") or {})


async def write_postage_settings(
    db: AsyncSession, tenant: "Tenant", carrier: Optional[str], default_service: Optional[str]
) -> dict[str, Any]:
    """``tenant.settings["postage"]``: the carrier and the shop's default service."""
    value = {"carrier": carrier, "default_service": default_service}
    await TenantSettingsService(db).write_settings_part(tenant, "postage", value)
    return value


async def tenant_profiles(db: AsyncSession, tenant: "Tenant") -> list[ShippingProfile]:
    result = await db.execute(select(ShippingProfile).where(ShippingProfile.tenant_id == tenant.id))
    return list(result.scalars().all())


def _in_force_from(profile: ShippingProfile, on: date) -> bool:
    """Whether a profile applies on ``on`` or later."""
    return profile.effective_to is None or profile.effective_to >= on


async def _close(db: AsyncSession, profile: ShippingProfile, opens_on: date) -> None:
    """Supersede one seeded profile from ``opens_on``: closed the day before.

    A row that would close before it opened (seeded today and replaced today)
    and that no order was placed under is removed instead; one that was used is
    closed on its first day.
    """
    closes_on = opens_on - timedelta(days=1)
    if closes_on >= profile.effective_from:
        profile.effective_to = closes_on
    elif not await has_been_used(db, profile):
        await db.delete(profile)
    else:
        profile.effective_to = profile.effective_from


def _resolve_carrier(
    tenant: "Tenant", carrier: Optional[str]
) -> tuple[Optional[str], str, Optional[str]]:
    """(carrier, chosen_from, reason) for a request, explicit carrier or :func:`carrier_for`."""
    if carrier is None:
        choice = cd.carrier_for_tenant(tenant)
        return choice.carrier, choice.chosen_from, choice.reason
    if carrier not in cd.CARRIER_CURRENCY:
        raise UnknownCarrier(carrier)
    currency = (tenant.currency_code or "").upper()
    if cd.CARRIER_CURRENCY[carrier] != currency:
        raise CarrierCurrencyMismatch(carrier, currency)
    # Say which setting proposed it when the operator kept the proposal.
    choice = cd.carrier_for_tenant(tenant)
    return carrier, choice.chosen_from if choice.carrier == carrier else "operator", None


async def seed_postage(
    db: AsyncSession,
    tenant: "Tenant",
    carrier: Optional[str] = None,
    services: Optional[Sequence[str]] = None,
    tariff_version: Optional[date] = None,
    *,
    release: bool = False,
    default_service: Optional[str] = None,
) -> SeedResult:
    """Seed one carrier's tariff for the tenant, superseding other seeded postage.

    ``carrier`` None means the shop's own (:func:`carrier_for_tenant`: country,
    else currency); a shop with none gets nothing and a notice saying why
    (FR-022). ``services`` None means all of the tariff's services;
    ``tariff_version`` None the latest shipped. ``release`` skips a tenant that
    was seeded (or told why not) before -- a later tariff is offered, never
    applied automatically (FR-020). Nothing is committed; the caller commits.
    """
    if release and seed_state(tenant, "postage"):
        return SeedResult(part="postage", not_due=True)

    resolved, chosen_from, reason = _resolve_carrier(tenant, carrier)
    result = SeedResult(part="postage", carrier=resolved, chosen_from=chosen_from)
    if resolved is None:
        result.reason = reason
        async with db.begin_nested():
            await record_notice(db, tenant, "postage", result)
        logger.info(f"No carrier postage for tenant {tenant.id}: {reason}")
        return result

    tariff = (
        cd.tariff(resolved, tariff_version)
        if tariff_version is not None
        else cd.latest_tariff(resolved)
    )
    if tariff is None:
        if tariff_version is not None:
            raise TariffNotFound(resolved, tariff_version)
        raise cd.CatalogueDataError(f"No tariff is shipped for {resolved}")
    if services:
        unknown = sorted(set(services) - {s.key for s in tariff.services})
        if unknown:
            raise UnknownService(resolved, unknown)
        chosen = [s for s in tariff.services if s.key in set(services)]
    else:
        chosen = list(tariff.services)
    result.tariff_version = tariff.effective_date

    today = clock.today()
    opens_on = max(tariff.effective_date, today)

    async with db.begin_nested():
        profiles = await tenant_profiles(db, tenant)
        # Supersede: another carrier's seeded rows, or this carrier's from an
        # older tariff. Operator rows (no catalogue_carrier) are never touched.
        for profile in profiles:
            if profile.catalogue_carrier is None or not _in_force_from(profile, opens_on):
                continue
            other_carrier = profile.catalogue_carrier != resolved
            older_tariff = (
                profile.catalogue_carrier == resolved
                and profile.tariff_version is not None
                and profile.tariff_version < tariff.effective_date
            )
            if other_carrier or older_tariff:
                await _close(db, profile, opens_on)
                result.superseded += 1
        await db.flush()
        profiles = await tenant_profiles(db, tenant)

        inserted: list[ShippingProfile] = []
        for service in chosen:
            limits = size_class(service)
            for zone in service.zones:
                for bracket in zone.brackets:
                    candidate = Candidate(
                        zone=zone.zone,
                        minimum=bracket.min_grams,
                        maximum=bracket.max_grams,
                        effective_from=opens_on,
                        limits=limits,
                    )
                    clash = first_overlap(candidate, [*profiles, *inserted])
                    if clash is not None:
                        same = (
                            clash.catalogue_carrier == resolved
                            and clash.service == service.key
                            and clash.tariff_version == tariff.effective_date
                        )
                        result.skipped.append(
                            {
                                "service": service.key,
                                "zone": zone.zone,
                                "min_grams": str(bracket.min_grams),
                                "reason": ALREADY_PRESENT if same else OVERLAPS_EXISTING,
                            }
                        )
                        continue
                    profile = ShippingProfile(
                        tenant_id=tenant.id,
                        name=f"{tariff.name} {service.name}"[:100],
                        destination_zone=zone.zone,
                        weight_bracket_min_grams=bracket.min_grams,
                        weight_bracket_max_grams=bracket.max_grams,
                        postage_cost=bracket.price,
                        carrier=tariff.name,
                        effective_from=opens_on,
                        effective_to=None,
                        max_length_mm=service.max_length_mm,
                        max_width_mm=service.max_width_mm,
                        max_height_mm=service.max_height_mm,
                        volumetric_divisor=service.volumetric_divisor,
                        catalogue_carrier=resolved,
                        service=service.key,
                        tariff_version=tariff.effective_date,
                        source=tariff.source[:255],
                    )
                    db.add(profile)
                    inserted.append(profile)
        await db.flush()
        for profile in inserted:
            await _record_assumed(
                db, tenant, "shipping_profile", profile, PROFILE_FIGURES, tariff.effective_date
            )
            result.added.append(
                {"id": profile.id, "service": profile.service, "zone": profile.destination_zone}
            )

        # The default stays only while a profile in force prices it.
        keep_default = default_service or _postage_settings(tenant).get("default_service")
        if keep_default and keep_default not in await services_in_force(db, tenant, opens_on):
            keep_default = None
        await write_postage_settings(db, tenant, resolved, keep_default)
        await record_notice(db, tenant, "postage", result)
    logger.info(
        f"Seeded {resolved} postage for tenant {tenant.id}: {len(result.added)} added, "
        f"{result.superseded} superseded, {len(result.skipped)} skipped"
    )
    return result


async def services_in_force(
    db: AsyncSession, tenant: "Tenant", on: Optional[date] = None
) -> set[str]:
    """Every service key a profile in force on ``on`` (today) prices."""
    day = on or clock.today()
    return {
        key
        for profile in await tenant_profiles(db, tenant)
        if profile.applies_on(day) and (key := service_key(profile)) is not None
    }


def _split_service(tenant: "Tenant", service: str) -> tuple[Optional[str], str]:
    if ":" in service:
        carrier, key = service.split(":", 1)
        return carrier, key
    return _postage_settings(tenant).get("carrier"), service


async def remove_postage_service(db: AsyncSession, tenant: "Tenant", service: str) -> int:
    """Stop a seeded service (FR-018): its rows in force are superseded from today.

    Never edits a price and never touches an operator row. A service that was
    the shop's default stops being it. Returns the rows closed; raises
    :class:`ServiceNotSeeded` when nothing seeded for it is in force.
    """
    carrier, key = _split_service(tenant, service)
    today = clock.today()
    rows = [
        p
        for p in await tenant_profiles(db, tenant)
        if p.catalogue_carrier is not None
        and (carrier is None or p.catalogue_carrier == carrier)
        and p.service == key
        and _in_force_from(p, today)
    ]
    if not rows:
        raise ServiceNotSeeded(service)
    for profile in rows:
        await _close(db, profile, today)
    current = _postage_settings(tenant)
    full = f"{rows[0].catalogue_carrier}:{key}"
    if current.get("default_service") == full:
        await write_postage_settings(db, tenant, current.get("carrier"), None)
    await db.flush()
    return len(rows)


@dataclass(frozen=True)
class TariffUpdate:
    """A newer shipped tariff than the one a tenant's seeded postage comes from."""

    carrier: str
    current: date
    latest: date
    effective_from: date
    source: str


async def pending_tariff_updates(db: AsyncSession, tenant: "Tenant") -> list[TariffUpdate]:
    """The carriers whose seeded postage in force is older than the newest tariff (D8)."""
    today = clock.today()
    current: dict[str, date] = {}
    for profile in await tenant_profiles(db, tenant):
        if (
            profile.catalogue_carrier
            and profile.tariff_version is not None
            and _in_force_from(profile, today)
        ):
            known = current.get(profile.catalogue_carrier)
            if known is None or profile.tariff_version > known:
                current[profile.catalogue_carrier] = profile.tariff_version
    updates: list[TariffUpdate] = []
    for carrier, version in sorted(current.items()):
        latest = cd.latest_tariff(carrier)
        if latest is not None and latest.effective_date > version:
            updates.append(
                TariffUpdate(
                    carrier=carrier,
                    current=version,
                    latest=latest.effective_date,
                    effective_from=max(latest.effective_date, today),
                    source=latest.source,
                )
            )
    return updates


async def seeded_services(db: AsyncSession, tenant: "Tenant", carrier: str) -> set[str]:
    """The service keys of ``carrier`` with seeded rows in force (or starting later)."""
    today = clock.today()
    return {
        p.service
        for p in await tenant_profiles(db, tenant)
        if p.catalogue_carrier == carrier and p.service and _in_force_from(p, today)
    }


__all__ = [
    "ALREADY_PRESENT",
    "CarrierCurrencyMismatch",
    "CatalogueSeedError",
    "NAME_IN_USE",
    "NOTICE_PARTS",
    "OVERLAPS_EXISTING",
    "SeedResult",
    "ServiceNotSeeded",
    "TariffNotFound",
    "TariffUpdate",
    "UnknownCarrier",
    "UnknownCatalogueKey",
    "UnknownService",
    "acknowledge",
    "packaging_rows",
    "pending_notices",
    "pending_tariff_updates",
    "record_notice",
    "remove_postage_service",
    "seed_packaging",
    "seed_postage",
    "seed_state",
    "seeded_services",
    "services_in_force",
    "write_postage_settings",
]
