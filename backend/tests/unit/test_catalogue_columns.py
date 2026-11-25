"""The catalogue columns added by spec 006 and their constraints (data-model.md, T006)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.consumable import ConsumableType
from app.models.product import Product
from app.models.shipping_profile import ShippingProfile
from app.models.tenant import Tenant


async def _tenant(db) -> Tenant:
    tenant = Tenant(id=uuid4(), name="Other", slug=f"other-{uuid4().hex[:8]}", settings={})
    db.add(tenant)
    await db.commit()
    return tenant


def _consumable(tenant, key=None, **kw) -> ConsumableType:
    return ConsumableType(
        tenant_id=tenant.id,
        sku=f"PKG-{uuid4().hex[:8]}",
        name=kw.pop("name", f"Box {uuid4().hex[:4]}"),
        packaging_kind="box",
        catalogue_key=key,
        catalogue_version=1 if key else None,
        **kw,
    )


def _profile(tenant, **kw) -> ShippingProfile:
    base = dict(
        tenant_id=tenant.id,
        name="Small Packet",
        destination_zone="us",
        weight_bracket_min_grams=Decimal("0"),
        weight_bracket_max_grams=Decimal("100"),
        postage_cost=Decimal("9.11"),
        effective_from=date(2026, 1, 12),
    )
    base.update(kw)
    return ShippingProfile(**base)


class TestConsumableCatalogueKey:
    async def test_round_trips(self, db_session, test_tenant):
        row = _consumable(test_tenant, "box-cube-100")
        db_session.add(row)
        await db_session.commit()
        stored = (
            await db_session.execute(select(ConsumableType).where(ConsumableType.id == row.id))
        ).scalar_one()
        assert stored.catalogue_key == "box-cube-100"
        assert stored.catalogue_version == 1
        stored.catalogue_version = 2
        await db_session.commit()
        await db_session.refresh(stored)
        assert stored.catalogue_version == 2

    async def test_two_operator_rows_without_key_are_allowed(self, db_session, test_tenant):
        db_session.add_all([_consumable(test_tenant), _consumable(test_tenant)])
        await db_session.commit()

    async def test_duplicate_key_in_one_tenant_is_refused(self, db_session, test_tenant):
        db_session.add(_consumable(test_tenant, "box-cube-100"))
        await db_session.commit()
        db_session.add(_consumable(test_tenant, "box-cube-100"))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_same_key_in_two_tenants_is_allowed(self, db_session, test_tenant):
        other = await _tenant(db_session)
        db_session.add_all(
            [_consumable(test_tenant, "box-cube-100"), _consumable(other, "box-cube-100")]
        )
        await db_session.commit()


class TestShippingProfileCatalogueIdentity:
    async def test_seeded_row_round_trips(self, db_session, test_tenant):
        row = _profile(
            test_tenant,
            catalogue_carrier="canada_post",
            service="small_packet",
            tariff_version=date(2026, 1, 12),
            source="Canada Post guide",
        )
        db_session.add(row)
        await db_session.commit()
        await db_session.refresh(row)
        assert (row.catalogue_carrier, row.service, row.tariff_version) == (
            "canada_post",
            "small_packet",
            date(2026, 1, 12),
        )

    async def test_operator_row_may_name_a_service_only(self, db_session, test_tenant):
        db_session.add(_profile(test_tenant, service="my_courier"))
        await db_session.commit()

    @pytest.mark.parametrize(
        "missing", [{"service": None}, {"tariff_version": None}], ids=["no-service", "no-tariff"]
    )
    async def test_seeded_row_needs_service_and_tariff(self, db_session, test_tenant, missing):
        fields = dict(
            catalogue_carrier="canada_post",
            service="small_packet",
            tariff_version=date(2026, 1, 12),
        )
        fields.update(missing)
        db_session.add(_profile(test_tenant, **fields))
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()


class TestTenantCountry:
    @pytest.mark.parametrize("code", [None, "FR"])
    async def test_accepted(self, db_session, test_tenant, code):
        test_tenant.country_code = code
        await db_session.commit()
        await db_session.refresh(test_tenant)
        assert test_tenant.country_code == code

    @pytest.mark.parametrize("code", ["fr", "FRA", "F1"])
    async def test_refused(self, db_session, test_tenant, code):
        test_tenant.country_code = code
        # A CHECK violation, or a value too long for the column (FRA).
        with pytest.raises(DBAPIError):
            await db_session.commit()
        await db_session.rollback()


class TestProductPostageService:
    async def test_round_trips(self, db_session, test_tenant):
        product = Product(
            tenant_id=test_tenant.id,
            sku=f"P-{uuid4().hex[:6]}",
            name="Dragon",
            postage_service="canada_post:small_packet",
        )
        db_session.add(product)
        await db_session.commit()
        await db_session.refresh(product)
        assert product.postage_service == "canada_post:small_packet"
        product.postage_service = None
        await db_session.commit()
        await db_session.refresh(product)
        assert product.postage_service is None
