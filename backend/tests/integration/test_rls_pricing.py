"""Tenant isolation across every route this feature adds.

Constitution I is non-negotiable and names the reason: a leak across tenants is
unrecoverable, because it cannot be patched after the fact. So the harness is
written in the Foundational phase, before the routes exist, and it carries the
full route list from contracts/pricing-api.md. A route that has not landed yet
is reported as skipped with its task number; a route that lands without tenant
scope fails here the moment it is registered.

Two things are checked, because they fail differently:

1. **Invisibility.** A second tenant's rows must not be reachable through any
   of these routes. A route that answers 200 with another tenant's figure has
   leaked; one that answers 404 has not.
2. **The session dependency.** PostgreSQL row-level security only engages
   through ``get_tenant_db``; a handler wired to ``get_db`` is relying on
   application-level filtering alone, which the Constitution forbids as the only
   belt. This is checked by inspecting the registered dependency graph, so it
   holds even for a route no test calls.
"""

import ast
from decimal import Decimal
from pathlib import Path
from typing import Optional
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_shop_db, get_tenant_db
from app.database import get_db
from app.main import app
from app.models.model import Model
from app.models.product import Product
from app.models.sales_channel import SalesChannel
from app.models.tenant import Tenant

API = "/api/v1"


# ---------------------------------------------------------------------------
# The routes this feature adds, from contracts/pricing-api.md
# ---------------------------------------------------------------------------

#: (method, path template, the task that introduces it)
FEATURE_ROUTES: list[tuple[str, str, str]] = [
    ("GET", f"{API}/models/{{model_id}}/cost", "T049"),
    ("GET", f"{API}/products/{{product_id}}/cost", "T049"),
    ("GET", f"{API}/products/{{product_id}}/pricing/{{channel_id}}/margin", "T079"),
    ("POST", f"{API}/products/{{product_id}}/pricing/{{channel_id}}/solve", "T088"),
    ("GET", f"{API}/products/{{product_id}}/pricing/{{channel_id}}/ladder", "T088a"),
    ("GET", f"{API}/printers/{{printer_id}}/cost-policy", "T046"),
    ("PUT", f"{API}/printers/{{printer_id}}/cost-policy", "T046"),
    ("GET", f"{API}/settings/pricing-policy", "T047"),
    ("PUT", f"{API}/settings/pricing-policy", "T047"),
    ("GET", f"{API}/sales-channels/{{channel_id}}/fee-rules", "T076"),
    ("POST", f"{API}/sales-channels/{{channel_id}}/fee-rules", "T076"),
    ("POST", f"{API}/sales-channels/{{channel_id}}/fee-rules/preview", "T076"),
    ("POST", f"{API}/reconciliation/fee-actuals", "T077"),
    ("GET", f"{API}/reconciliation/channel-pnl", "T077"),
    ("GET", f"{API}/filament-purchases", "T048"),
    ("GET", f"{API}/shipping-profiles", "T078"),
    ("GET", f"{API}/provenance", "T105"),
    ("PUT", f"{API}/provenance/{{entity_type}}/{{entity_id}}/{{field_name}}", "T105"),
    ("GET", f"{API}/estimate-revisions", "T106"),
    ("POST", f"{API}/scenarios", "T114"),
    # The channel economics (FR-002/FR-003) are read and superseded through
    # the sales-channel resource itself, so its own routes carry planning
    # figures and belong under the same belt (T136, T139).
    ("POST", f"{API}/sales-channels", "T136"),
    ("GET", f"{API}/sales-channels", "T136"),
    ("GET", f"{API}/sales-channels/{{channel_id}}", "T136"),
    ("PUT", f"{API}/sales-channels/{{channel_id}}", "T136"),
    ("DELETE", f"{API}/sales-channels/{{channel_id}}", "T136"),
    # The temporal price history (T094, T097) is written and superseded through
    # these three, and a model the engine costs is edited through the fourth.
    # T139 moved the costing, margin, solve and ladder *reads* onto the RLS
    # session and left every write beside them on `get_db`, which is the one
    # arrangement Constitution I forbids: application-level filtering as the
    # only belt, on the paths that change the figures (T145).
    ("POST", f"{API}/products/{{product_id}}/pricing", "T145"),
    ("PUT", f"{API}/products/{{product_id}}/pricing/{{pricing_id}}", "T145"),
    ("DELETE", f"{API}/products/{{product_id}}/pricing/{{pricing_id}}", "T145"),
    ("GET", f"{API}/products/{{product_id}}/pricing/{{channel_id}}/history", "T145"),
    ("PUT", f"{API}/models/{{model_id}}", "T145"),
    # The printed item's operational figures (T147): waste, yield, failure mode
    # and the four-way labor split, which the engine costs on every read.
    ("GET", f"{API}/models/{{model_id}}/cost-profile", "T147"),
    ("PUT", f"{API}/models/{{model_id}}/cost-profile", "T147"),
    # The production run is where the FR-040 realised actuals are written, and
    # where the run `telemetry.learn` learns an observed print time and purge
    # figure from is closed. T155 and T156 moved products, models, printers,
    # orders and consumables and left this whole router on `get_db` (T170).
    ("POST", f"{API}/production-runs", "T170"),
    ("GET", f"{API}/production-runs", "T170"),
    ("GET", f"{API}/production-runs/{{run_id}}", "T170"),
    ("PATCH", f"{API}/production-runs/{{run_id}}", "T170"),
    ("DELETE", f"{API}/production-runs/{{run_id}}", "T170"),
    ("POST", f"{API}/production-runs/{{run_id}}/complete", "T170"),
    ("POST", f"{API}/production-runs/{{run_id}}/items", "T170"),
    ("POST", f"{API}/production-runs/{{run_id}}/materials", "T170"),
    ("POST", f"{API}/production-runs/{{run_id}}/plates", "T170"),
    ("GET", f"{API}/production-runs/{{run_id}}/plates", "T170"),
    # The RMA surface (T192). `POST /returns/{return_id}/complete` writes
    # `ReturnRequest.refund_amount`, which T189 makes an input the realised
    # margin reads -- the same class of cost-input write T156 moved -- and all
    # eight handlers took the un-scoped session.
    ("GET", f"{API}/returns", "T192"),
    ("GET", f"{API}/returns/{{return_id}}", "T192"),
    ("PUT", f"{API}/returns/{{return_id}}", "T192"),
    ("POST", f"{API}/returns/{{return_id}}/approve", "T192"),
    ("POST", f"{API}/returns/{{return_id}}/receive", "T192"),
    ("POST", f"{API}/returns/{{return_id}}/complete", "T192"),
    ("POST", f"{API}/returns/{{return_id}}/reject", "T192"),
    ("DELETE", f"{API}/returns/{{return_id}}", "T192"),
    # The production-history and variance reads, whose cost figures T183 moved
    # onto the service and which read on the un-scoped session (T183).
    ("GET", f"{API}/analytics/variance-report", "T183"),
    ("GET", f"{API}/analytics/products/{{product_id}}/production-history", "T183"),
    ("GET", f"{API}/analytics/spools/{{spool_id}}/production-usage", "T183"),
]


#: Storefront routes, which carry a tenant but never a token (T171).
#:
#: `get_tenant_db` cannot serve these: it reads `request.state.tenant_id`,
#: which `TenantContextMiddleware` sets from a JWT, and a shopper has none. So
#: they take `get_shop_db`, which scopes the session to the tenant
#: `get_shop_tenant` resolved from `X-Shop-Hostname`. `POST /shop/checkout/
#: complete` is the one that matters most: it writes the order and then the
#: sale snapshot carrying `make_cost_at_sale`, `cost_breakdown_json`,
#: `fees_json` and `postage_paid` (FR-036).
SHOP_ROUTES: list[tuple[str, str, str]] = [
    ("POST", f"{API}/shop/checkout/complete", "T171"),
    # The two Square surfaces that write an order of their own (T181). They
    # resolve their tenant through `ShopContext`, exactly as the storefront
    # does, and both wrote the order, its lines and -- after T180 -- its sale
    # snapshot on the un-scoped session.
    ("POST", f"{API}/payments/hosted-checkout", "T181"),
    ("POST", f"{API}/payments/process", "T181"),
    ("POST", f"{API}/shop/checkout/create-payment", "T171"),
    ("GET", f"{API}/shop/products", "T171"),
    ("GET", f"{API}/shop/products/{{product_id}}", "T171"),
    ("GET", f"{API}/shop/orders/{{order_number}}", "T171"),
    ("GET", f"{API}/shop/pages", "T171"),
    ("POST", f"{API}/shop/checkout/validate-discount", "T171"),
    ("GET", f"{API}/shop/categories", "T171"),
    ("GET", f"{API}/shop/designers", "T171"),
    # Applies the shop channel's free-shipping threshold, read from its
    # effective-dated economics on the scoped session (T208).
    ("POST", f"{API}/shop/checkout/shipping-rates", "T208"),
]


#: Where each `app.api.v1` router is mounted, mirroring app/main.py.
#:
#: FastAPI includes routers lazily, so `app.routes` holds internal placeholder
#: objects rather than the APIRoute instances whose dependency graph we need.
#: Reaching into those internals would tie this harness to a FastAPI version,
#: so the routers are inspected at their source instead and
#: `test_the_prefix_map_matches_the_app` keeps this map honest against the
#: published OpenAPI paths.
ROUTER_PREFIXES: dict[str, str] = {
    "models": f"{API}/models",
    "products": f"{API}/products",
    "printers": f"{API}/printers",
    "sales_channels": f"{API}/sales-channels",
    # Routers this feature adds (tasks T046-T048, T076-T078, T105, T114).
    "pricing_policy": f"{API}/settings",
    "fee_rules": f"{API}/sales-channels",
    "reconciliation": f"{API}/reconciliation",
    "filament_purchases": f"{API}/filament-purchases",
    "shipping_profiles": f"{API}/shipping-profiles",
    # Mounted at the API root, with the entity in each route's own path: one
    # provenance read answers for eleven entity types, and a scenario is asked
    # of the whole catalogue (contracts/pricing-api.md).
    "provenance": API,
    "scenarios": API,
    # Where the realised actuals are written (T170) and where a sale is made
    # without a token (T171).
    "production_runs": f"{API}/production-runs",
    "shop": f"{API}/shop",
    # The Square checkout surfaces write orders and snapshots too (T181).
    "payments": f"{API}/payments",
    # Where a refund amount is recorded (T192) and where the production costs
    # are read (T183).
    "returns": f"{API}/returns",
    "analytics": f"{API}/analytics",
    # The Shopify ingest, which scopes its session in the handler rather than
    # through a dependency; see the test below for why (T184).
    "shopify_webhooks": f"{API}/shopify",
}


def _registered() -> dict[tuple[str, str], APIRoute]:
    """Every (method, full path) this app serves, with its APIRoute."""
    import importlib

    found: dict[tuple[str, str], APIRoute] = {}
    for module_name, prefix in ROUTER_PREFIXES.items():
        try:
            module = importlib.import_module(f"app.api.v1.{module_name}")
        except ModuleNotFoundError:
            continue  # a router from a later tier
        router = getattr(module, "router", None)
        if router is None:
            continue
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods or set():
                found[(method, f"{prefix}{route.path}")] = route
    return found


def _dependency_functions(route: APIRoute) -> set:
    """Every dependency callable reachable from a route, at any depth."""
    seen: set = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dependant = stack.pop()
        if dependant.call is not None:
            seen.add(dependant.call)
        stack.extend(dependant.dependencies)
    return seen


def _handler_dependency_functions(route: APIRoute) -> set:
    """The dependencies the *handler itself* declares, not their children.

    The distinction matters for the session check below. Authentication cannot
    run on the RLS session: `get_current_user` has to resolve the bearer token
    before any tenant is known, so it necessarily takes `get_db`, and every
    authenticated route therefore reaches `get_db` transitively. Asserting over
    the transitive set would be unsatisfiable for every route in this feature.

    What the Constitution requires is that the handler's *own* queries run with
    `SET LOCAL app.current_tenant_id` in force, which is a claim about the
    session the handler was handed.
    """
    return {
        dependant.call for dependant in route.dependant.dependencies if dependant.call is not None
    }


@pytest.mark.parametrize(
    ("method", "path", "task"),
    FEATURE_ROUTES,
    ids=[f"{m} {p}" for m, p, _ in FEATURE_ROUTES],
)
def test_route_uses_the_rls_session_dependency(method: str, path: str, task: str) -> None:
    """A pricing route's handler must take ``get_tenant_db``, never ``get_db``.

    RLS engages only through ``get_tenant_db``, which issues
    ``SET LOCAL app.current_tenant_id``. A handler on ``get_db`` has
    application-level filtering as its only protection, which the Constitution
    rules out as a sole belt.

    Only the handler's own dependencies are examined; see
    :func:`_handler_dependency_functions` for why the transitive set cannot be.
    """
    route = _registered().get((method, path))
    if route is None:
        pytest.skip(f"{method} {path} arrives with task {task}")

    functions = _handler_dependency_functions(route)
    assert get_tenant_db in functions, (
        f"{method} {path} does not depend on get_tenant_db, so row-level "
        f"security never engages for it (Constitution I)"
    )
    assert get_db not in functions, (
        f"{method} {path} takes get_db directly; a tenant-scoped handler must "
        f"query on get_tenant_db so RLS engages"
    )


@pytest.mark.parametrize(
    ("method", "path", "task"),
    FEATURE_ROUTES,
    ids=[f"{m} {p}" for m, p, _ in FEATURE_ROUTES],
)
def test_route_resolves_the_tenant_from_the_token(method: str, path: str, task: str) -> None:
    """Every pricing route must resolve its tenant through the dependency."""
    from app.auth.dependencies import get_current_tenant

    route = _registered().get((method, path))
    if route is None:
        pytest.skip(f"{method} {path} arrives with task {task}")

    assert get_current_tenant in _dependency_functions(route), (
        f"{method} {path} never resolves a tenant, so nothing scopes its queries"
    )


# ---------------------------------------------------------------------------
# The storefront, which carries a tenant but never a token (T171)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "task"),
    SHOP_ROUTES,
    ids=[f"{m} {p}" for m, p, _ in SHOP_ROUTES],
)
def test_shop_route_uses_the_shop_scoped_session(method: str, path: str, task: str) -> None:
    """A storefront handler must take ``get_shop_db``, never ``get_db``.

    Every storefront sale used to be written on the un-scoped session, with
    row-level security absent at the one layer this system does not rely on
    remembering to filter. `get_tenant_db` cannot help here -- there is no
    token to read a tenant from -- so `get_shop_db` sets the RLS variable from
    the tenant resolved out of `X-Shop-Hostname` instead (Constitution I,
    FR-036).
    """
    route = _registered().get((method, path))
    if route is None:
        pytest.skip(f"{method} {path} arrives with task {task}")

    functions = _handler_dependency_functions(route)
    assert get_shop_db in functions, (
        f"{method} {path} does not depend on get_shop_db, so row-level security "
        f"never engages for it (Constitution I)"
    )
    assert get_db not in functions, (
        f"{method} {path} takes get_db directly; a storefront handler must query "
        f"on get_shop_db so RLS engages"
    )


@pytest.mark.parametrize(
    ("method", "path", "task"),
    SHOP_ROUTES,
    ids=[f"{m} {p}" for m, p, _ in SHOP_ROUTES],
)
def test_shop_route_resolves_its_tenant_from_the_hostname(
    method: str, path: str, task: str
) -> None:
    """The scoped session is only as good as the tenant it was given."""
    from app.auth.dependencies import get_shop_tenant

    route = _registered().get((method, path))
    if route is None:
        pytest.skip(f"{method} {path} arrives with task {task}")

    assert get_shop_tenant in _dependency_functions(route), (
        f"{method} {path} never resolves a shop tenant, so nothing scopes its queries"
    )


def test_the_shop_db_dependency_sets_the_rls_variable() -> None:
    """The dependency must actually issue the statement RLS reads.

    Checked against the source rather than by running it, because the point is
    that the variable is set for *every* storefront request, not only the ones
    a test happens to exercise.
    """
    import inspect

    from app.auth.dependencies import get_shop_db as dependency

    source = inspect.getsource(dependency)
    assert "SET LOCAL app.current_tenant_id" in source, (
        "get_shop_db must issue SET LOCAL app.current_tenant_id, or it is just "
        "another un-scoped session with a different name"
    )
    assert "shop_tenant.id" in source, (
        "the tenant must come from the resolved shop tenant, not from request state, "
        "which a storefront request never carries"
    )


def test_only_the_image_route_remains_unscoped() -> None:
    """One documented exception, and nothing else drifting back.

    `GET /shop/images/{product_id}/{image_filename}` is served straight to a browser
    from an `<img src>`, which cannot send the `X-Shop-Hostname` header a
    scoped session resolves its tenant from. It reads one row of cache
    metadata and writes nothing. Every other handler in the router is scoped,
    and this test fails if a new one is added on `get_db`.
    """
    from app.api.v1 import shop

    unscoped = []
    for route in shop.router.routes:
        if not isinstance(route, APIRoute):
            continue
        if get_db in _handler_dependency_functions(route):
            unscoped.append(f"{sorted(route.methods or [])} {route.path}")

    assert unscoped == ["['GET'] /images/{product_id}/{image_filename}"], (
        f"unexpected storefront handlers on the un-scoped session: {unscoped}"
    )


# ---------------------------------------------------------------------------
# Invisibility, exercised over HTTP against a genuine second tenant
# ---------------------------------------------------------------------------


@pytest.fixture
async def other_tenant(db_session: AsyncSession) -> Tenant:
    """A second tenant whose rows the authenticated tenant must never see."""
    tenant = Tenant(
        id=uuid4(),
        name="Other Workshop",
        slug=f"other-workshop-{uuid4().hex[:8]}",
        tenant_type="three_d_print",
        is_active=True,
        settings={},
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest.fixture
async def other_tenants_product(db_session: AsyncSession, other_tenant: Tenant) -> Product:
    product = Product(
        id=uuid4(),
        tenant_id=other_tenant.id,
        sku="OTHER-PROD-001",
        name="Someone else's product",
        is_active=True,
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest.fixture
async def other_tenants_model(db_session: AsyncSession, other_tenant: Tenant) -> Model:
    model = Model(
        id=uuid4(),
        tenant_id=other_tenant.id,
        sku="OTHER-MODEL-001",
        name="Someone else's model",
        labor_hours=Decimal("0.25"),
        is_active=True,
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


@pytest.fixture
async def other_tenants_channel(db_session: AsyncSession, other_tenant: Tenant) -> SalesChannel:
    channel = SalesChannel(
        id=uuid4(),
        tenant_id=other_tenant.id,
        name="Someone else's channel",
        platform_type="etsy",
        monthly_cost=Decimal("0"),
        is_active=True,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return channel


class TestCostBearingReadsDoNotLeakAcrossTenants:
    """The routes that already serve a cost must not serve someone else's."""

    async def test_product_detail_hides_another_tenants_product(
        self, client: AsyncClient, other_tenants_product: Product
    ) -> None:
        response = await client.get(f"{API}/products/{other_tenants_product.id}")
        assert response.status_code == 404, (
            f"product detail answered {response.status_code} for another tenant's "
            f"product: {response.text[:400]}"
        )

    async def test_model_detail_hides_another_tenants_model(
        self, client: AsyncClient, other_tenants_model: Model
    ) -> None:
        response = await client.get(f"{API}/models/{other_tenants_model.id}")
        assert response.status_code == 404, (
            f"model detail answered {response.status_code} for another tenant's model"
        )

    async def test_product_list_omits_another_tenants_products(
        self, client: AsyncClient, other_tenants_product: Product, test_product: Product
    ) -> None:
        response = await client.get(f"{API}/products", params={"limit": 200})
        assert response.status_code == 200
        skus = {item["sku"] for item in response.json()["products"]}
        assert other_tenants_product.sku not in skus
        assert test_product.sku in skus

    async def test_model_list_omits_another_tenants_models(
        self, client: AsyncClient, other_tenants_model: Model, test_model: Model
    ) -> None:
        response = await client.get(f"{API}/models", params={"limit": 200})
        assert response.status_code == 200
        skus = {item["sku"] for item in response.json()["models"]}
        assert other_tenants_model.sku not in skus
        assert test_model.sku in skus

    async def test_pricing_cannot_be_written_against_another_tenants_channel(
        self,
        client: AsyncClient,
        test_product: Product,
        other_tenants_channel: SalesChannel,
    ) -> None:
        """A price on a foreign channel would read a foreign fee structure."""
        response = await client.post(
            f"{API}/products/{test_product.id}/pricing",
            json={
                "sales_channel_id": str(other_tenants_channel.id),
                "list_price": "64.99",
                "is_active": True,
            },
        )
        assert response.status_code in (400, 403, 404, 422), (
            f"pricing accepted another tenant's channel with "
            f"{response.status_code}: {response.text[:400]}"
        )


class TestTheHarnessItselfIsWired:
    """A harness that silently covers nothing is worse than none."""

    def test_the_route_list_is_not_empty(self) -> None:
        assert FEATURE_ROUTES, "the feature's route list was emptied"

    def test_every_declared_route_names_the_task_that_adds_it(self) -> None:
        for method, path, task in FEATURE_ROUTES:
            assert task.startswith("T"), f"{method} {path} has no task reference"

    def test_dependency_inspection_finds_what_it_claims_to(self) -> None:
        """Prove the inspector can see a session dependency on a real route."""
        route = _registered().get(("GET", f"{API}/products"))
        assert route is not None, (
            "the product list route was not found; the inspector is untested and "
            "every assertion above may be skipping silently"
        )
        functions = _dependency_functions(route)
        assert get_db in functions or get_tenant_db in functions, (
            "dependency inspection found no session dependency on a route that "
            "certainly has one, so the assertions above prove nothing"
        )

    def test_the_handler_level_inspector_is_narrower_than_the_transitive_one(
        self,
    ) -> None:
        """Prove the shallow inspector really is shallow.

        If it quietly returned the transitive set, the session assertion would
        be unsatisfiable again and every pricing route would fail; if it
        returned nothing, the assertion would pass vacuously. A route whose
        auth chain reaches `get_db` below the surface shows it does neither.
        """
        route = _registered().get(("GET", f"{API}/settings/pricing-policy"))
        assert route is not None, (
            "the pricing policy route was not found; this check proves nothing"
        )
        shallow = _handler_dependency_functions(route)
        transitive = _dependency_functions(route)

        assert shallow, "the handler-level inspector found no dependencies at all"
        assert get_db in transitive, (
            "authentication no longer reaches get_db, so this route cannot show "
            "the difference between the two inspectors -- pick another"
        )
        assert get_db not in shallow
        assert shallow < transitive

    def test_the_prefix_map_matches_the_app(self) -> None:
        """Every path the harness believes in must be one the app publishes.

        A wrong prefix would make every check above skip while reporting
        nothing amiss, which is the quiet failure this harness exists to catch.
        """
        published = set(app.openapi()["paths"])
        for (_method, path), _route in _registered().items():
            assert path in published, (
                f"the harness built {path} from ROUTER_PREFIXES but the app does "
                f"not publish it; the prefix map has drifted from app/main.py"
            )


# ---------------------------------------------------------------------------
# The webhook, which carries neither a token nor a hostname (T184)
# ---------------------------------------------------------------------------


def test_the_shopify_webhook_scopes_its_own_session() -> None:
    """The Shopify ingest must engage RLS once its tenant is resolved.

    Neither session dependency can serve this route. `get_tenant_db` reads
    `request.state.tenant_id`, which `TenantContextMiddleware` sets from a JWT,
    and Shopify sends none; `get_shop_db` resolves its tenant from
    `X-Shop-Hostname`, which Shopify does not send either. The tenant arrives
    in the `{tenant_slug}` path segment, so it is only known partway through
    the handler -- after the session is open and before the first write.

    So the claim checked here is not about a dependency but about the handler:
    that it calls `scope_session_to_tenant` with the tenant it resolved, and
    does so before creating the order, its line items and the FR-036 sale
    snapshot (Constitution I, FR-036).
    """
    import inspect

    from app.api.v1 import shopify_webhooks

    source = inspect.getsource(shopify_webhooks.shopify_webhook)

    assert "scope_session_to_tenant(db, tenant.id)" in source, (
        "the Shopify webhook creates an order, its items and its sale snapshot; "
        "without scope_session_to_tenant none of those writes has row-level "
        "security in force (Constitution I)"
    )

    scoped_at = source.index("scope_session_to_tenant")
    for write in ("db.add(order)", "write_sale_snapshot("):
        assert write in source, f"the handler no longer performs {write}"
        assert scoped_at < source.index(write), (
            f"the session is scoped after {write}, so that write still runs "
            f"un-scoped -- SET LOCAL has to precede the writes it protects"
        )


def test_the_scoping_helper_issues_the_statement_rls_reads() -> None:
    """The helper must set the variable, and from the tenant it was given."""
    import inspect

    from app.database import scope_session_to_tenant

    source = inspect.getsource(scope_session_to_tenant)
    assert "SET LOCAL app.current_tenant_id" in source, (
        "scope_session_to_tenant must issue SET LOCAL app.current_tenant_id, "
        "or it is a no-op with a reassuring name"
    )
    assert "settings.rls_enabled" in source, (
        "the helper must respect the RLS toggle, as both session dependencies do"
    )


# ---------------------------------------------------------------------------
# The whole route population, derived (T204)
# ---------------------------------------------------------------------------
#
# Everything above asserts over hand-written lists, and a hand-written list is
# covered by absence: a route nobody added is a route nobody checks. The lists
# above name 64 routes; the app serves 373, of which 144 take the un-scoped
# session, and not one of those 144 appeared above. That is how T181, T183,
# T184, T192, T197, T198, T203 and T205 each had to be *found*, by reading
# routers one at a time, instead of failing a test.
#
# So the population is derived here instead:
#
# * the mount map comes from `app/main.py` itself, by parsing its
#   `include_router` calls -- the one place that decides where a router is
#   mounted, rather than a copy of it that drifts;
# * every router it names is imported and walked, because FastAPI mounts
#   routers lazily and `app.routes` holds internal placeholders rather than
#   the `APIRoute` objects whose dependency graph is the thing under test;
# * each route must take one of the four scoped sessions, or be named below.
#
# `NOT_YET_SCOPED` is the consequence: the 120 routes still on `get_db` that
# are not deliberate exceptions, listed by module. It is asserted as an exact
# set, so it can only shrink -- a route moved onto a scoped session and left
# on the list fails here, and so does a new route added on `get_db`.

MAIN_PY = Path(__file__).resolve().parents[2] / "app" / "main.py"

#: What `prefix=settings.api_v1_prefix` evaluates to, in either spelling.
_SETTINGS_PREFIX = ("settings.api_v1_prefix", "settings.API_V1_PREFIX")


def _prefix_value(node: ast.AST) -> Optional[str]:
    """The string a `prefix=` argument in main.py evaluates to, or None.

    Only the three forms main.py actually uses are understood -- a literal,
    `settings.api_v1_prefix`, and an f-string built from it. Anything else
    returns None and fails `test_every_mounted_router_has_a_known_prefix`
    rather than being silently skipped, which is the failure mode this whole
    section exists to remove.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute) and ast.unparse(node) in _SETTINGS_PREFIX:
        return API
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            elif isinstance(piece, ast.FormattedValue):
                if ast.unparse(piece.value) not in _SETTINGS_PREFIX:
                    return None
                parts.append(API)
            else:
                return None
        return "".join(parts)
    return None


def _mounted() -> dict[str, Optional[str]]:
    """Every `app.api.v1` router main.py mounts, with the prefix it mounts at.

    A prefix of None means the call was found but its `prefix=` could not be
    read, which is a failure rather than an omission.
    """
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))

    # `from app.api.v1 import (settings as settings_api, ...)` -- the local
    # name in the include_router call is not always the module name.
    local_to_module: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.api.v1":
            for alias in node.names:
                local_to_module[alias.asname or alias.name] = alias.name

    found: dict[str, Optional[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "include_router"):
            continue
        if not node.args:
            continue
        target = node.args[0]
        if not (isinstance(target, ast.Attribute) and target.attr == "router"):
            continue
        if not isinstance(target.value, ast.Name):
            continue
        module = local_to_module.get(target.value.id, target.value.id)
        prefix: Optional[str] = ""
        for keyword in node.keywords:
            if keyword.arg == "prefix":
                prefix = _prefix_value(keyword.value)
        found.setdefault(module, prefix)
    return found


def _population() -> dict[tuple[str, str], tuple[APIRoute, str]]:
    """Every (method, path) the app serves, with its route and module."""
    import importlib

    found: dict[tuple[str, str], tuple[APIRoute, str]] = {}
    for module_name, prefix in _mounted().items():
        if prefix is None:
            continue
        try:
            module = importlib.import_module(f"app.api.v1.{module_name}")
        except ModuleNotFoundError:  # pragma: no cover - a router from later
            continue
        router = getattr(module, "router", None)
        if router is None:
            continue
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods or set():
                found[(method, f"{prefix}{route.path}")] = (route, module_name)
    return found


def _scoped_sessions() -> set:
    """The four dependencies that put a tenant on the session."""
    from app.auth.customer_dependencies import get_customer_db
    from app.auth.dependencies import get_platform_admin_db, get_shop_db, get_tenant_db

    # `get_platform_admin_db` is scoped in the other direction -- it serves a
    # platform admin across tenants on purpose -- but it is a deliberate,
    # role-gated session rather than a handler that forgot one, so it counts.
    return {get_tenant_db, get_shop_db, get_customer_db, get_platform_admin_db}


#: Routers with no tenant to scope to, by design.
#:
#: Authentication has to run before any tenant is known: `auth.py` and
#: `customer_auth.py` resolve credentials into a token, and `onboarding.py`
#: creates the tenant. `shop_resolver.py` answers "which tenant is this
#: hostname" and is the lookup `get_shop_db` itself depends on, so it cannot
#: depend on a session that depends on it.
UNSCOPED_ENTRY_POINT_MODULES: frozenset[str] = frozenset(
    {"auth", "customer_auth", "onboarding", "shop_resolver"}
)

#: Individual routes with no tenant at the moment the session opens.
UNSCOPED_ROUTES_BY_DESIGN: dict[tuple[str, str], str] = {
    ("POST", f"{API}/payments/webhooks/square"): (
        "Square posts this; the tenant is only known once the payment is "
        "matched, which happens inside the handler"
    ),
    ("POST", f"{API}/shopify/webhooks/{{tenant_slug}}"): (
        "Shopify sends neither a token nor X-Shop-Hostname; the handler calls "
        "scope_session_to_tenant itself once the slug resolves (T184), which "
        "test_the_shopify_webhook_scopes_its_own_session asserts"
    ),
    ("GET", f"{API}/shop/images/{{product_id}}/{{image_filename}}"): (
        "served straight to a browser from an <img src>, which cannot send "
        "the X-Shop-Hostname header a scoped session resolves its tenant from"
    ),
}


#: Routes still on the un-scoped session, with no deliberate reason.
#:
#: This is the list the derivation above makes visible. Every entry is a
#: handler whose queries run without `app.current_tenant_id` set, relying on
#: an application-level `tenant_id` filter as its only belt -- which
#: Constitution I rules out as a sole protection. None of them is a pricing
#: path, which is why this feature did not move them; they are listed so that
#: the next change finds them already named instead of reading 50 routers to
#: discover them again.
#:
#: Asserted as an exact set, so it only shrinks. Moving a route onto a scoped
#: session and forgetting to delete its line here fails
#: `test_no_scoped_route_is_still_listed_as_unscoped`; adding a new route on
#: `get_db` fails `test_every_route_is_scoped_or_named`.
NOT_YET_SCOPED: set[tuple[str, str]] = {
    # audit.py (5)
    ("GET", f"{API}/audit"),
    ("GET", f"{API}/audit/summary"),
    ("GET", f"{API}/audit/entity/{{entity_type}}/{{entity_id}}"),
    ("GET", f"{API}/audit/user/{{user_id}}"),
    ("GET", f"{API}/audit/actions"),
    # categories.py (8)
    ("GET", f"{API}/categories"),
    ("GET", f"{API}/categories/{{category_id}}"),
    ("POST", f"{API}/categories"),
    ("PATCH", f"{API}/categories/{{category_id}}"),
    ("DELETE", f"{API}/categories/{{category_id}}"),
    ("GET", f"{API}/categories/{{category_id}}/products"),
    ("POST", f"{API}/categories/{{category_id}}/products/{{product_id}}"),
    ("DELETE", f"{API}/categories/{{category_id}}/products/{{product_id}}"),
    # dashboard.py (6)
    ("GET", f"{API}/dashboard/summary"),
    ("GET", f"{API}/dashboard/active-production"),
    ("GET", f"{API}/dashboard/low-stock"),
    ("GET", f"{API}/dashboard/recent-activity"),
    ("GET", f"{API}/dashboard/performance-charts"),
    ("GET", f"{API}/dashboard/failure-analytics"),
    # designers.py (5)
    ("GET", f"{API}/designers"),
    ("GET", f"{API}/designers/{{designer_id}}"),
    ("POST", f"{API}/designers"),
    ("PATCH", f"{API}/designers/{{designer_id}}"),
    ("DELETE", f"{API}/designers/{{designer_id}}"),
    # forecasting.py (4)
    ("GET", f"{API}/forecasting/demand/{{product_id}}"),
    ("GET", f"{API}/forecasting/reorder/{{product_id}}"),
    ("GET", f"{API}/forecasting/reorder-recommendations"),
    ("GET", f"{API}/forecasting/stock-health"),
    # model_files.py (10)
    ("POST", f"{API}/models/{{model_id}}/files"),
    ("POST", f"{API}/models/{{model_id}}/files/link-local"),
    ("POST", f"{API}/models/validate-local-path"),
    ("POST", f"{API}/models/files/parse-3mf"),
    ("GET", f"{API}/models/{{model_id}}/files"),
    ("GET", f"{API}/models/{{model_id}}/files/primary"),
    ("GET", f"{API}/models/{{model_id}}/files/{{file_id}}"),
    ("GET", f"{API}/models/{{model_id}}/files/{{file_id}}/download"),
    ("PATCH", f"{API}/models/{{model_id}}/files/{{file_id}}"),
    ("DELETE", f"{API}/models/{{model_id}}/files/{{file_id}}"),
    # modules.py (2)
    ("GET", f"{API}/modules"),
    ("GET", f"{API}/modules/{{module_name}}"),
    # newsletter.py (1)
    ("POST", f"{API}/newsletter/subscribe"),
    # pages.py (5)
    ("GET", f"{API}/pages"),
    ("GET", f"{API}/pages/{{page_id}}"),
    ("POST", f"{API}/pages"),
    ("PATCH", f"{API}/pages/{{page_id}}"),
    ("DELETE", f"{API}/pages/{{page_id}}"),
    # payments.py (2)
    ("GET", f"{API}/payments/config"),
    ("GET", f"{API}/payments/status/{{payment_id}}"),
    # printer_bambu.py (12)
    ("POST", f"{API}/printers/{{printer_id}}/connection"),
    ("GET", f"{API}/printers/{{printer_id}}/connection"),
    ("PUT", f"{API}/printers/{{printer_id}}/connection"),
    ("DELETE", f"{API}/printers/{{printer_id}}/connection"),
    ("POST", f"{API}/printers/{{printer_id}}/connection/connect"),
    ("POST", f"{API}/printers/{{printer_id}}/connection/disconnect"),
    ("GET", f"{API}/printers/{{printer_id}}/status"),
    ("GET", f"{API}/printers/{{printer_id}}/ams"),
    ("POST", f"{API}/printers/{{printer_id}}/ams/map"),
    ("DELETE", f"{API}/printers/{{printer_id}}/ams/{{ams_id}}/{{tray_id}}"),
    ("GET", f"{API}/printers/{{printer_id}}/ams/live"),
    ("POST", f"{API}/printers/{{printer_id}}/ams/sync"),
    # printers.py (1)
    ("GET", f"{API}/printers/models"),
    # production_runs.py (1)
    ("GET", f"{API}/production-runs/failure-reasons"),
    # reviews.py (6)
    ("GET", f"{API}/reviews"),
    ("GET", f"{API}/reviews/{{review_id}}"),
    ("PUT", f"{API}/reviews/{{review_id}}"),
    ("POST", f"{API}/reviews/{{review_id}}/approve"),
    ("POST", f"{API}/reviews/{{review_id}}/reject"),
    ("DELETE", f"{API}/reviews/{{review_id}}"),
    # settings.py (16)
    ("GET", f"{API}/settings/square"),
    ("PUT", f"{API}/settings/square"),
    ("POST", f"{API}/settings/square/test"),
    ("GET", f"{API}/settings/etsy"),
    ("PUT", f"{API}/settings/etsy"),
    ("POST", f"{API}/settings/etsy/test"),
    ("GET", f"{API}/settings/tenant"),
    ("PUT", f"{API}/settings/tenant"),
    ("GET", f"{API}/settings/shop"),
    ("PUT", f"{API}/settings/shop"),
    ("GET", f"{API}/settings/branding"),
    ("PUT", f"{API}/settings/branding"),
    ("POST", f"{API}/settings/custom-domain"),
    ("GET", f"{API}/settings/custom-domain/status"),
    ("POST", f"{API}/settings/custom-domain/verify"),
    ("DELETE", f"{API}/settings/custom-domain"),
    # shipping.py (3)
    ("POST", f"{API}/shipping/rates"),
    ("GET", f"{API}/shipping/validate-postcode/{{postcode}}"),
    ("GET", f"{API}/shipping/methods"),
    # shop.py (5)
    ("GET", f"{API}/shop/cart/{{session_id}}"),
    ("POST", f"{API}/shop/cart"),
    ("DELETE", f"{API}/shop/cart/{{session_id}}/items/{{item_id}}"),
    ("PATCH", f"{API}/shop/cart/{{session_id}}/items/{{item_id}}"),
    ("POST", f"{API}/shop/contact"),
    # sku.py (2)
    ("GET", f"{API}/sku/next/{{entity_type}}"),
    ("GET", f"{API}/sku/check/{{entity_type}}/{{sku}}"),
    # spoolmandb.py (6)
    ("GET", f"{API}/spoolmandb/stats"),
    ("POST", f"{API}/spoolmandb/sync"),
    ("GET", f"{API}/spoolmandb/manufacturers"),
    ("GET", f"{API}/spoolmandb/filaments"),
    ("GET", f"{API}/spoolmandb/filaments/{{filament_id}}"),
    ("GET", f"{API}/spoolmandb/materials"),
    # tenant_members.py (4)
    ("GET", f"{API}/tenant/members"),
    ("POST", f"{API}/tenant/members/invite"),
    ("PUT", f"{API}/tenant/members/{{member_id}}"),
    ("DELETE", f"{API}/tenant/members/{{member_id}}"),
    # test.py (4)
    ("POST", f"{API}/test/email"),
    ("GET", f"{API}/test/me"),
    ("GET", f"{API}/test/materials"),
    ("GET", f"{API}/test/admin-only"),
    # users.py (1)
    ("GET", f"{API}/users/me"),
    # webhooks.py (11)
    ("POST", f"{API}/webhooks/subscriptions"),
    ("GET", f"{API}/webhooks/subscriptions"),
    ("GET", f"{API}/webhooks/subscriptions/{{subscription_id}}"),
    ("PUT", f"{API}/webhooks/subscriptions/{{subscription_id}}"),
    ("DELETE", f"{API}/webhooks/subscriptions/{{subscription_id}}"),
    ("POST", f"{API}/webhooks/subscriptions/{{subscription_id}}/regenerate-secret"),
    ("POST", f"{API}/webhooks/subscriptions/{{subscription_id}}/test"),
    ("GET", f"{API}/webhooks/deliveries"),
    ("GET", f"{API}/webhooks/deliveries/{{delivery_id}}"),
    ("POST", f"{API}/webhooks/deliveries/{{delivery_id}}/retry"),
    ("GET", f"{API}/webhooks/event-types"),
}


def _population_ids() -> list[tuple[str, str]]:
    """The derived population, ordered so parametrisation ids are stable."""
    return sorted(_population())


@pytest.mark.parametrize(
    ("method", "path"),
    _population_ids(),
    ids=[f"{m} {p}" for m, p in _population_ids()],
)
def test_every_route_is_scoped_or_named(method: str, path: str) -> None:
    """Every route the app serves takes a scoped session, or is named above.

    This is the assertion the hand-written lists could not make. It runs over
    the whole derived population, so a route added on `get_db` fails here the
    moment it is registered -- it does not have to be remembered into a list
    first (Constitution I, II).

    A route that is genuinely scoped must not also appear in
    `NOT_YET_SCOPED`; that direction is checked by
    :func:`TestTheUnscopedListOnlyShrinks`, so this one only has to allow it.
    """
    route, module_name = _population()[(method, path)]

    if module_name in UNSCOPED_ENTRY_POINT_MODULES:
        pytest.skip(f"{module_name}.py has no tenant to scope to: it is an entry point")
    if (method, path) in UNSCOPED_ROUTES_BY_DESIGN:
        pytest.skip(UNSCOPED_ROUTES_BY_DESIGN[(method, path)])

    scoped = _scoped_sessions()
    if not (_dependency_functions(route) & scoped):
        assert (method, path) in NOT_YET_SCOPED, (
            f"{method} {path} ({module_name}.py) queries on the un-scoped "
            f"session, so row-level security never engages for it "
            f"(Constitution I). Move it onto get_tenant_db -- or onto "
            f"get_shop_db / get_customer_db if it is a storefront or customer "
            f"surface -- or, if it genuinely has no tenant, name it in "
            f"UNSCOPED_ROUTES_BY_DESIGN with the reason."
        )
        pytest.skip(f"{method} {path} is on the NOT_YET_SCOPED list")

    assert get_db not in _handler_dependency_functions(route), (
        f"{method} {path} ({module_name}.py) takes a scoped session *and* "
        f"get_db; the handler's own queries must run on the scoped one"
    )


class TestTheDerivationCoversTheWholeApp:
    """A derivation that quietly covers nothing is the bug it replaces."""

    def test_main_mounts_the_routers_this_harness_walks(self) -> None:
        mounted = _mounted()
        assert len(mounted) > 40, (
            f"only {len(mounted)} routers were read out of app/main.py; the "
            f"include_router parsing has stopped matching and the population "
            f"below is a fraction of the app"
        )

    def test_every_mounted_router_has_a_known_prefix(self) -> None:
        """An unreadable prefix drops a whole router out of the population."""
        unreadable = sorted(name for name, prefix in _mounted().items() if prefix is None)
        assert unreadable == [], (
            f"the prefix main.py mounts these routers at could not be read, so "
            f"none of their routes is checked: {unreadable}. Teach "
            f"_prefix_value the form it uses."
        )

    def test_the_population_is_the_whole_api(self) -> None:
        population = _population()
        assert len(population) > 300, (
            f"the derivation found only {len(population)} routes; the app "
            f"serves well over three hundred, so something is being skipped"
        )

    def test_every_derived_path_is_one_the_app_publishes(self) -> None:
        """The paths are built from a parse, so they are checked against truth.

        A wrong prefix would make every assertion above pass against a path
        nobody serves, which is exactly the quiet failure this replaces.
        """
        published = set(app.openapi()["paths"])
        missing = sorted({path for _method, path in _population()} - published)
        assert missing == [], (
            f"these paths were derived from app/main.py but the app does not "
            f"publish them: {missing[:10]}"
        )

    def test_the_hand_written_lists_are_inside_the_derived_population(self) -> None:
        """The two halves must agree about what the app serves."""
        population = set(_population())
        declared = {(m, p) for m, p, _ in FEATURE_ROUTES + SHOP_ROUTES}
        assert declared <= population, (
            f"routes are declared above that the derivation never found, so "
            f"the two disagree about the app: {sorted(declared - population)}"
        )

    def test_the_derivation_can_tell_a_scoped_route_from_an_unscoped_one(self) -> None:
        """Prove the check discriminates, rather than passing either way."""
        population = _population()
        scoped = _scoped_sessions()

        policy = population.get(("GET", f"{API}/settings/pricing-policy"))
        assert policy is not None, "the pricing policy route vanished; this proves nothing"
        assert _dependency_functions(policy[0]) & scoped, (
            "a route known to take get_tenant_db does not register as scoped, "
            "so every assertion above passes vacuously"
        )

        entry = population.get(("POST", f"{API}/auth/login"))
        assert entry is not None, "the login route vanished; this proves nothing"
        assert not (_dependency_functions(entry[0]) & scoped), (
            "a route known to take no scoped session registers as scoped, so the check cannot fail"
        )


class TestTheUnscopedListOnlyShrinks:
    """The remaining routes are a visible list, not a discovery each round."""

    def test_no_scoped_route_is_still_listed_as_unscoped(self) -> None:
        """Fixing a route means deleting its line, in the same change."""
        population = _population()
        scoped = _scoped_sessions()

        fixed = sorted(
            entry
            for entry in NOT_YET_SCOPED
            if entry in population and (_dependency_functions(population[entry][0]) & scoped)
        )
        assert fixed == [], (
            f"these routes now take a scoped session but are still listed in "
            f"NOT_YET_SCOPED; delete their lines: {fixed}"
        )

    def test_every_listed_route_is_one_the_app_serves(self) -> None:
        """A stale entry excuses nothing and hides a real route."""
        population = set(_population())
        stale = sorted(NOT_YET_SCOPED - population)
        assert stale == [], (
            f"NOT_YET_SCOPED names routes the app does not serve, so the list "
            f"has drifted from the app: {stale}"
        )

    def test_no_pricing_route_is_on_the_list(self) -> None:
        """The list is for the rest of the app, never for a money path."""
        declared = {(m, p) for m, p, _ in FEATURE_ROUTES + SHOP_ROUTES}
        excused = sorted(NOT_YET_SCOPED & declared)
        assert excused == [], (
            f"a route this feature declares is on the NOT_YET_SCOPED list; a "
            f"pricing path is never excused from Constitution I: {excused}"
        )

    def test_the_list_is_not_empty_without_the_check_being_tightened(self) -> None:
        """When it empties, the `pytest.skip` above becomes dead -- say so.

        This is not a requirement that routes stay unscoped. It fails when the
        list reaches zero so that the escape hatch in
        `test_every_route_is_scoped_or_named` is removed in the same change,
        rather than left behind as an allow-list with nothing in it.
        """
        assert NOT_YET_SCOPED, (
            "NOT_YET_SCOPED is empty -- every route is scoped now. Delete the "
            "list and the `assert ... in NOT_YET_SCOPED` branch in "
            "test_every_route_is_scoped_or_named, so an unscoped route fails "
            "outright instead of needing to be listed first."
        )
