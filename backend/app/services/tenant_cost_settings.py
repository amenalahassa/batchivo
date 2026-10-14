"""Resolve the costing figures the operator configured.

Constitution IV: *a value the operator configured MUST be the value the system
uses; a hardcoded default silently shadowing a tenant setting is a defect, not
a fallback.*

Before this module, `Tenant.settings["default_labor_rate"]` was written by the
settings UI, documented as the tenant's hourly labor rate, and read by nobody.
Every cost on every screen used `CostingService`'s own `DEFAULT_LABOR_RATE` of
10.00 instead. That key is now gone (task T123): the rate lives in the typed,
dated `tenant_pricing_policy` table, which is where a figure that money depends
on belongs. What remains here is the overhead percentage, which FR-014 keeps as
an absorption option and which has not moved into that table.

The value is stored in a JSON blob and arrives as whatever JSON had -- an int, a
float, or a string. It is converted through `str` rather than passed to
`Decimal` directly: `Decimal(20.1)` from a float carries the float's error into
exact arithmetic, which defeats the point.

This is deliberately a thin reader, not a policy layer. Tier 1 replaces the
blob with the typed temporal `tenant_pricing_policy` table (research.md D2),
at which point `app/services/pricing_policy.py` resolves policy as-of a date
and these functions go away with the key they read.
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

#: The legacy settings key still read here. The labor rate's key went with the
#: column drop in task T123: every tenant has a dated policy row, and a tenant
#: created without one takes `pricing_policy.POLICYLESS_LABOR_RATE`.
OVERHEAD_PERCENTAGE_KEY = "default_overhead_percentage"

#: No overhead unless configured. A model's own `overhead_percentage` still
#: wins where it is set, which is how overhead already worked.
FALLBACK_OVERHEAD_PERCENTAGE = Decimal("0")


def _as_decimal(value: Any, *, field: str, tenant_slug: str) -> Optional[Decimal]:
    """Convert a JSON scalar to an exact Decimal, or None if it is unusable."""
    if value is None:
        return None
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        logger.warning(
            f"Tenant {tenant_slug} has a non-numeric {field} setting ({value!r}); "
            f"falling back to the documented default"
        )
        return None
    if not converted.is_finite() or converted < 0:
        logger.warning(
            f"Tenant {tenant_slug} has an out-of-range {field} setting ({value!r}); "
            f"falling back to the documented default"
        )
        return None
    return converted


def tenant_overhead_percentage(tenant: "Tenant") -> Decimal:
    """The default overhead percentage this tenant configured, 0-100.

    A model's own `overhead_percentage` takes precedence where it is set; this
    is the figure used for a model that has none.
    """
    settings = getattr(tenant, "settings", None) or {}
    configured = _as_decimal(
        settings.get(OVERHEAD_PERCENTAGE_KEY),
        field=OVERHEAD_PERCENTAGE_KEY,
        tenant_slug=getattr(tenant, "slug", "<unknown>"),
    )
    return configured if configured is not None else FALLBACK_OVERHEAD_PERCENTAGE
