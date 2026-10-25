"""Every pricing write route takes a role, found by walking the routers (T250).

`MEMBER_WRITES` in `tests/api/test_cost_input_write_guards.py` lists the routes
a viewer must be refused, by hand, so a new pricing write route is covered by
its absence. This walks every router module in `app.api.v1` instead: each
module is classified as a pricing surface or not -- a new module fails until it
is -- and every non-GET route on a pricing surface must depend on a role guard
(`require_member`, `require_admin`, `require_role`) or be named below with its
reason (FR-007c, FR-007d, Constitution II).

Routers are read from their modules rather than from `app.routes`, which holds
FastAPI's lazy placeholders rather than the routes' dependency graphs (the
same reason `tests/integration/test_rls_pricing.py` gives).
"""

import importlib
import pkgutil

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

import app.api.v1 as v1

#: Routers whose writes move a cost input, a price, a fee, a policy, an
#: exchange rate, a discount or a recorded actual.
PRICING_MODULES: frozenset[str] = frozenset(
    {
        "consumables",
        "discounts",
        "fee_rules",
        "filament_purchases",
        "fx_rates",
        "models",
        "orders",
        "pricing_policy",
        "printers",
        "production_runs",
        "products",
        "provenance",
        "reconciliation",
        "returns",
        "sales_channels",
        "scenarios",
        "shipping_profiles",
        "spools",
    }
)

#: Routers that hold no pricing figure. Their role guards are tracked by the
#: `tests/unit/test_write_route_role_guards.py`, not by this feature. `settings`
#: is here although `PUT /settings/tenant` sets the books currency: that one
#: route is guarded and tested in `tests/api/test_books_currency.py`, and the
#: router's other fifteen are shop and branding settings.
NOT_PRICING_MODULES: frozenset[str] = frozenset(
    {
        "analytics",
        "audit",
        "auth",
        "categories",
        "customer_account",
        "customer_auth",
        "dashboard",
        "designers",
        "exports",
        "filament_types",
        "forecasting",
        "model_files",
        "modules",
        "needle",
        "newsletter",
        "onboarding",
        "pages",
        "patterns",
        "payments",
        "platform",
        "print_queue",
        "printer_bambu",
        "printer_ws",
        "projects",
        "reviews",
        "settings",
        "shipping",
        "shop",
        "shop_resolver",
        "shopify_webhooks",
        "sku",
        "spoolmandb",
        "tenant_members",
        "test",
        "users",
        "webhooks",
        "yarn",
    }
)

#: The names of the dependencies that enforce a role.
GUARDS = frozenset({"check_member", "check_admin", "require_role", "get_platform_admin"})

#: Pricing-router writes that deliberately take no role guard, each with why.
#: Keyed by (module, method, route path as declared on the router).
NOT_ROLE_GUARDED: dict[tuple[str, str, str], str] = {
    ("discounts", "POST", "/validate"): "a read: checks a code against an order, writes nothing",
    ("products", "POST", "/{product_id}/pricing/{channel_id}/solve"): (
        "a read: solves for a price and writes nothing (a scenario writes nothing)"
    ),
    ("provenance", "PUT", "/provenance/{entity_type}/{entity_id}/{field_name}"): (
        "guarded inline by `_require_write_role`: admin for a policy field, member "
        "otherwise, which one dependency cannot express"
    ),
}


def _router_modules() -> set[str]:
    return {
        info.name
        for info in pkgutil.iter_modules(v1.__path__)
        if hasattr(importlib.import_module(f"app.api.v1.{info.name}"), "router")
    }


def _guarded(dependant: Dependant) -> bool:
    for dependency in dependant.dependencies:
        if getattr(dependency.call, "__name__", "") in GUARDS or _guarded(dependency):
            return True
    return False


def _pricing_writes() -> list[tuple[str, str, str, APIRoute]]:
    found = []
    for module_name in sorted(PRICING_MODULES):
        router = importlib.import_module(f"app.api.v1.{module_name}").router
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in sorted((route.methods or set()) - {"GET", "HEAD", "OPTIONS"}):
                found.append((module_name, method, route.path, route))
    return found


def test_every_router_is_classified() -> None:
    """A new router must be called a pricing surface or not; silence is a gap."""
    modules = _router_modules()
    unclassified = sorted(modules - PRICING_MODULES - NOT_PRICING_MODULES)
    assert not unclassified, (
        f"classify these routers in PRICING_MODULES or NOT_PRICING_MODULES: {unclassified}"
    )
    stale = sorted((PRICING_MODULES | NOT_PRICING_MODULES) - modules)
    assert not stale, f"these classified routers no longer exist: {stale}"
    assert not PRICING_MODULES & NOT_PRICING_MODULES


def test_the_walk_finds_the_pricing_writes() -> None:
    """A walk that finds nothing would pass for the wrong reason."""
    writes = {(module, method, path) for module, method, path, _ in _pricing_writes()}
    assert ("spools", "PUT", "/{spool_id}") in writes
    assert len(writes) > 80


def test_every_pricing_write_route_takes_a_role() -> None:
    unguarded = sorted(
        f"{module}: {method} {path}"
        for module, method, path, route in _pricing_writes()
        if (module, method, path) not in NOT_ROLE_GUARDED and not _guarded(route.dependant)
    )
    assert not unguarded, (
        "these pricing write routes take no role guard, so a viewer can use them "
        "(FR-007c). Add RequireMember or RequireAdmin, or name the route in "
        "NOT_ROLE_GUARDED with the reason:\n  " + "\n  ".join(unguarded)
    )


def test_every_exception_is_still_a_route() -> None:
    live = {(module, method, path) for module, method, path, _ in _pricing_writes()}
    stale = sorted(set(NOT_ROLE_GUARDED) - live)
    assert not stale, f"NOT_ROLE_GUARDED names routes that no longer exist: {stale}"
