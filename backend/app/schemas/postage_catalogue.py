"""Schemas for carrier postage: carriers, tariff updates and the default service (spec 006)."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChoiceReason = Literal[
    "no_carrier_for_country", "no_carrier_for_currency", "carrier_currency_mismatch"
]


class CarrierServiceOut(BaseModel):
    key: str
    name: str
    seeded: bool = Field(..., description="This tenant has seeded rows of it in force")
    has_size_limits: bool


class CarrierOut(BaseModel):
    key: str
    name: str
    currency: str
    usable: bool = Field(..., description="Priced in the tenant's books currency")
    latest_tariff: Optional[date]
    source: Optional[str]
    services: list[CarrierServiceOut]


class CurrentPostageOut(BaseModel):
    carrier: Optional[str] = None
    default_service: Optional[str] = None
    tariff_version: Optional[date] = None


class CarriersResponse(BaseModel):
    suggested_carrier: Optional[str]
    candidate_carrier: Optional[str] = Field(
        None, description="The carrier the country or currency names, even when unusable"
    )
    chosen_from: Literal["country", "currency"]
    reason: Optional[ChoiceReason]
    current: CurrentPostageOut
    carriers: list[CarrierOut]


class CarrierApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carrier: str = Field(..., min_length=1, max_length=32)
    services: Optional[list[str]] = Field(None, description="Absent or empty: every service")
    tariff_version: Optional[date] = Field(None, description="Null: the latest shipped tariff")


class SkippedProfile(BaseModel):
    service: str
    zone: str
    min_grams: str
    reason: Literal["already_present", "overlaps_existing"]


class CarrierApplyResponse(BaseModel):
    added: int
    superseded: int
    skipped: list[SkippedProfile]


class TariffUpdateOut(BaseModel):
    carrier: str
    current: date
    latest: date
    effective_from: date
    source: str


class TariffUpdatesResponse(BaseModel):
    updates: list[TariffUpdateOut]


class PostageSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_service: Optional[str] = Field(
        ..., max_length=100, description="'<carrier>:<service>', or null for the cheapest fitting"
    )

    @field_validator("default_service")
    @classmethod
    def _blank_is_none(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if value is not None else None


class PostageSettingsOut(BaseModel):
    carrier: Optional[str]
    default_service: Optional[str]


__all__ = [
    "CarrierApplyRequest",
    "CarrierApplyResponse",
    "CarrierOut",
    "CarrierServiceOut",
    "CarriersResponse",
    "CurrentPostageOut",
    "PostageSettingsOut",
    "PostageSettingsUpdate",
    "SkippedProfile",
    "TariffUpdateOut",
    "TariffUpdatesResponse",
]
