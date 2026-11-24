"""Model and product creation services, shared by the routes and idea conversion (spec 007, R3).

The services flush and never commit, so a caller can roll the whole creation
back; their checks are the ones the routes always had.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model import Model
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.model import ModelCreate
from app.schemas.product import ProductComponentCreate, ProductCreate, ProductModelCreate
from app.services.model_creation import create_model
from app.services.product_creation import create_product, slugify
from tests.utils.ideas import idea_in


async def _count(db: AsyncSession, table) -> int:
    return await db.scalar(select(func.count()).select_from(table))


class TestCreateModel:
    async def test_creates_without_committing(
        self, db_session: AsyncSession, test_tenant: Tenant, test_user: User
    ):
        model = await create_model(
            db_session, test_tenant, test_user, ModelCreate(sku="M-1", name="Clip")
        )
        assert model.id is not None and model.source_idea_id is None
        await db_session.rollback()
        assert await _count(db_session, Model) == 0

    async def test_taken_sku(self, db_session: AsyncSession, test_tenant: Tenant, test_user: User):
        await create_model(db_session, test_tenant, test_user, ModelCreate(sku="M-1", name="a"))
        await db_session.commit()
        with pytest.raises(HTTPException) as refused:
            await create_model(db_session, test_tenant, test_user, ModelCreate(sku="M-1", name="b"))
        assert refused.value.status_code == 400

    async def test_source_idea_recorded(
        self, db_session: AsyncSession, test_tenant: Tenant, test_user: User
    ):
        idea = await idea_in(db_session, test_tenant)
        model = await create_model(
            db_session,
            test_tenant,
            test_user,
            ModelCreate(sku="M-2", name="From idea"),
            source_idea_id=idea.id,
        )
        assert model.source_idea_id == idea.id


class TestCreateProduct:
    async def test_bom_line_and_rollback(
        self, db_session: AsyncSession, test_tenant: Tenant, test_user: User
    ):
        model = await create_model(
            db_session, test_tenant, test_user, ModelCreate(sku="M-1", name="Clip")
        )
        product = await create_product(
            db_session,
            test_tenant,
            test_user,
            ProductCreate(
                sku="P-1",
                name="Sun Visor Clip!",
                models=[ProductModelCreate(model_id=model.id, quantity=1)],
            ),
        )
        assert product.seo_slug == "sun-visor-clip"
        assert await _count(db_session, ProductModel) == 1
        await db_session.rollback()
        assert await _count(db_session, Product) == 0
        assert await _count(db_session, ProductModel) == 0

    async def test_refusals(self, db_session: AsyncSession, test_tenant: Tenant, test_user: User):
        await create_product(db_session, test_tenant, test_user, ProductCreate(sku="P-1", name="a"))
        await db_session.commit()
        cases = [
            (ProductCreate(sku="P-1", name="dup"), 400),
            (
                ProductCreate(
                    sku="P-2",
                    name="b",
                    models=[ProductModelCreate(model_id=uuid.uuid4(), quantity=1)],
                ),
                404,
            ),
            (ProductCreate(sku="P-3", name="c", designer_id=uuid.uuid4()), 404),
            (
                ProductCreate(
                    sku="P-4",
                    name="d",
                    child_products=[
                        ProductComponentCreate(child_product_id=uuid.uuid4(), quantity=1)
                    ],
                ),
                404,
            ),
        ]
        for data, code in cases:
            # A savepoint per case: a full rollback would expire the tenant and user.
            savepoint = await db_session.begin_nested()
            with pytest.raises(HTTPException) as refused:
                await create_product(db_session, test_tenant, test_user, data)
            assert refused.value.status_code == code
            await savepoint.rollback()

    async def test_source_idea_recorded(
        self, db_session: AsyncSession, test_tenant: Tenant, test_user: User
    ):
        idea = await idea_in(db_session, test_tenant)
        product = await create_product(
            db_session,
            test_tenant,
            test_user,
            ProductCreate(sku="P-9", name="x"),
            source_idea_id=idea.id,
        )
        assert product.source_idea_id == idea.id


def test_slugify():
    assert slugify("  Sun Visor -- Clip!  ") == "sun-visor-clip"
