"""Request and response schemas for the tenant pricing policy (task T047).

Every field here is an operator decision (FR-002), so the write schema forbids
unknown keys: a mistyped lever that silently did nothing would leave the
operator believing they had set a rate they had not. The read schema reports
``origin`` so a tenant still on the legacy settings blob can see that their
policy is a fallback rather than a decision anyone made.
"""

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

MarginBasis = Literal["customer_total", "item_price", "net_revenue"]
OverheadMethod = Literal["per_machine_hour", "percentage"]

#: Where the figures served came from: a policy row, or the legacy
#: ``Tenant.settings`` blob for a tenant the Tier 1 migration has not reached.
PolicyOrigin = Literal["policy_row", "legacy_settings"]


class PricingPolicyUpdate(BaseModel):
    """A change to one or more levers. Unlisted levers are carried forward."""

    print_labor_rate: Optional[Decimal] = Field(
        None, ge=0, description="Hourly rate for print handling and per-plate preparation"
    )
    finishing_labor_rate: Optional[Decimal] = Field(
        None, ge=0, description="Hourly rate for finishing work (FR-012)"
    )
    default_machine_rate_per_hour: Optional[Decimal] = Field(
        None, ge=0, description="Fallback machine rate for an item planned on no printer (FR-011)"
    )
    overhead_method: Optional[OverheadMethod] = Field(
        None, description="How overhead reaches a unit of production (FR-014)"
    )
    overhead_monthly_pool: Optional[Decimal] = Field(
        None, ge=0, description="Monthly overhead pool absorbed over expected machine-hours"
    )
    expected_monthly_machine_hours: Optional[Decimal] = Field(
        None, ge=0, description="Expected monthly machine capacity; the absorption denominator"
    )
    electricity_rate_per_kwh: Optional[Decimal] = Field(
        None, ge=0, description="Rate used by any printer carrying none of its own"
    )
    margin_basis: Optional[MarginBasis] = Field(
        None, description="Which amount a margin percentage is taken over (FR-031)"
    )
    default_target_margin_pct: Optional[Decimal] = Field(
        None, description="Target margin the solver uses when a request names none"
    )
    rounding_rule: Optional[str] = Field(
        None, max_length=20, description="How a solved price is rounded (FR-033)"
    )
    sales_tax_recoverable: Optional[bool] = Field(
        None, description="Whether input sales tax is recoverable (FR-008c)"
    )
    staleness_threshold_days: Optional[int] = Field(
        None, gt=0, description="Days after which a hand-measured figure is flagged stale (FR-005)"
    )
    margin_alert_threshold_pct: Optional[Decimal] = Field(
        None, ge=0, description="Realised-versus-planned divergence that alerts (FR-042)"
    )
    min_outcomes_before_auto_update: Optional[int] = Field(
        None, gt=0, description="Recorded outcomes before an estimate updates itself (FR-042a)"
    )
    estimate_divergence_threshold_pct: Optional[Decimal] = Field(
        None, ge=0, description="Divergence beyond which an observation is held (FR-042b)"
    )

    effective_from: Optional[date] = Field(
        None, description="First day the new policy applies; defaults to today"
    )

    # An unknown lever is a typo, and a typo that silently did nothing would be
    # worse than a refusal.
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def at_least_one_lever(self) -> "PricingPolicyUpdate":
        """Nothing to change is not a change, and must not open a new period."""
        changed = self.model_dump(exclude_none=True)
        changed.pop("effective_from", None)
        if not changed:
            raise ValueError(
                "name at least one lever to change; an empty body would open a "
                "new effective period that changes nothing"
            )
        return self

    def changes(self) -> dict:
        """The levers this request actually names, ready for `write_policy`."""
        values = self.model_dump(exclude_none=True)
        values.pop("effective_from", None)
        return values


class PricingPolicyResponse(BaseModel):
    """The policy in effect, with where it came from and when it started."""

    print_labor_rate: Decimal
    finishing_labor_rate: Decimal
    default_machine_rate_per_hour: Optional[Decimal] = None
    overhead_method: OverheadMethod
    overhead_monthly_pool: Optional[Decimal] = None
    expected_monthly_machine_hours: Optional[Decimal] = None
    overhead_rate_per_machine_hour: Optional[Decimal] = Field(
        None,
        description=(
            "Overhead absorbed per machine-hour, or null when no pool and "
            "capacity are declared — reported missing rather than as zero (FR-019)"
        ),
    )
    overhead_percentage: Decimal = Field(
        ...,
        description="The legacy percentage figure, used when overhead_method is 'percentage'",
    )
    electricity_rate_per_kwh: Optional[Decimal] = None
    margin_basis: MarginBasis
    default_target_margin_pct: Optional[Decimal] = None
    rounding_rule: Optional[str] = None
    sales_tax_recoverable: bool
    staleness_threshold_days: int
    margin_alert_threshold_pct: Decimal
    min_outcomes_before_auto_update: int
    estimate_divergence_threshold_pct: Decimal

    origin: PolicyOrigin = Field(
        ..., description="'policy_row', or 'legacy_settings' for a tenant with no row yet"
    )
    effective_from: Optional[date] = Field(
        None, description="First day this policy applied; null for a legacy fallback"
    )
    effective_to: Optional[date] = Field(
        None, description="Last day it applied; null means it is current"
    )
    set_by_role: Optional[str] = Field(None, description="The role that authorised it (FR-007a)")

    model_config = ConfigDict(from_attributes=True)
