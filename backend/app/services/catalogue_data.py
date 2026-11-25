"""The packaging catalogue and carrier tariffs shipped with the backend (research D2).

Both are reference data, identical for every tenant and versioned with the
code that reads them: ``app/data/packaging_catalogue.json`` and one file per
carrier tariff at ``app/data/postage_tariffs/<carrier>/<effective_date>.json``.
They are loaded and validated here, once per process, and nowhere else reads
them -- the seeding service (:mod:`app.services.catalogue_seed`), the
catalogue routes and the release step all go through these functions.

Every figure in a file is a decimal **string**, parsed to :class:`Decimal`, so
a price is never a binary float on its way in (Constitution IV). An invalid
file raises at load time, and a unit test loads every shipped file, so a typo
in a tariff fails CI rather than a margin.

This module also holds the single answer to "which carrier does this shop post
with?" (:func:`carrier_for`, research D7): its country when one is recorded,
otherwise its currency. Onboarding, ``GET /postage/carriers`` and the release
step all ask it, so they cannot disagree (Constitution III).
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

if TYPE_CHECKING:
    from app.models.tenant import Tenant

#: Where the reference data lives. Module attributes, so a test can point the
#: loaders at a directory of its own (``monkeypatch.setattr``).
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PACKAGING_CATALOGUE_PATH = DATA_DIR / "packaging_catalogue.json"
TARIFF_ROOT = DATA_DIR / "postage_tariffs"

#: The currencies a catalogue item may quote a typical cost in.
CATALOGUE_CURRENCIES = ("CAD", "GBP", "USD", "EUR")

#: Each carrier's tariff is published in one currency; prices are never
#: converted (spec Assumptions).
CARRIER_CURRENCY: dict[str, str] = {
    "canada_post": "CAD",
    "royal_mail": "GBP",
    "la_poste": "EUR",
    "usps": "USD",
}

CARRIER_NAMES: dict[str, str] = {
    "canada_post": "Canada Post",
    "royal_mail": "Royal Mail",
    "la_poste": "La Poste",
    "usps": "USPS",
}

#: The services the first release covers per carrier (FR-016).
CARRIER_SERVICES: dict[str, tuple[str, ...]] = {
    "canada_post": ("lettermail", "small_packet", "expedited_parcel"),
    "royal_mail": ("large_letter", "small_parcel", "medium_parcel"),
    "la_poste": ("lettre_suivie", "colissimo"),
    "usps": ("ground_advantage", "priority_mail"),
}

CARRIER_FOR_COUNTRY: dict[str, str] = {
    "CA": "canada_post",
    "GB": "royal_mail",
    "US": "usps",
    "FR": "la_poste",
}

CARRIER_FOR_CURRENCY: dict[str, str] = {
    "CAD": "canada_post",
    "GBP": "royal_mail",
    "USD": "usps",
    "EUR": "la_poste",
}

#: Why no carrier postage was seeded (FR-022).
NO_CARRIER_FOR_COUNTRY = "no_carrier_for_country"
NO_CARRIER_FOR_CURRENCY = "no_carrier_for_currency"
CARRIER_CURRENCY_MISMATCH = "carrier_currency_mismatch"

PackagingKind = Literal["box", "mailer", "void_fill", "wrap"]
_CONTAINER_KINDS = ("box", "mailer")
_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SERVICE_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class CatalogueDataError(ValueError):
    """A shipped catalogue or tariff file is unreadable or invalid."""


def _decimal_string(value: object) -> Decimal:
    """A figure written as a decimal string, never a JSON number or a placeholder."""
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        raise ValueError(f"figures are decimal strings, got {value!r}")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{value!r} is not a decimal figure") from None
    if not parsed.is_finite():
        raise ValueError(f"{value!r} is not a decimal figure")
    return parsed


DecimalStr = Annotated[Decimal, BeforeValidator(_decimal_string)]


def _positive(value: Optional[Decimal], name: str) -> None:
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be above 0")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ============================================
# Packaging catalogue
# ============================================


class PackagingCatalogueItem(_Strict):
    """One standard container or filler (data-model "Packaging catalogue entry")."""

    key: str = Field(..., max_length=64)
    name: str = Field(..., min_length=1, max_length=200)
    kind: PackagingKind
    inner_length_mm: Optional[DecimalStr] = None
    inner_width_mm: Optional[DecimalStr] = None
    inner_height_mm: Optional[DecimalStr] = None
    wall_mm: Optional[DecimalStr] = None
    empty_weight_grams: Optional[DecimalStr] = None
    fill_volume_ml: Optional[DecimalStr] = None
    unit_of_measure: str = Field("each", min_length=1, max_length=20)
    typical_cost: dict[str, DecimalStr] = Field(default_factory=dict)
    source: str = Field(..., min_length=1, max_length=255)

    @field_validator("key")
    @classmethod
    def _kebab(cls, value: str) -> str:
        if not _KEY_PATTERN.match(value):
            raise ValueError(f"key {value!r} must be kebab-case")
        return value

    @field_validator("typical_cost")
    @classmethod
    def _currencies(cls, value: dict[str, Decimal]) -> dict[str, Decimal]:
        unknown = sorted(set(value) - set(CATALOGUE_CURRENCIES))
        if unknown:
            raise ValueError(
                f"typical_cost currencies must be in {CATALOGUE_CURRENCIES}: {unknown}"
            )
        for currency, amount in value.items():
            _positive(amount, f"typical_cost[{currency}]")
        return value

    @model_validator(mode="after")
    def _figures_for_kind(self) -> "PackagingCatalogueItem":
        inner = (self.inner_length_mm, self.inner_width_mm, self.inner_height_mm)
        for name in (
            "inner_length_mm",
            "inner_width_mm",
            "inner_height_mm",
            "wall_mm",
            "empty_weight_grams",
            "fill_volume_ml",
        ):
            _positive(getattr(self, name), name)
        if self.kind in _CONTAINER_KINDS:
            missing = [
                name
                for name in (
                    "inner_length_mm",
                    "inner_width_mm",
                    "inner_height_mm",
                    "wall_mm",
                    "empty_weight_grams",
                )
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(f"{self.key}: a {self.kind} needs {', '.join(missing)}")
            if self.fill_volume_ml is not None:
                raise ValueError(f"{self.key}: a {self.kind} has no fill volume")
        else:
            if self.fill_volume_ml is None:
                raise ValueError(f"{self.key}: {self.kind} needs fill_volume_ml")
            if any(v is not None for v in inner) or self.wall_mm is not None:
                raise ValueError(f"{self.key}: {self.kind} has no inner size or wall")
        return self

    @property
    def is_container(self) -> bool:
        return self.kind in _CONTAINER_KINDS


class PackagingCatalogue(_Strict):
    """The whole catalogue: a version, its date and the items."""

    version: int = Field(..., ge=1)
    as_of: date
    items: tuple[PackagingCatalogueItem, ...]

    @model_validator(mode="after")
    def _unique(self) -> "PackagingCatalogue":
        keys = [item.key for item in self.items]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        if duplicates:
            raise ValueError(f"duplicate catalogue keys: {duplicates}")
        same: list[str] = []
        seen: set[tuple[str, str]] = set()
        for pair in ((item.kind, item.name.casefold()) for item in self.items):
            if pair in seen:
                same.append(pair[1])
            seen.add(pair)
        if same:
            raise ValueError(f"duplicate catalogue names within a kind: {same}")
        return self

    def by_key(self) -> dict[str, PackagingCatalogueItem]:
        return {item.key: item for item in self.items}


# ============================================
# Carrier tariffs
# ============================================


class TariffBracket(_Strict):
    """One weight bracket: inclusive below, exclusive above, as profiles price it."""

    min_grams: DecimalStr
    max_grams: Optional[DecimalStr] = None
    price: DecimalStr

    @model_validator(mode="after")
    def _order(self) -> "TariffBracket":
        if self.min_grams < 0:
            raise ValueError("min_grams must not be negative")
        if self.max_grams is not None and self.max_grams <= self.min_grams:
            raise ValueError("max_grams must be above min_grams")
        _positive(self.price, "price")
        return self


class TariffZone(_Strict):
    """A destination zone of one service with its brackets."""

    zone: str = Field(..., min_length=1, max_length=50)
    brackets: tuple[TariffBracket, ...] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _ascending(self) -> "TariffZone":
        previous: Optional[TariffBracket] = None
        for bracket in self.brackets:
            if previous is not None:
                if previous.max_grams is None:
                    raise ValueError(f"zone {self.zone}: only the last bracket may be open-ended")
                if bracket.min_grams < previous.max_grams:
                    raise ValueError(
                        f"zone {self.zone}: brackets must ascend without overlapping "
                        f"({bracket.min_grams} g starts before {previous.max_grams} g)"
                    )
            previous = bracket
        return self


class TariffService(_Strict):
    """A carrier service: its size class, divisor and zones."""

    key: str = Field(..., max_length=64)
    name: str = Field(..., min_length=1, max_length=100)
    max_length_mm: Optional[DecimalStr] = None
    max_width_mm: Optional[DecimalStr] = None
    max_height_mm: Optional[DecimalStr] = None
    volumetric_divisor: Optional[DecimalStr] = None
    zones: tuple[TariffZone, ...] = Field(..., min_length=1)

    @field_validator("key")
    @classmethod
    def _snake(cls, value: str) -> str:
        if not _SERVICE_PATTERN.match(value):
            raise ValueError(f"service key {value!r} must be snake_case")
        return value

    @model_validator(mode="after")
    def _limits(self) -> "TariffService":
        limits = (self.max_length_mm, self.max_width_mm, self.max_height_mm)
        if any(v is None for v in limits) and any(v is not None for v in limits):
            # The same rule as the shipping_profiles CHECK: all three or none.
            raise ValueError(f"{self.key}: size limits are all three or none")
        for name in ("max_length_mm", "max_width_mm", "max_height_mm", "volumetric_divisor"):
            _positive(getattr(self, name), name)
        zones = [z.zone for z in self.zones]
        if len(set(zones)) != len(zones):
            raise ValueError(f"{self.key}: a zone is listed twice")
        return self

    @property
    def has_size_limits(self) -> bool:
        return self.max_length_mm is not None


class CarrierTariff(_Strict):
    """One carrier's published prices from one effective date."""

    carrier: str
    name: str = Field(..., min_length=1, max_length=100)
    currency: str
    effective_date: date
    source: str = Field(..., min_length=1, max_length=255)
    services: tuple[TariffService, ...] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _carrier_currency(self) -> "CarrierTariff":
        expected = CARRIER_CURRENCY.get(self.carrier)
        if expected is None:
            raise ValueError(f"unknown carrier {self.carrier!r}")
        if self.currency != expected:
            raise ValueError(f"{self.carrier} is priced in {expected}, not {self.currency}")
        keys = [s.key for s in self.services]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{self.carrier}: a service is listed twice")
        return self

    def service(self, key: str) -> Optional[TariffService]:
        return next((s for s in self.services if s.key == key), None)


# ============================================
# Loading
# ============================================


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogueDataError(f"{path.name} could not be read: {exc}") from exc


@lru_cache(maxsize=8)
def _load_packaging(path: str) -> PackagingCatalogue:
    try:
        return PackagingCatalogue.model_validate(_read_json(Path(path)))
    except ValueError as exc:
        if isinstance(exc, CatalogueDataError):
            raise
        raise CatalogueDataError(f"{Path(path).name} is invalid: {exc}") from exc


def load_packaging_catalogue() -> PackagingCatalogue:
    """The shipped packaging catalogue, validated (cached per process)."""
    return _load_packaging(str(PACKAGING_CATALOGUE_PATH))


def parse_tariff_file(path: Path) -> CarrierTariff:
    """One tariff file, checked against where it sits: ``<carrier>/<effective_date>.json``."""
    try:
        tariff = CarrierTariff.model_validate(_read_json(path))
    except CatalogueDataError:
        raise
    except ValueError as exc:
        raise CatalogueDataError(f"{path.parent.name}/{path.name} is invalid: {exc}") from exc
    if tariff.carrier != path.parent.name:
        raise CatalogueDataError(f"{path.parent.name}/{path.name} names carrier {tariff.carrier!r}")
    if path.stem != tariff.effective_date.isoformat():
        raise CatalogueDataError(
            f"{path.parent.name}/{path.name}: the file name must be its effective_date "
            f"({tariff.effective_date.isoformat()})"
        )
    return tariff


@lru_cache(maxsize=8)
def _load_tariffs(root: str) -> tuple[CarrierTariff, ...]:
    base = Path(root)
    if not base.is_dir():
        return ()
    tariffs = [
        parse_tariff_file(path)
        for carrier_dir in sorted(p for p in base.iterdir() if p.is_dir())
        for path in sorted(carrier_dir.glob("*.json"))
    ]
    return tuple(sorted(tariffs, key=lambda t: (t.carrier, t.effective_date)))


def load_tariffs(carrier: Optional[str] = None) -> list[CarrierTariff]:
    """Every shipped tariff (one carrier's when named), oldest first."""
    tariffs = _load_tariffs(str(TARIFF_ROOT))
    return [t for t in tariffs if carrier is None or t.carrier == carrier]


def latest_tariff(carrier: str) -> Optional[CarrierTariff]:
    """The newest tariff shipped for ``carrier``, or None."""
    tariffs = load_tariffs(carrier)
    return tariffs[-1] if tariffs else None


def tariff(carrier: str, effective_date: date) -> Optional[CarrierTariff]:
    """One shipped tariff by carrier and effective date, or None."""
    return next((t for t in load_tariffs(carrier) if t.effective_date == effective_date), None)


def clear_caches() -> None:
    """Forget loaded files (tests that point the loaders elsewhere)."""
    _load_packaging.cache_clear()
    _load_tariffs.cache_clear()


# ============================================
# Which carrier a shop posts with (research D7)
# ============================================


@dataclass(frozen=True)
class CarrierChoice:
    """The carrier for a shop, or why there is none.

    ``chosen_from`` says which of the shop's settings decided it -- ``country``
    when one is recorded, else ``currency``. ``candidate`` is the carrier that
    setting names even when it cannot be used (a currency mismatch), so the
    notice can say which carrier was considered.
    """

    carrier: Optional[str]
    chosen_from: Literal["country", "currency"]
    reason: Optional[str] = None
    candidate: Optional[str] = None


def carrier_for(country_code: Optional[str], currency_code: Optional[str]) -> CarrierChoice:
    """The one resolver of a shop's carrier: country first, then currency.

    With a country recorded, the currency is never a fallback: a Belgian EUR
    shop would otherwise receive La Poste's domestic rates for Belgium. A
    carrier priced in another currency than the books is not used either --
    prices are never converted.
    """
    currency = (currency_code or "").upper() or None
    if country_code:
        chosen_from: Literal["country", "currency"] = "country"
        carrier = CARRIER_FOR_COUNTRY.get(country_code.upper())
        if carrier is None:
            return CarrierChoice(None, chosen_from, NO_CARRIER_FOR_COUNTRY)
    else:
        chosen_from = "currency"
        carrier = CARRIER_FOR_CURRENCY.get(currency or "")
        if carrier is None:
            return CarrierChoice(None, chosen_from, NO_CARRIER_FOR_CURRENCY)
    if CARRIER_CURRENCY[carrier] != currency:
        return CarrierChoice(None, chosen_from, CARRIER_CURRENCY_MISMATCH, candidate=carrier)
    return CarrierChoice(carrier, chosen_from, candidate=carrier)


def carrier_for_tenant(tenant: "Tenant") -> CarrierChoice:
    """:func:`carrier_for` for a tenant's recorded country and books currency."""
    return carrier_for(getattr(tenant, "country_code", None), tenant.currency_code)


__all__ = [
    "CARRIER_CURRENCY",
    "CARRIER_CURRENCY_MISMATCH",
    "CARRIER_FOR_COUNTRY",
    "CARRIER_FOR_CURRENCY",
    "CARRIER_NAMES",
    "CARRIER_SERVICES",
    "CATALOGUE_CURRENCIES",
    "CarrierChoice",
    "CarrierTariff",
    "CatalogueDataError",
    "NO_CARRIER_FOR_COUNTRY",
    "NO_CARRIER_FOR_CURRENCY",
    "PackagingCatalogue",
    "PackagingCatalogueItem",
    "TariffBracket",
    "TariffService",
    "TariffZone",
    "carrier_for",
    "carrier_for_tenant",
    "clear_caches",
    "latest_tariff",
    "load_packaging_catalogue",
    "load_tariffs",
    "parse_tariff_file",
    "tariff",
]
