"""The labor rate the operator configured is the one the system uses.

Constitution IV: *a value the operator configured MUST be the value the system
uses: a hardcoded default silently shadowing a tenant setting is a defect, not
a fallback.*

`Tenant.settings["default_labor_rate"]` was written by the settings UI and read
by nobody. Every cost on every screen used `CostingService`'s own
`DEFAULT_LABOR_RATE` of 10.00 instead -- a figure the operator never chose and
could not change.

**This test must never be made to pass by restoring the hardcoded rate**, and
the rate below is deliberately absurd (CA$137.00/h) so that no plausible
default could coincide with it. A suite that turns green by reverting the fix
is a failed change, not a passing one (Constitution, Development Workflow).

The HTTP cases cover the endpoints an operator actually looks at. The source
scan covers the call sites no response reaches, which is what makes the claim
"every call site" checkable rather than hopeful.
"""

import ast
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.tenant import Tenant
from app.services.tenant_cost_settings import tenant_labor_rate

API = "/api/v1"

#: Nothing in the codebase could default to this, so a figure derived from it
#: proves the configured value was read.
DISTINCTIVE_RATE = Decimal("137.00")

#: The rate the engine used to hardcode. Any figure matching this one is the
#: defect, not the fix.
SUPERSEDED_HARDCODED_RATE = Decimal("10.00")

LABOR_HOURS = Decimal("0.25")

#: `Product.assembly_minutes` is an Integer column, so the stored value is an
#: int; it becomes a Decimal only once it reaches the arithmetic.
ASSEMBLY_MINUTES_STORED = 30
ASSEMBLY_MINUTES = Decimal(ASSEMBLY_MINUTES_STORED)


@pytest.fixture
async def rate_tenant(db_session: AsyncSession, test_tenant: Tenant) -> Tenant:
    """The authenticated tenant, with a labor rate nobody could guess."""
    test_tenant.settings = {**(test_tenant.settings or {}), "default_labor_rate": "137.00"}
    db_session.add(test_tenant)
    await db_session.commit()
    await db_session.refresh(test_tenant)
    return test_tenant


@pytest.fixture
async def costed_model(db_session: AsyncSession, rate_tenant: Tenant, test_spool) -> Model:
    """A model whose cost is mostly labor, so the rate dominates the figure."""
    model = Model(
        id=uuid4(),
        tenant_id=rate_tenant.id,
        sku=f"RATE-MODEL-{uuid4().hex[:6]}",
        name="Rate probe model",
        labor_hours=LABOR_HOURS,
        is_active=True,
    )
    db_session.add(model)
    await db_session.flush()
    db_session.add(
        ModelMaterial(
            id=uuid4(),
            model_id=model.id,
            spool_id=test_spool.id,
            weight_grams=Decimal("142"),
            cost_per_gram=Decimal("0.0310"),
        )
    )
    await db_session.commit()
    await db_session.refresh(model)
    return model


@pytest.fixture
async def costed_product(
    db_session: AsyncSession, rate_tenant: Tenant, costed_model: Model
) -> Product:
    product = Product(
        id=uuid4(),
        tenant_id=rate_tenant.id,
        sku=f"RATE-PROD-{uuid4().hex[:6]}",
        name="Rate probe product",
        assembly_minutes=ASSEMBLY_MINUTES_STORED,
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()
    db_session.add(
        ProductModel(id=uuid4(), product_id=product.id, model_id=costed_model.id, quantity=1)
    )
    await db_session.commit()
    await db_session.refresh(product)
    return product


# ---------------------------------------------------------------------------
# The resolver itself
# ---------------------------------------------------------------------------


class TestTheResolverReadsTheSetting:
    def test_it_returns_the_configured_rate(self, rate_tenant: Tenant) -> None:
        assert tenant_labor_rate(rate_tenant) == DISTINCTIVE_RATE

    def test_it_converts_through_str_so_a_json_float_stays_exact(self, test_tenant: Tenant) -> None:
        """`Decimal(20.1)` from a float carries the float's error; `Decimal("20.1")` does not."""
        test_tenant.settings = {"default_labor_rate": 20.1}
        assert tenant_labor_rate(test_tenant) == Decimal("20.1")

    def test_it_accepts_an_integer(self, test_tenant: Tenant) -> None:
        test_tenant.settings = {"default_labor_rate": 25}
        assert tenant_labor_rate(test_tenant) == Decimal("25")

    def test_an_unset_rate_falls_back_to_the_documented_default_not_to_ten(
        self, test_tenant: Tenant
    ) -> None:
        from app.services.tenant_cost_settings import FALLBACK_LABOR_RATE

        test_tenant.settings = {}
        resolved = tenant_labor_rate(test_tenant)
        assert resolved == FALLBACK_LABOR_RATE
        assert resolved != SUPERSEDED_HARDCODED_RATE, (
            "the fallback is the figure the settings screen shows an operator, "
            "not the engine's old hardcoded 10.00"
        )

    def test_a_nonsense_value_falls_back_rather_than_crashing_a_price_screen(
        self, test_tenant: Tenant
    ) -> None:
        from app.services.tenant_cost_settings import FALLBACK_LABOR_RATE

        test_tenant.settings = {"default_labor_rate": "twenty quid"}
        assert tenant_labor_rate(test_tenant) == FALLBACK_LABOR_RATE

    def test_a_negative_rate_is_rejected(self, test_tenant: Tenant) -> None:
        from app.services.tenant_cost_settings import FALLBACK_LABOR_RATE

        test_tenant.settings = {"default_labor_rate": "-5"}
        assert tenant_labor_rate(test_tenant) == FALLBACK_LABOR_RATE


# ---------------------------------------------------------------------------
# The rate reaches the endpoints an operator looks at
# ---------------------------------------------------------------------------


class TestTheRateReachesTheModelEndpoints:
    async def test_model_detail_labor_cost_uses_the_configured_rate(
        self, client: AsyncClient, costed_model: Model
    ) -> None:
        response = await client.get(f"{API}/models/{costed_model.id}")
        assert response.status_code == 200, response.text

        labor_cost = Decimal(str(response.json()["cost_breakdown"]["labor_cost"]))
        assert labor_cost == (LABOR_HOURS * DISTINCTIVE_RATE).quantize(Decimal("0.001")), (
            f"labor cost came back as {labor_cost}; at {LABOR_HOURS} h the "
            f"configured {DISTINCTIVE_RATE}/h gives "
            f"{LABOR_HOURS * DISTINCTIVE_RATE}"
        )
        assert labor_cost != (LABOR_HOURS * SUPERSEDED_HARDCODED_RATE).quantize(Decimal("0.001")), (
            "the hardcoded 10.00/h is still in use"
        )

    async def test_model_list_total_cost_uses_the_configured_rate(
        self, client: AsyncClient, costed_model: Model
    ) -> None:
        response = await client.get(f"{API}/models", params={"limit": 200})
        assert response.status_code == 200, response.text

        rows = [row for row in response.json()["models"] if row["sku"] == costed_model.sku]
        assert rows, f"{costed_model.sku} is missing from the model list"

        total = Decimal(str(rows[0]["total_cost"]))
        expected_material = Decimal("142") * Decimal("0.0310")
        expected_labor = LABOR_HOURS * DISTINCTIVE_RATE
        assert total == (expected_material + expected_labor).quantize(Decimal("0.001")), (
            f"model list reported {total}; expected material {expected_material} "
            f"plus labor {expected_labor}"
        )


class TestTheRateReachesTheProductEndpoints:
    async def test_product_detail_assembly_cost_uses_the_configured_rate(
        self, client: AsyncClient, costed_product: Product
    ) -> None:
        response = await client.get(f"{API}/products/{costed_product.id}")
        assert response.status_code == 200, response.text

        assembly = Decimal(str(response.json()["cost_breakdown"]["assembly_cost"]))
        expected = (ASSEMBLY_MINUTES / Decimal("60") * DISTINCTIVE_RATE).quantize(Decimal("0.01"))
        assert assembly == expected, (
            f"assembly cost came back as {assembly}; {ASSEMBLY_MINUTES} min at "
            f"{DISTINCTIVE_RATE}/h is {expected}"
        )

    async def test_product_detail_models_cost_uses_the_configured_rate(
        self, client: AsyncClient, costed_product: Product
    ) -> None:
        """The rate must reach the nested model cost, not only assembly.

        `calculate_product_cost` used to pass its rate to assembly alone while
        every nested model fell back to the engine default -- one call, two
        different labor rates in the same figure.
        """
        response = await client.get(f"{API}/products/{costed_product.id}")
        assert response.status_code == 200, response.text

        models_cost = Decimal(str(response.json()["cost_breakdown"]["models_cost"]))
        expected = (Decimal("142") * Decimal("0.0310") + LABOR_HOURS * DISTINCTIVE_RATE).quantize(
            Decimal("0.01")
        )
        assert models_cost == expected, (
            f"models cost came back as {models_cost}; expected {expected}. A "
            f"figure built with two different labor rates is the defect this "
            f"test exists for."
        )

    async def test_product_list_make_cost_uses_the_configured_rate(
        self, client: AsyncClient, costed_product: Product
    ) -> None:
        response = await client.get(f"{API}/products", params={"limit": 200})
        assert response.status_code == 200, response.text

        rows = [row for row in response.json()["products"] if row["sku"] == costed_product.sku]
        assert rows, f"{costed_product.sku} is missing from the product list"

        total = Decimal(str(rows[0]["total_make_cost"]))
        expected = (
            Decimal("142") * Decimal("0.0310")
            + LABOR_HOURS * DISTINCTIVE_RATE
            + ASSEMBLY_MINUTES / Decimal("60") * DISTINCTIVE_RATE
        ).quantize(Decimal("0.01"))
        assert total == expected, f"product list reported {total}, expected {expected}"

    async def test_the_nested_model_cost_on_the_product_matches(
        self, client: AsyncClient, costed_product: Product
    ) -> None:
        response = await client.get(f"{API}/products/{costed_product.id}")
        assert response.status_code == 200, response.text

        models = response.json()["models"]
        assert models, "the product reported no models"
        model_cost = Decimal(str(models[0]["model_cost"]))
        expected = (Decimal("142") * Decimal("0.0310") + LABOR_HOURS * DISTINCTIVE_RATE).quantize(
            Decimal("0.001")
        )
        assert model_cost == expected, (
            f"the model cost shown inside the product is {model_cost}, not {expected}"
        )


# ---------------------------------------------------------------------------
# Every call site, including those no response reaches
# ---------------------------------------------------------------------------

BACKEND_ROOT = Path(__file__).resolve().parents[2]

#: Modules that call the costing engine on behalf of a request.
CALL_SITE_MODULES = [
    BACKEND_ROOT / "app" / "api" / "v1" / "products.py",
    BACKEND_ROOT / "app" / "api" / "v1" / "models.py",
]

#: The engine entry points that cost labor and therefore need a rate.
RATE_BEARING_METHODS = {"calculate_product_cost", "calculate_model_cost"}

#: Argument names that supply the rate. Positional is not accepted: these are
#: keyword-only in spirit and a bare positional is how the bug got in.
#:
#: `policy` is accepted from Tier 1 on, where a call site hands the engine a
#: resolved `CostPolicy` instead of a loose rate. That is a stronger guarantee
#: rather than a weaker one -- the snapshot carries both labor rates, the
#: machine rate and the overhead method together, so a figure cannot be built
#: from one tenant's rate and another's overhead method. Whether the policy
#: holds the *configured* rate is what the HTTP cases above check; this scan
#: only proves no call site leaves the engine to invent one.
RATE_ARGUMENTS = {"labor_rate", "tenant_default_labor_rate", "policy"}


def _costing_calls(path: Path) -> list[tuple[int, str, set[str]]]:
    """Every `CostingService.<method>(...)` call in a module, with its keywords."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str, set[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in RATE_BEARING_METHODS:
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "CostingService"):
            continue
        keywords = {kw.arg for kw in node.keywords if kw.arg}
        found.append((node.lineno, func.attr, keywords))
    return found


@pytest.mark.parametrize("path", CALL_SITE_MODULES, ids=[p.name for p in CALL_SITE_MODULES])
def test_every_costing_call_site_passes_a_labor_rate(path: Path) -> None:
    """No request may cost labor at a rate the operator did not choose."""
    calls = _costing_calls(path)
    assert calls, f"no CostingService calls found in {path.name}; this scan is proving nothing"

    missing = [
        f"{path.name}:{lineno} {method}() passes no rate"
        for lineno, method, keywords in calls
        if not (keywords & RATE_ARGUMENTS)
    ]
    assert not missing, (
        "these call sites cost labor at the engine's default rather than the "
        "tenant's configured rate (Constitution IV):\n  " + "\n  ".join(missing)
    )


def test_the_engine_propagates_the_rate_into_nested_model_costs() -> None:
    """A product cost must not mix two labor rates in one figure."""
    path = BACKEND_ROOT / "app" / "services" / "costing.py"
    missing = [
        f"costing.py:{lineno} {method}() passes neither a rate nor a policy"
        for lineno, method, keywords in _costing_calls(path)
        if not (keywords & RATE_ARGUMENTS)
    ]
    assert not missing, (
        "the engine calls itself without forwarding the rate, so a nested model "
        "falls back to the default while assembly uses the tenant's rate:\n  "
        + "\n  ".join(missing)
    )


def test_the_engine_no_longer_offers_a_silent_hardcoded_rate() -> None:
    """A default that shadows a configured value is a defect, not a fallback."""
    from app.services import costing

    default = getattr(costing, "DEFAULT_LABOR_RATE", None)
    assert default != SUPERSEDED_HARDCODED_RATE, (
        "DEFAULT_LABOR_RATE is back to 10.00; if a caller forgets the rate, the "
        "operator's figure is silently replaced by one nobody chose"
    )
