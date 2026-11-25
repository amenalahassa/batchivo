"""Smoke test for the packed-parcel postage delta report (T055)."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.product import Product
from app.models.shipping_profile import ShippingProfile
from scripts.postage_delta_report import COLUMNS, collect, render
from tests.utils.packaging import make_box

pytestmark = pytest.mark.asyncio


def _profile(tenant, name, cost, low, high) -> ShippingProfile:
    return ShippingProfile(
        tenant_id=tenant.id,
        name=name,
        destination_zone="domestic",
        weight_bracket_min_grams=Decimal(low),
        weight_bracket_max_grams=Decimal(high),
        postage_cost=Decimal(cost),
        effective_from=date(2020, 1, 1),
    )


async def test_reports_each_product_both_ways(db_session, test_tenant) -> None:
    box = await make_box(db_session, test_tenant, "Box M", (150, 100, 60), weight=40, wall=3)
    boxed = Product(
        id=uuid4(),
        tenant_id=test_tenant.id,
        sku="A-BOXED",
        name="Boxed",
        weight_grams=180,
        packaging_consumable_id=box.id,
        packaging_quantity=1,
    )
    bare = Product(id=uuid4(), tenant_id=test_tenant.id, sku="B-BARE", name="Bare", weight_grams=90)
    db_session.add_all(
        [
            boxed,
            bare,
            _profile(test_tenant, "Light", "3.00", "0", "200"),
            _profile(test_tenant, "Heavy", "4.50", "200", "500"),
        ]
    )
    await db_session.commit()

    rows = await collect(db_session, test_tenant.slug)
    by_sku = {row["sku"]: row for row in rows}

    assert by_sku["A-BOXED"]["weight_only"] == Decimal("3.00")
    assert by_sku["A-BOXED"]["packed"] == Decimal("4.50")
    assert by_sku["A-BOXED"]["difference"] == Decimal("1.50")
    assert by_sku["B-BARE"]["difference"] == Decimal("0")
    assert "no_packaging_recorded" in by_sku["B-BARE"]["note"]

    csv = render(rows)
    assert csv.splitlines()[0] == ",".join(COLUMNS)
    assert "A-BOXED,domestic,3.00,4.50,1.50," in csv
