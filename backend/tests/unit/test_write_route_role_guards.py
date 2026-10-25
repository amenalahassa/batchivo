"""Every tenant write route outside pricing takes a role (bug viewer-write-guards).

FR-007c makes the viewer a reader. The pricing routers are walked by
`tests/unit/pricing/test_pricing_write_guards_derived.py`; this walks the rest
(`NOT_PRICING_MODULES` there), so the two together cover every router. A
non-GET route must depend on a role guard, or its module or route must be named
below with the reason it has none.
"""

import importlib
import inspect

from fastapi.routing import APIRoute

from tests.unit.pricing.test_pricing_write_guards_derived import NOT_PRICING_MODULES, _guarded

#: Routers whose writes are not a tenant user's: the public storefront, customer
#: accounts, signup, inbound webhooks, and sockets. Each authenticates another way.
PUBLIC_MODULES: dict[str, str] = {
    "auth": "login, registration and password reset run before any role exists",
    "customer_auth": "storefront customers, authenticated as customers, not tenant users",
    "customer_account": "a storefront customer's own account",
    "newsletter": "a public storefront sign-up",
    "onboarding": "tenant signup and email verification, before a role exists",
    "payments": "public checkout and Square's signed webhooks",
    "shop": "the public storefront, resolved by domain",
    "shop_resolver": "resolves a storefront domain to a tenant",
    "shopify_webhooks": "inbound Shopify webhooks, verified by HMAC signature",
    "printer_ws": "printer monitoring socket",
}

#: Single routes on tenant routers that take no role, each with why. Keyed by
#: (module, method, route path as declared on the router).
_INLINE = "guarded inline: the handler calls `_require_admin_role(user, tenant)` first"

NOT_ROLE_GUARDED: dict[tuple[str, str, str], str] = {
    ("shipping", "POST", "/rates"): "a read: quotes postage for a parcel, writes nothing",
    ("settings", "PUT", "/square"): _INLINE,
    ("settings", "POST", "/square/test"): _INLINE,
    ("settings", "PUT", "/etsy"): _INLINE,
    ("settings", "POST", "/etsy/test"): _INLINE,
    ("settings", "PUT", "/shop"): _INLINE,
    ("settings", "PUT", "/branding"): _INLINE,
    ("settings", "POST", "/custom-domain"): _INLINE,
    ("settings", "POST", "/custom-domain/verify"): _INLINE,
    ("settings", "DELETE", "/custom-domain"): _INLINE,
    ("tenant_members", "POST", "/invite"): _INLINE,
    ("tenant_members", "PUT", "/{member_id}"): _INLINE,
    ("tenant_members", "DELETE", "/{member_id}"): _INLINE,
}


def _writes() -> list[tuple[str, str, str, APIRoute]]:
    found = []
    for module_name in sorted(NOT_PRICING_MODULES - set(PUBLIC_MODULES)):
        router = importlib.import_module(f"app.api.v1.{module_name}").router
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in sorted((route.methods or set()) - {"GET", "HEAD", "OPTIONS"}):
                found.append((module_name, method, route.path, route))
    return found


def test_every_public_module_is_a_known_router() -> None:
    stale = sorted(set(PUBLIC_MODULES) - NOT_PRICING_MODULES)
    assert not stale, f"PUBLIC_MODULES names routers that are gone or reclassified: {stale}"


def test_the_walk_finds_the_writes() -> None:
    """A walk that finds nothing would pass for the wrong reason."""
    writes = {(module, method, path) for module, method, path, _ in _writes()}
    assert ("categories", "POST", "") in writes
    assert ("print_queue", "POST", "/print-queue/auto-assign") in writes
    assert len(writes) > 50


def test_every_tenant_write_route_takes_a_role() -> None:
    unguarded = sorted(
        f"{module}: {method} {path}"
        for module, method, path, route in _writes()
        if (module, method, path) not in NOT_ROLE_GUARDED and not _guarded(route.dependant)
    )
    assert not unguarded, (
        "these write routes take no role guard, so a viewer can use them (FR-007c). "
        "Add RequireMember or RequireAdmin, or name the route in NOT_ROLE_GUARDED "
        "with the reason:\n  " + "\n  ".join(unguarded)
    )


def test_every_inline_exception_calls_the_inline_guard() -> None:
    """An `_INLINE` entry is a claim about the handler's body; hold it to that."""
    routes = {(module, method, path): route for module, method, path, route in _writes()}
    missing = sorted(
        f"{module}: {method} {path}"
        for (module, method, path), reason in NOT_ROLE_GUARDED.items()
        if reason == _INLINE
        and "_require_admin_role(user, tenant)"
        not in inspect.getsource(routes[(module, method, path)].endpoint)
    )
    assert not missing, f"named as guarded inline but never call the guard: {missing}"


def test_every_exception_is_still_a_route() -> None:
    live = {(module, method, path) for module, method, path, _ in _writes()}
    stale = sorted(set(NOT_ROLE_GUARDED) - live)
    assert not stale, f"NOT_ROLE_GUARDED names routes that no longer exist: {stale}"
