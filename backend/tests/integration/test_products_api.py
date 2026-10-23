"""Integration tests for products API endpoints."""

from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.product import Product
from app.models.product_model import ProductModel


class TestProductsEndpoints:
    """Test products API endpoints."""

    @pytest.mark.asyncio
    async def test_create_product(self, client: AsyncClient, auth_headers: dict):
        """Test product creation."""
        response = await client.post(
            "/api/v1/products",
            headers=auth_headers,
            json={
                "sku": f"TEST-{uuid4().hex[:8].upper()}",
                "name": "Test Product",
                "description": "A test product for integration tests",
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["name"] == "Test Product"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_list_products(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ):
        """Test product listing."""
        response = await client.get("/api/v1/products", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        # Response is paginated with "products" key
        assert isinstance(data, dict)
        assert "products" in data
        products = data["products"]

        assert isinstance(products, list)
        assert len(products) >= 1

    @pytest.mark.asyncio
    async def test_get_product_by_id(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ):
        """Test retrieving a specific product."""
        response = await client.get(f"/api/v1/products/{test_product.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_product.id)
        assert data["name"] == test_product.name

    @pytest.mark.asyncio
    async def test_update_product(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ):
        """Test product update."""
        response = await client.put(
            f"/api/v1/products/{test_product.id}",
            headers=auth_headers,
            json={
                "name": "Updated Product Name",
                "description": "Updated description",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Product Name"

    @pytest.mark.asyncio
    async def test_delete_product(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ):
        """Test product deletion."""
        response = await client.delete(f"/api/v1/products/{test_product.id}", headers=auth_headers)
        assert response.status_code in [200, 204]

        # Verify product is deleted
        response = await client.get(f"/api/v1/products/{test_product.id}", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_product_not_found(self, client: AsyncClient, auth_headers: dict):
        """Test accessing non-existent product returns 404."""
        fake_id = uuid4()
        response = await client.get(f"/api/v1/products/{fake_id}", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_product_duplicate_sku(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ):
        """Test creating product with duplicate SKU returns error."""
        response = await client.post(
            "/api/v1/products",
            headers=auth_headers,
            json={
                "sku": test_product.sku,  # Duplicate
                "name": "Another Product",
                "description": "This should fail",
            },
        )
        assert response.status_code in [400, 409]


class TestProductTenantIsolation:
    """Test multi-tenant isolation for products."""

    @pytest.mark.asyncio
    async def test_cannot_access_other_tenant_product(
        self, client: AsyncClient, auth_headers: dict, db_session
    ):
        """Test products from other tenants are not visible."""
        from app.models.tenant import Tenant
        from app.models.product import Product

        # Create a different tenant
        other_tenant = Tenant(id=uuid4(), name="Other Tenant", slug="other-tenant", settings={})
        db_session.add(other_tenant)
        await db_session.flush()

        # Create a product for the other tenant
        other_product = Product(
            id=uuid4(),
            tenant_id=other_tenant.id,
            sku="OTHER-001",
            name="Other Tenant Product",
            description="Should not be visible",
        )
        db_session.add(other_product)
        await db_session.commit()

        # Try to access other tenant's product
        response = await client.get(f"/api/v1/products/{other_product.id}", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_only_shows_own_tenant_products(
        self, client: AsyncClient, auth_headers: dict, test_product: Product, db_session
    ):
        """Test product list only returns products from current tenant."""
        from app.models.tenant import Tenant
        from app.models.product import Product

        # Create another tenant with products
        other_tenant = Tenant(id=uuid4(), name="Other Tenant", slug="other-tenant-2", settings={})
        db_session.add(other_tenant)
        await db_session.flush()

        other_product = Product(
            id=uuid4(),
            tenant_id=other_tenant.id,
            sku="OTHER-002",
            name="Other Product",
            description="Should not appear in list",
        )
        db_session.add(other_product)
        await db_session.commit()

        # Get product list
        response = await client.get("/api/v1/products", headers=auth_headers)
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, dict)
        assert "products" in data
        products = data["products"]

        # Verify other tenant's product is not in list
        product_ids = [p["id"] for p in products]
        assert str(other_product.id) not in product_ids


class TestProductShopFields:
    """Test shop-related fields (is_featured, shop_description, feature_title, backstory)."""

    @pytest.mark.asyncio
    async def test_update_shop_fields(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ):
        """Test updating shop display fields."""
        response = await client.put(
            f"/api/v1/products/{test_product.id}",
            headers=auth_headers,
            json={
                "shop_description": "<p>A beautiful dragon with intricate scales</p>",
                "is_featured": True,
                "feature_title": "Rosyra the Rose Dragon",
                "backstory": "Born in the enchanted gardens of Mystmere...",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["shop_description"] == "<p>A beautiful dragon with intricate scales</p>"
        assert data["is_featured"] is True
        assert data["feature_title"] == "Rosyra the Rose Dragon"
        assert data["backstory"] == "Born in the enchanted gardens of Mystmere..."

    @pytest.mark.asyncio
    async def test_shop_fields_persist_after_fetch(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ):
        """Test that shop fields persist and are returned when fetching product."""
        # First update with shop fields
        update_response = await client.put(
            f"/api/v1/products/{test_product.id}",
            headers=auth_headers,
            json={
                "shop_description": "Shop description test",
                "is_featured": True,
                "feature_title": "Featured Title",
                "backstory": "Test backstory content",
            },
        )
        assert update_response.status_code == 200

        # Fetch the product and verify fields are returned
        get_response = await client.get(f"/api/v1/products/{test_product.id}", headers=auth_headers)
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["shop_description"] == "Shop description test"
        assert data["is_featured"] is True
        assert data["feature_title"] == "Featured Title"
        assert data["backstory"] == "Test backstory content"

    @pytest.mark.asyncio
    async def test_shop_visible_toggle(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ):
        """Test toggling shop visibility."""
        # Enable shop visibility
        response = await client.put(
            f"/api/v1/products/{test_product.id}",
            headers=auth_headers,
            json={"shop_visible": True},
        )
        assert response.status_code == 200
        assert response.json()["shop_visible"] is True

        # Disable shop visibility
        response = await client.put(
            f"/api/v1/products/{test_product.id}",
            headers=auth_headers,
            json={"shop_visible": False},
        )
        assert response.status_code == 200
        assert response.json()["shop_visible"] is False

    @pytest.mark.asyncio
    async def test_create_product_with_shop_fields(self, client: AsyncClient, auth_headers: dict):
        """Test creating a product with shop fields."""
        response = await client.post(
            "/api/v1/products",
            headers=auth_headers,
            json={
                "sku": f"SHOP-{uuid4().hex[:8].upper()}",
                "name": "Featured Dragon",
                "description": "Internal description",
                "shop_description": "Beautiful featured dragon for sale",
                "is_featured": True,
                "feature_title": "Dragon of the Month",
                "backstory": "A legendary dragon...",
                "shop_visible": True,
            },
        )
        assert response.status_code in [200, 201]
        data = response.json()
        assert data["shop_description"] == "Beautiful featured dragon for sale"
        assert data["is_featured"] is True
        assert data["feature_title"] == "Dragon of the Month"
        assert data["backstory"] == "A legendary dragon..."
        assert data["shop_visible"] is True


class TestProductCostCalculation:
    """`GET /products/{id}/cost`, the endpoint every costed screen reads.

    Both tests in this class used to skip themselves (tasks T187, T188).

    The first skipped on a 404 or 501, and that endpoint has existed since
    Tier 0 at `app/api/v1/products.py:603` -- so the branch was dead code that
    would have converted the endpoint's *removal* into a skip rather than a
    failure. The second had no body at all, only
    `pytest.skip("implement when models exist")`, and `Model`, `ProductModel`
    and `Product.product_models` are the foundation this whole feature costs
    from. A permanent skip reads in every test report as an uncovered
    requirement (Constitution II).

    SC-008 (the three screens agreeing on one cost) and US1/AC2 are covered in
    depth by `tests/api/test_cost_consistency.py` and
    `tests/integration/test_cost_graph_coherence.py`. What these two add is
    the HTTP surface: that the route answers, and that a product holding a
    model is costed through it from that model's own bill of materials.
    """

    @pytest.mark.asyncio
    async def test_product_cost_calculation(
        self, client: AsyncClient, auth_headers: dict, test_product: Product
    ):
        """The endpoint answers with a breakdown, not a bare figure."""
        response = await client.get(
            f"/api/v1/products/{test_product.id}/cost", headers=auth_headers
        )

        assert response.status_code == 200, response.text
        data = response.json()

        # The shape FR-019 and FR-001 require: a total, the lines behind it,
        # how much of it is evidence, and what was missing.
        assert "total_make_cost" in data
        assert "lines" in data
        assert "observed_share" in data
        assert "incomplete_reasons" in data

        # Money crosses this API as a decimal string, so a reader can hold it
        # exactly (FR-047). `test_product` has nothing beneath it, which is a
        # complete answer of zero rather than a gap -- a product with no bill
        # of materials costs nothing to make, and the engine says so without
        # inventing a reason.
        assert isinstance(data["total_make_cost"], str)
        assert Decimal(str(data["total_make_cost"])) == Decimal("0")
        assert data["incomplete_reasons"] == []

    @pytest.mark.asyncio
    async def test_product_with_models_shows_cost(
        self, client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_spool
    ):
        """A product holding a model is costed from that model's own BOM.

        40 g at £0.025/g is £1.00 of material, which must appear on the
        `material` line and in the total. Exact equality, not a tolerance: the
        engine is decimal end to end and the figure crosses the wire as a
        decimal string (Constitution IV).
        """
        model = Model(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sku=f"COSTED-M-{uuid4().hex[:8].upper()}",
            name="A model with a bill of materials",
            is_active=True,
        )
        db_session.add(model)
        await db_session.flush()

        db_session.add(
            ModelMaterial(
                id=uuid4(),
                model_id=model.id,
                spool_id=test_spool.id,
                weight_grams=Decimal("40"),
                cost_per_gram=Decimal("0.025"),
            )
        )

        product = Product(
            id=uuid4(),
            tenant_id=test_tenant.id,
            sku=f"COSTED-P-{uuid4().hex[:8].upper()}",
            name="A product holding that model",
            is_active=True,
        )
        db_session.add(product)
        await db_session.flush()

        db_session.add(
            ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1)
        )
        await db_session.commit()

        response = await client.get(f"/api/v1/products/{product.id}/cost", headers=auth_headers)

        assert response.status_code == 200, response.text
        data = response.json()

        lines = {line["key"]: Decimal(str(line["amount"])) for line in data["lines"]}
        assert "material" in lines, f"no material line in {sorted(lines)}"
        assert lines["material"] == Decimal("1.00"), (
            f"40 g at 0.025 is 1.00, not {lines['material']}"
        )
        assert Decimal(str(data["total_make_cost"])) >= Decimal("1.00"), (
            "the total must at least contain the material it is made of"
        )

        # Two quantities of the same model is twice the material: the quantity
        # on `ProductModel` is what makes this a product rather than a model.
        await db_session.execute(
            update(ProductModel).where(ProductModel.product_id == product.id).values(quantity=2)
        )
        await db_session.commit()

        doubled = await client.get(f"/api/v1/products/{product.id}/cost", headers=auth_headers)
        assert doubled.status_code == 200, doubled.text
        doubled_lines = {
            line["key"]: Decimal(str(line["amount"])) for line in doubled.json()["lines"]
        }
        assert doubled_lines["material"] == Decimal("2.00"), (
            f"two of the model is 2.00 of material, not {doubled_lines['material']}"
        )


class TestProductListDetailConsistency:
    """Regression tests: list endpoint must return same field values as detail endpoint."""

    @pytest.mark.asyncio
    async def test_list_and_detail_fields_match(self, client: AsyncClient, auth_headers: dict):
        """list and detail endpoints must return the same field values for a product."""
        sku = f"CONSIST-{uuid4().hex[:8].upper()}"
        create_resp = await client.post(
            "/api/v1/products",
            headers=auth_headers,
            json={
                "sku": sku,
                "name": "Consistency Test Dragon",
                "print_to_order": True,
                "free_shipping": True,
                "is_featured": True,
                "is_dragon": True,
                "seo_slug": "consistency-test-dragon",
                "seo_title": "Consistency Test",
                "tags": ["test", "dragon"],
            },
        )
        assert create_resp.status_code in [200, 201]
        product_id = create_resp.json()["id"]

        detail_resp = await client.get(f"/api/v1/products/{product_id}", headers=auth_headers)
        assert detail_resp.status_code == 200
        detail = detail_resp.json()

        list_resp = await client.get(f"/api/v1/products?search={sku}", headers=auth_headers)
        assert list_resp.status_code == 200
        products = list_resp.json()["products"]
        assert len(products) == 1
        listed = products[0]

        fields = [
            "print_to_order",
            "free_shipping",
            "is_featured",
            "is_dragon",
            "seo_slug",
            "seo_title",
            "tags",
            "shop_visible",
        ]
        for field in fields:
            assert listed[field] == detail[field], (
                f"Field '{field}' differs: list={listed[field]!r}, detail={detail[field]!r}"
            )

        await client.delete(f"/api/v1/products/{product_id}", headers=auth_headers)
