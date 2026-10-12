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

from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_tenant_db
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
    "provenance": f"{API}/provenance",
    "scenarios": f"{API}/scenarios",
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
        fee_percentage=Decimal("6.5"),
        fee_fixed=Decimal("0.20"),
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
