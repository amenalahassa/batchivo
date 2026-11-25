"""Tests for analytics API endpoints."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.filament_type import FilamentType
from app.models.material import MaterialType
from app.models.model import Model
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.production_run import ProductionRun, ProductionRunItem, ProductionRunMaterial
from app.models.spool import Spool
from app.models.tenant import Tenant


# ============================================
# Fixtures
# ============================================


@pytest_asyncio.fixture
async def analytics_product(
    db_session: AsyncSession,
    test_tenant: Tenant,
    analytics_model: Model,
) -> Product:
    """A product actually made of `analytics_model`.

    The link was missing: this fixture created a bare `Product` with no
    `ProductModel` row, so nothing connected it to the runs the tests below
    assert on -- and they passed regardless, because the handler never looked
    at the product id. A product with no bill of materials cannot have a
    production history, so the fixture now states the one relationship the
    endpoint exists to follow.
    """
    product = Product(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Analytics Test Product",
        sku="ATP-001",
        description="Product for analytics testing",
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    db_session.add(
        ProductModel(id=uuid4(), product_id=product.id, model_id=analytics_model.id, quantity=1)
    )

    await db_session.commit()
    await db_session.refresh(product)
    return product


@pytest_asyncio.fixture
async def analytics_model(
    db_session: AsyncSession,
    test_tenant: Tenant,
) -> Model:
    """Create a test model for analytics."""
    model = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku="MDL-ANALYTICS-001",
        name="Analytics Test Model",
        print_time_minutes=120,
        is_active=True,
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)
    return model


@pytest_asyncio.fixture
async def analytics_spool(
    db_session: AsyncSession,
    test_tenant: Tenant,
    test_material_type: MaterialType,
) -> Spool:
    """Create a test spool for analytics."""
    ft = FilamentType(
        id=uuid4(),
        tenant_id=test_tenant.id,
        material_type_id=test_material_type.id,
        brand="TestBrand",
        color="Blue",
        color_hex="#0000FF",
        diameter=1.75,
        has_sample=False,
        translucent=False,
        glow=False,
    )
    db_session.add(ft)
    await db_session.flush()
    spool = Spool(
        id=uuid4(),
        tenant_id=test_tenant.id,
        filament_type_id=ft.id,
        spool_id="SPL-ANALYTICS-001",
        initial_weight=1000.0,
        current_weight=800.0,
        is_active=True,
    )
    db_session.add(spool)
    await db_session.commit()
    await db_session.refresh(spool)
    return spool


@pytest_asyncio.fixture
async def completed_production_run(
    db_session: AsyncSession,
    test_tenant: Tenant,
    analytics_model: Model,
    analytics_spool: Spool,
) -> ProductionRun:
    """Create a completed production run with materials and items."""
    run = ProductionRun(
        id=uuid4(),
        tenant_id=test_tenant.id,
        run_number="RUN-ANALYTICS-001",
        status="completed",
        started_at=datetime.now(timezone.utc) - timedelta(hours=4),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        total_plates=1,
        completed_plates=1,
    )
    db_session.add(run)
    await db_session.flush()

    # Add production run item
    item = ProductionRunItem(
        id=uuid4(),
        production_run_id=run.id,
        model_id=analytics_model.id,
        quantity=5,
        successful_quantity=4,
        failed_quantity=1,
    )
    db_session.add(item)

    # Add production run material
    material = ProductionRunMaterial(
        id=uuid4(),
        production_run_id=run.id,
        spool_id=analytics_spool.id,
        estimated_model_weight_grams=Decimal("50.0"),
        estimated_flushed_grams=Decimal("5.0"),
        estimated_tower_grams=Decimal("0.0"),
        actual_model_weight_grams=Decimal("60.0"),
        cost_per_gram=Decimal("0.025"),
    )
    db_session.add(material)

    await db_session.commit()
    await db_session.refresh(run)
    return run


@pytest_asyncio.fixture
async def production_run_in_progress(
    db_session: AsyncSession,
    test_tenant: Tenant,
    analytics_model: Model,
    analytics_spool: Spool,
) -> ProductionRun:
    """Create an in-progress production run."""
    run = ProductionRun(
        id=uuid4(),
        tenant_id=test_tenant.id,
        run_number="RUN-ANALYTICS-002",
        status="in_progress",
        started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        total_plates=1,
        completed_plates=0,
    )
    db_session.add(run)
    await db_session.flush()

    item = ProductionRunItem(
        id=uuid4(),
        production_run_id=run.id,
        model_id=analytics_model.id,
        quantity=3,
    )
    db_session.add(item)

    material = ProductionRunMaterial(
        id=uuid4(),
        production_run_id=run.id,
        spool_id=analytics_spool.id,
        estimated_model_weight_grams=Decimal("30.0"),
        estimated_flushed_grams=Decimal("3.0"),
        estimated_tower_grams=Decimal("0.0"),
        cost_per_gram=Decimal("0.025"),
    )
    db_session.add(material)

    await db_session.commit()
    await db_session.refresh(run)
    return run


# ============================================
# Test Classes
# ============================================


class TestVarianceReport:
    """Tests for variance report endpoint."""

    async def test_variance_report_empty(
        self,
        client: AsyncClient,
    ):
        """Test variance report with no data."""
        response = await client.get("/api/v1/analytics/variance-report")
        assert response.status_code == 200
        data = response.json()
        assert "by_product" in data
        assert "highest_variance_runs" in data
        assert "variance_trends" in data
        assert "summary" in data
        assert data["summary"]["total_runs_analyzed"] == 0

    async def test_variance_report_with_data(
        self,
        client: AsyncClient,
        completed_production_run: ProductionRun,
    ):
        """Test variance report with production data."""
        response = await client.get("/api/v1/analytics/variance-report")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        # Should have at least one run analyzed
        assert data["summary"]["total_runs_analyzed"] >= 1

    async def test_variance_report_custom_days(
        self,
        client: AsyncClient,
    ):
        """Test variance report with custom days parameter."""
        response = await client.get("/api/v1/analytics/variance-report?days=60")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data

    async def test_variance_report_with_threshold(
        self,
        client: AsyncClient,
        completed_production_run: ProductionRun,
    ):
        """Test variance report with variance threshold filter."""
        response = await client.get("/api/v1/analytics/variance-report?variance_threshold=5")
        assert response.status_code == 200
        data = response.json()
        # Only runs above threshold should be included
        for run in data["highest_variance_runs"]:
            assert abs(run["variance_percent"]) >= 5

    async def test_variance_report_with_product_filter(
        self,
        client: AsyncClient,
        analytics_product: Product,
    ):
        """Test variance report filtered by product."""
        response = await client.get(
            f"/api/v1/analytics/variance-report?product_id={analytics_product.id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert "by_product" in data

    async def test_variance_report_invalid_days(
        self,
        client: AsyncClient,
    ):
        """Test variance report with invalid days parameter."""
        response = await client.get("/api/v1/analytics/variance-report?days=0")
        assert response.status_code == 422

        response = await client.get("/api/v1/analytics/variance-report?days=500")
        assert response.status_code == 422

    async def test_variance_report_unauthenticated(
        self,
        unauthenticated_client: AsyncClient,
    ):
        """Test that unauthenticated requests are rejected."""
        response = await unauthenticated_client.get("/api/v1/analytics/variance-report")
        assert response.status_code == 401


class TestProductProductionHistory:
    """Tests for product production history endpoint."""

    async def test_production_history_product_not_found(
        self,
        client: AsyncClient,
    ):
        """Test production history for non-existent product."""
        fake_id = uuid4()
        response = await client.get(f"/api/v1/analytics/products/{fake_id}/production-history")
        assert response.status_code == 404

    async def test_production_history_empty(
        self,
        client: AsyncClient,
        analytics_product: Product,
    ):
        """Test production history with no runs."""
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["product_id"] == str(analytics_product.id)
        assert data["product_name"] == analytics_product.name
        assert data["total_runs"] == 0
        assert data["production_history"] == []

    async def test_production_history_with_runs(
        self,
        client: AsyncClient,
        analytics_product: Product,
        completed_production_run: ProductionRun,
    ):
        """Test production history with production runs."""
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["product_id"] == str(analytics_product.id)
        # "May or may not have runs depending on model linkage" is what this
        # asserted, which was true of a fixture whose product was linked to
        # nothing. It is linked now, so the run is reported.
        assert data["total_runs"] == 1
        assert [item["run_number"] for item in data["production_history"]] == ["RUN-ANALYTICS-001"]
        assert "overall_success_rate" in data

    async def test_production_history_custom_days(
        self,
        client: AsyncClient,
        analytics_product: Product,
    ):
        """Test production history with custom days parameter."""
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history?days=180"
        )
        assert response.status_code == 200

    async def test_production_history_with_status_filter(
        self,
        client: AsyncClient,
        analytics_product: Product,
    ):
        """Test production history with status filter."""
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history?status_filter=completed"
        )
        assert response.status_code == 200
        data = response.json()
        for item in data["production_history"]:
            assert item["status"] == "completed"

    async def test_production_history_pagination(
        self,
        client: AsyncClient,
        analytics_product: Product,
    ):
        """Test production history pagination."""
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history?skip=0&limit=10"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["production_history"]) <= 10

    async def test_production_history_unauthenticated(
        self,
        unauthenticated_client: AsyncClient,
    ):
        """Test that unauthenticated requests are rejected."""
        fake_id = uuid4()
        response = await unauthenticated_client.get(
            f"/api/v1/analytics/products/{fake_id}/production-history"
        )
        assert response.status_code == 401


class TestSpoolProductionUsage:
    """Tests for spool production usage endpoint."""

    async def test_spool_usage_not_found(
        self,
        client: AsyncClient,
    ):
        """Test spool usage for non-existent spool."""
        fake_id = uuid4()
        response = await client.get(f"/api/v1/analytics/spools/{fake_id}/production-usage")
        assert response.status_code == 404

    async def test_spool_usage_empty(
        self,
        client: AsyncClient,
        analytics_spool: Spool,
    ):
        """Test spool usage with no runs."""
        response = await client.get(
            f"/api/v1/analytics/spools/{analytics_spool.id}/production-usage"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["spool_id"] == str(analytics_spool.id)
        assert data["spool_code"] == analytics_spool.spool_id
        assert data["color"] == "Blue"  # analytics_spool filament_type color
        assert data["run_count"] == 0
        assert data["usage_history"] == []

    async def test_spool_usage_with_runs(
        self,
        client: AsyncClient,
        analytics_spool: Spool,
        completed_production_run: ProductionRun,
    ):
        """Test spool usage with production runs."""
        response = await client.get(
            f"/api/v1/analytics/spools/{analytics_spool.id}/production-usage"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["spool_id"] == str(analytics_spool.id)
        assert data["run_count"] >= 1
        assert len(data["usage_history"]) >= 1

        # Check usage item structure
        if data["usage_history"]:
            usage = data["usage_history"][0]
            assert "run_id" in usage
            assert "run_number" in usage
            assert "estimated_weight" in usage
            assert "actual_weight" in usage
            assert "variance_grams" in usage
            assert "variance_percent" in usage
            assert "products_printed" in usage

    async def test_spool_usage_custom_days(
        self,
        client: AsyncClient,
        analytics_spool: Spool,
    ):
        """Test spool usage with custom days parameter."""
        response = await client.get(
            f"/api/v1/analytics/spools/{analytics_spool.id}/production-usage?days=180"
        )
        assert response.status_code == 200

    async def test_spool_usage_pagination(
        self,
        client: AsyncClient,
        analytics_spool: Spool,
    ):
        """Test spool usage pagination."""
        response = await client.get(
            f"/api/v1/analytics/spools/{analytics_spool.id}/production-usage?skip=0&limit=10"
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["usage_history"]) <= 10

    async def test_spool_usage_unauthenticated(
        self,
        unauthenticated_client: AsyncClient,
        analytics_spool: Spool,
    ):
        """Test that unauthenticated requests are rejected."""
        response = await unauthenticated_client.get(
            f"/api/v1/analytics/spools/{analytics_spool.id}/production-usage"
        )
        assert response.status_code == 401


# ============================================
# One owner for a production cost, exactly (tasks T183, T185)
# ============================================


class TestProductionHistoryCostsComeFromTheService:
    """The production-history costs, and who computes them.

    This endpoint used to compute its own: it summed
    ``float(m.estimated_total_weight * m.cost_per_gram)`` and the actual beside
    it, took a percentage from the two and rounded between the steps. That was
    a second cost implementation, in a route handler, in binary floating point
    -- while ``ProductionRunDetail`` rendered the service's recorded actuals
    for the same run, so the two screens answered differently for one number
    (Constitution III and IV, SC-008, FR-040, FR-047, FR-048).
    """

    async def test_the_figures_are_decimal_strings_on_the_wire(
        self,
        client: AsyncClient,
        analytics_product: Product,
        completed_production_run: ProductionRun,
    ):
        """Money crosses this API as a decimal string, never a JSON number."""
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["production_history"], "the completed run was not reported"
        entry = next(
            item for item in data["production_history"] if item["run_number"] == "RUN-ANALYTICS-001"
        )

        for field in ("estimated_cost", "actual_cost", "variance_percent"):
            assert isinstance(entry[field], str), (
                f"{field} came back as {type(entry[field]).__name__}; a money "
                f"figure crosses the wire as a decimal string, because a JSON "
                f"number is a binary double by the time anything reads it "
                f"(FR-047)"
            )
        for field in ("avg_estimated_cost", "avg_actual_cost"):
            assert isinstance(data[field], str), f"{field} is not a decimal string"

        # A success rate is not money and stays a number, which is the half of
        # the money-name rule that keeps it from being switched off.
        assert isinstance(entry["success_rate"], (int, float))

    async def test_the_figures_match_the_authority(
        self,
        client: AsyncClient,
        analytics_product: Product,
        completed_production_run: ProductionRun,
    ):
        """Exactly what the material model and the service say, to the penny.

        55 g estimated and 60 g actual at £0.025/g: £1.375 against £1.500, a
        variance of 9.0909...%. Each is carried exact and quantized once, here
        at the edge -- so the estimate reads 1.38 rather than the 1.37 a
        rounding applied mid-calculation would give.
        """
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history"
        )
        assert response.status_code == 200
        entry = next(
            item
            for item in response.json()["production_history"]
            if item["run_number"] == "RUN-ANALYTICS-001"
        )

        assert Decimal(entry["estimated_cost"]) == Decimal("1.38")
        assert Decimal(entry["actual_cost"]) == Decimal("1.50")
        assert Decimal(entry["variance_percent"]) == Decimal("9.09")

    async def test_an_unrecorded_actual_is_absent_not_zero(
        self,
        client: AsyncClient,
        analytics_product: Product,
        production_run_in_progress: ProductionRun,
    ):
        """A run still printing has no actual cost, and says so (FR-019)."""
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history"
        )
        assert response.status_code == 200
        data = response.json()
        entry = next(
            item for item in data["production_history"] if item["run_number"] == "RUN-ANALYTICS-002"
        )

        assert entry["actual_cost"] is None, (
            "an in-progress run reported a cost; an unrecorded actual and a "
            "cost of nothing are different facts (FR-019)"
        )
        assert entry["variance_percent"] is None
        assert Decimal(entry["estimated_cost"]) == Decimal("0.82")
        # Nothing recorded anywhere, so the average has nothing to average.
        assert data["avg_actual_cost"] is None


class TestMaterialCostSummaryIsTheAuthority:
    """The service method the route now calls, exercised directly.

    A route test proves the wiring. These prove the arithmetic, including the
    two cases the old handler got wrong because it tested the figures for
    truthiness: a genuinely free run and a total loss.
    """

    @staticmethod
    def _material(**kwargs) -> ProductionRunMaterial:
        defaults = dict(
            id=uuid4(),
            estimated_model_weight_grams=Decimal("0"),
            estimated_flushed_grams=Decimal("0"),
            estimated_tower_grams=Decimal("0"),
            cost_per_gram=Decimal("0.025"),
        )
        defaults.update(kwargs)
        return ProductionRunMaterial(**defaults)

    @staticmethod
    def _run(status: str, materials: list[ProductionRunMaterial]) -> ProductionRun:
        run = ProductionRun(
            id=uuid4(),
            run_number="RUN-UNIT-001",
            status=status,
            started_at=datetime.now(timezone.utc),
        )
        run.materials = materials
        return run

    def test_it_sums_both_sides_exactly(self):
        """Two materials, two rates, and no rounding between the steps."""
        from app.services.production_run import ProductionRunService

        run = self._run(
            "completed",
            [
                self._material(
                    estimated_model_weight_grams=Decimal("50.0"),
                    estimated_flushed_grams=Decimal("5.0"),
                    actual_model_weight_grams=Decimal("60.0"),
                    cost_per_gram=Decimal("0.025"),
                ),
                self._material(
                    estimated_model_weight_grams=Decimal("10.0"),
                    actual_model_weight_grams=Decimal("9.0"),
                    cost_per_gram=Decimal("0.0333"),
                ),
            ],
        )
        costs = ProductionRunService.material_cost_summary(run)

        # 55 * 0.025 + 10 * 0.0333, and 60 * 0.025 + 9 * 0.0333, unrounded.
        assert costs.estimated == Decimal("1.7080")
        assert costs.actual == Decimal("1.7997")
        assert costs.variance_percent is not None
        # The percentage is carried at full precision, not rounded here.
        assert costs.variance_percent.quantize(Decimal("0.0001")) == Decimal("5.3689")

    def test_an_incomplete_run_has_no_actual(self):
        """Not zero, and so no variance either (FR-019)."""
        from app.services.production_run import ProductionRunService

        run = self._run(
            "in_progress",
            [self._material(estimated_model_weight_grams=Decimal("30.0"))],
        )
        costs = ProductionRunService.material_cost_summary(run)

        assert costs.estimated == Decimal("0.750")
        assert costs.actual is None
        assert costs.variance_percent is None

    def test_a_run_that_used_nothing_reports_zero_not_absent(self):
        """The case `if actual_cost` got wrong.

        A completed run whose actual filament cost is genuinely zero was
        reported as having no actual at all, because the old handler tested the
        figure for truthiness rather than for presence. Zero is a recorded
        fact; absent is not.
        """
        from app.services.production_run import ProductionRunService

        run = self._run(
            "completed",
            [
                self._material(
                    estimated_model_weight_grams=Decimal("30.0"),
                    actual_model_weight_grams=Decimal("0"),
                )
            ],
        )
        costs = ProductionRunService.material_cost_summary(run)

        assert costs.actual == Decimal("0.000")
        assert costs.actual is not None, "a free run is not an unrecorded one"
        # And its variance is -100%, which `if variance_percent` also dropped.
        assert costs.variance_percent == Decimal("-100")

    def test_a_zero_estimate_has_no_percentage(self):
        """There is no percentage of nothing, so it is absent rather than zero."""
        from app.services.production_run import ProductionRunService

        run = self._run(
            "completed",
            [self._material(actual_model_weight_grams=Decimal("12.0"))],
        )
        costs = ProductionRunService.material_cost_summary(run)

        assert costs.estimated == Decimal("0.000")
        assert costs.actual == Decimal("0.300")
        assert costs.variance_percent is None

    def test_the_estimated_cost_property_is_the_siblings_mirror(self):
        """`estimated_total_cost` and `total_cost` are one multiplication each."""
        material = self._material(
            estimated_model_weight_grams=Decimal("50.0"),
            estimated_flushed_grams=Decimal("5.0"),
            estimated_tower_grams=Decimal("2.5"),
            actual_model_weight_grams=Decimal("60.0"),
            cost_per_gram=Decimal("0.025"),
        )

        assert material.estimated_total_weight == Decimal("57.5")
        assert material.estimated_total_cost == Decimal("57.5") * Decimal("0.025")
        assert material.total_cost == material.actual_total_weight * Decimal("0.025")
        # Exact, so the two sides are comparable without a tolerance.
        assert material.estimated_total_cost == Decimal("1.4375")


# ============================================
# One product's history, not the workshop's
# ============================================


@pytest_asyncio.fixture
async def another_products_run(
    db_session: AsyncSession,
    test_tenant: Tenant,
    analytics_spool: Spool,
) -> dict:
    """A second product, its own model, and a completed run of it.

    Nothing here touches `analytics_product` or `analytics_model`: the two
    products share a tenant, a spool and a time window, and nothing else.
    """
    model = Model(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku="MDL-ANALYTICS-OTHER",
        name="Somebody Else's Model",
        print_time_minutes=90,
        is_active=True,
    )
    db_session.add(model)
    await db_session.flush()

    product = Product(
        id=uuid4(),
        tenant_id=test_tenant.id,
        name="Another Product Entirely",
        sku="ATP-OTHER",
        is_active=True,
    )
    db_session.add(product)
    await db_session.flush()

    db_session.add(ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1))

    run = ProductionRun(
        id=uuid4(),
        tenant_id=test_tenant.id,
        run_number="RUN-ANALYTICS-OTHER",
        status="completed",
        started_at=datetime.now(timezone.utc) - timedelta(hours=3),
        completed_at=datetime.now(timezone.utc) - timedelta(hours=2),
        total_plates=1,
        completed_plates=1,
    )
    db_session.add(run)
    await db_session.flush()

    db_session.add(
        ProductionRunItem(
            id=uuid4(),
            production_run_id=run.id,
            model_id=model.id,
            quantity=100,
            successful_quantity=100,
            failed_quantity=0,
        )
    )
    db_session.add(
        ProductionRunMaterial(
            id=uuid4(),
            production_run_id=run.id,
            spool_id=analytics_spool.id,
            estimated_model_weight_grams=Decimal("900.0"),
            estimated_flushed_grams=Decimal("0.0"),
            estimated_tower_grams=Decimal("0.0"),
            actual_model_weight_grams=Decimal("900.0"),
            cost_per_gram=Decimal("0.025"),
        )
    )

    await db_session.commit()
    return {"product": product, "model": model, "run": run}


class TestProductionHistoryIsScopedToTheProduct:
    """`GET /analytics/products/{id}/production-history` and its product id.

    The handler validated that the product existed and then never used it
    again. Its query joined `ProductionRunItem` to `Model` -- a condition every
    item satisfies, since every item has a model -- and filtered on nothing but
    the tenant and the window; `ProductModel`, the only link between a product
    and a run, was never joined. So every run in the workshop came back for
    every product, and the response's `total_runs`, `total_produced`,
    `overall_success_rate`, `avg_estimated_cost` and `avg_actual_cost` were all
    computed over them.

    The quantity loop had the same hole one level down: its comment said "Find
    items for this product's models" and it then added up every item in the
    run.

    Two products, each with its own model and its own completed run, in one
    tenant and one window, is the smallest arrangement that catches either.
    """

    async def test_only_this_products_runs_are_reported(
        self,
        client: AsyncClient,
        analytics_product: Product,
        completed_production_run: ProductionRun,
        another_products_run: dict,
    ):
        """The other product's run must not appear in this product's history."""
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history"
        )
        assert response.status_code == 200
        data = response.json()

        reported = [item["run_number"] for item in data["production_history"]]
        assert reported == ["RUN-ANALYTICS-001"], (
            f"this product's history reported {reported}; "
            "RUN-ANALYTICS-OTHER belongs to a different product"
        )
        assert data["total_runs"] == 1

    async def test_the_other_products_output_is_not_counted_as_this_ones(
        self,
        client: AsyncClient,
        analytics_product: Product,
        completed_production_run: ProductionRun,
        another_products_run: dict,
    ):
        """The totals are this product's: 4 made and 1 failed, not 104 and 1.

        `completed_production_run` planned 5, made 4, failed 1. The other
        product's run made 100. A success rate pooled across both reads 99%
        where this product's is 80%.
        """
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["total_produced"] == 4, (
            f"total_produced was {data['total_produced']}; 100 of them were somebody else's product"
        )
        assert data["total_failed"] == 1
        assert data["overall_success_rate"] == 80.0

        entry = data["production_history"][0]
        assert entry["quantity_planned"] == 5
        assert entry["quantity_successful"] == 4
        assert entry["quantity_failed"] == 1

    async def test_the_averages_do_not_include_the_other_products_costs(
        self,
        client: AsyncClient,
        analytics_product: Product,
        completed_production_run: ProductionRun,
        another_products_run: dict,
    ):
        """55 g at 0.025 is 1.375, which quantises to 1.38.

        The other run is 900 g at the same rate -- 22.50 -- so an average taken
        over both lands near 11.94 and nowhere near this product's own figure.
        """
        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history"
        )
        assert response.status_code == 200
        data = response.json()

        assert Decimal(data["avg_estimated_cost"]) == Decimal("1.38"), (
            f"avg_estimated_cost was {data['avg_estimated_cost']}; the other "
            "product's 900 g run was averaged in"
        )

    async def test_each_product_sees_its_own_run(
        self,
        client: AsyncClient,
        analytics_product: Product,
        completed_production_run: ProductionRun,
        another_products_run: dict,
    ):
        """The fix is a filter, not a smaller result set: both still answer."""
        other = another_products_run["product"]
        response = await client.get(f"/api/v1/analytics/products/{other.id}/production-history")
        assert response.status_code == 200
        data = response.json()

        assert [item["run_number"] for item in data["production_history"]] == [
            "RUN-ANALYTICS-OTHER"
        ]
        assert data["total_produced"] == 100

    async def test_a_run_holding_two_of_the_products_models_appears_once(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        analytics_product: Product,
        analytics_model: Model,
        completed_production_run: ProductionRun,
    ):
        """`.distinct()` earns its place: one run, two matching items, one row.

        A product is usually several models, and a run prints several of them
        at once, so the join multiplies rows. Both items' quantities count --
        9 planned, not 5.
        """
        second_model = Model(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sku="MDL-ANALYTICS-002",
            name="A second part of the same product",
            print_time_minutes=30,
            is_active=True,
        )
        db_session.add(second_model)
        await db_session.flush()

        db_session.add(
            ProductModel(
                id=uuid4(),
                product_id=analytics_product.id,
                model_id=second_model.id,
                quantity=1,
            )
        )
        db_session.add(
            ProductionRunItem(
                id=uuid4(),
                production_run_id=completed_production_run.id,
                model_id=second_model.id,
                quantity=4,
                successful_quantity=4,
                failed_quantity=0,
            )
        )
        await db_session.commit()

        response = await client.get(
            f"/api/v1/analytics/products/{analytics_product.id}/production-history"
        )
        assert response.status_code == 200
        data = response.json()

        assert data["total_runs"] == 1, "the run was reported once per matching item"
        entry = data["production_history"][0]
        assert entry["quantity_planned"] == 9
        assert entry["quantity_successful"] == 8

    async def test_a_product_made_of_nothing_has_no_history(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_tenant: Tenant,
        completed_production_run: ProductionRun,
    ):
        """No bill of materials, no runs -- rather than all of them.

        This is the case the defect made loudest: a product with no models at
        all was shown every run in the tenant.
        """
        bare = Product(
            id=uuid4(),
            tenant_id=test_tenant.id,
            name="A product made of nothing",
            sku="ATP-BARE",
            is_active=True,
        )
        db_session.add(bare)
        await db_session.commit()

        response = await client.get(f"/api/v1/analytics/products/{bare.id}/production-history")
        assert response.status_code == 200
        data = response.json()

        assert data["total_runs"] == 0
        assert data["production_history"] == []
        assert data["avg_actual_cost"] is None
