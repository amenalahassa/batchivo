#!/usr/bin/env python3
"""Seed the dedicated tenant the pricing end-to-end suite runs against (T266).

Constitution II: the browser suite never touches the production account. It
runs against this tenant, on a database CI creates and throws away, or on a
local scratch database.

What it seeds is the smallest catalogue every pricing journey needs:

* an owner and a viewer, so the suite can check a viewer sees disabled
  controls (FR-007a);
* a decided pricing policy;
* a printer with a machine cost policy;
* a spool bought on a purchase, a model costed from it, and a product built
  from the model, with a weight and a postage profile so a parcel is priced;
* a channel with fee rules and a price, so the margin, solver and ladder have
  something to answer;
* a held estimate proposal, so accepting and rejecting can be exercised.

Idempotent: a second run finds the tenant and stops.

Run with: ``DATABASE_URL=<scratch db> poetry run python scripts/seed_e2e.py``

The credentials below are test values for this tenant only (read by
``frontend/e2e/config.ts``); they are not anyone's real password.
"""

import asyncio
import logging
import sys
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from app.auth.password import get_password_hash
from app.core import clock
from app.database import async_session_maker
from app.models.fee_rule import FeeRule
from app.models.filament_purchase import FilamentPurchase
from app.models.filament_type import FilamentType
from app.models.material import MaterialType
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.printer import Printer
from app.models.product import Product
from app.models.product_model import ProductModel
from app.models.product_pricing import ProductPricing
from app.models.sales_channel import SalesChannel
from app.models.shipping_profile import ShippingProfile
from app.models.spool import Spool
from app.models.tenant import Tenant
from app.models.user import User, UserRole, UserTenant
from app.services.pricing_policy import write_policy
from app.services.variance_service import Outcome, consider_outcomes

logger = logging.getLogger(__name__)

TENANT_SLUG = "e2e-pricing"
OWNER_EMAIL = "e2e-owner@example.com"
VIEWER_EMAIL = "e2e-viewer@example.com"
PASSWORD = "E2e-Pricing-Only-1"

MODEL_SKU = "E2E-DRAGON"
SECOND_MODEL_SKU = "E2E-WYVERN"
PRODUCT_SKU = "E2E-DRAGON-P"
CHANNEL_NAME = "E2E Marketplace"
APPLIES_FROM = date(2020, 1, 1)


async def _user(db, tenant: Tenant, email: str, role: UserRole) -> User:
    user = User(
        id=uuid4(),
        email=email,
        full_name=f"E2E {role.value}",
        hashed_password=get_password_hash(PASSWORD),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, role=role))
    return user


async def _material_type(db) -> MaterialType:
    found = (
        await db.execute(select(MaterialType).where(MaterialType.code == "PLA"))
    ).scalar_one_or_none()
    if found is not None:
        return found
    material = MaterialType(id=uuid4(), code="PLA", name="PLA (Polylactic Acid)")
    db.add(material)
    await db.flush()
    return material


async def seed() -> None:
    async with async_session_maker() as db:
        existing = (
            await db.execute(select(Tenant).where(Tenant.slug == TENANT_SLUG))
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(f"Tenant {TENANT_SLUG} already seeded; nothing to do")
            return

        tenant = Tenant(
            id=uuid4(),
            name="E2E Pricing",
            slug=TENANT_SLUG,
            currency_code="GBP",
            settings={"currency": "GBP"},
        )
        db.add(tenant)
        await db.flush()

        owner = await _user(db, tenant, OWNER_EMAIL, UserRole.OWNER)
        await _user(db, tenant, VIEWER_EMAIL, UserRole.VIEWER)

        await write_policy(
            db,
            tenant,
            {
                "print_labor_rate": Decimal("18.00"),
                "finishing_labor_rate": Decimal("18.00"),
                "default_machine_rate_per_hour": Decimal("0.40"),
                "overhead_percentage": Decimal("10"),
            },
            user=owner,
            role=UserRole.OWNER.value,
            effective_from=APPLIES_FROM,
        )

        printer = Printer(
            id=uuid4(),
            tenant_id=tenant.id,
            name="E2E Printer",
            manufacturer="Bambu Lab",
            model="P1S",
            purchase_price=Decimal("700.00"),
            expected_lifetime_hours=5000,
            maintenance_reserve_total=Decimal("150.00"),
            measured_watts=Decimal("110"),
            is_active=True,
        )
        db.add(printer)

        material = await _material_type(db)
        filament = FilamentType(
            id=uuid4(),
            tenant_id=tenant.id,
            material_type_id=material.id,
            brand="E2E Brand",
            color="Green",
            diameter=1.75,
            has_sample=False,
            translucent=False,
            glow=False,
        )
        db.add(filament)
        await db.flush()

        purchase = FilamentPurchase(
            id=uuid4(),
            tenant_id=tenant.id,
            supplier="E2E Supplies",
            purchase_date=APPLIES_FROM,
            inbound_shipping_cost=Decimal("4.00"),
            tax_amount=Decimal("0"),
        )
        db.add(purchase)
        await db.flush()

        spool = Spool(
            id=uuid4(),
            tenant_id=tenant.id,
            filament_type_id=filament.id,
            filament_purchase_id=purchase.id,
            spool_id="E2E-SPOOL-1",
            initial_weight=1000.0,
            current_weight=1000.0,
            purchase_price=Decimal("20.00"),
            is_active=True,
            is_labeled=False,
        )
        db.add(spool)

        model = Model(
            id=uuid4(),
            tenant_id=tenant.id,
            sku=MODEL_SKU,
            name="E2E Dragon",
            print_time_minutes=240,
            prints_per_plate=1,
            labor_hours=Decimal("0.25"),
            planned_printer_id=printer.id,
            is_active=True,
        )
        db.add(model)
        await db.flush()
        db.add(
            ModelMaterial(
                id=uuid4(),
                model_id=model.id,
                spool_id=spool.id,
                weight_grams=Decimal("120"),
            )
        )

        product = Product(
            id=uuid4(),
            tenant_id=tenant.id,
            sku=PRODUCT_SKU,
            name="E2E Dragon Figure",
            weight_grams=180,
            units_in_stock=0,
            is_active=True,
        )
        db.add(product)
        await db.flush()
        db.add(ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1))

        db.add(
            ShippingProfile(
                id=uuid4(),
                tenant_id=tenant.id,
                name="Small parcel",
                destination_zone="domestic",
                weight_bracket_min_grams=Decimal("0"),
                weight_bracket_max_grams=Decimal("2000"),
                postage_cost=Decimal("3.40"),
                effective_from=APPLIES_FROM,
            )
        )

        channel = SalesChannel(
            id=uuid4(),
            tenant_id=tenant.id,
            name=CHANNEL_NAME,
            platform_type="etsy",
            monthly_cost=Decimal("0"),
            tax_remitter="marketplace",
            expected_discount_pct=Decimal("0"),
            expected_refund_pct=Decimal("2"),
            currency_code="GBP",
            offsite_ads_opt_in=False,
            is_active=True,
        )
        db.add(channel)
        await db.flush()
        for name, basis, rate, fixed, order in (
            ("transaction", "item_plus_shipping", Decimal("6.5"), Decimal("0.00"), 10),
            ("payment_processing", "order_total", Decimal("4.0"), Decimal("0.20"), 20),
            ("listing", "per_listing", Decimal("0"), Decimal("0.16"), 30),
        ):
            db.add(
                FeeRule(
                    id=uuid4(),
                    tenant_id=tenant.id,
                    sales_channel_id=channel.id,
                    name=name,
                    basis=basis,
                    rate_pct=rate,
                    fixed_amount=fixed,
                    sort_order=order,
                    applies_from=APPLIES_FROM,
                )
            )
        db.add(
            ProductPricing(
                id=uuid4(),
                product_id=product.id,
                sales_channel_id=channel.id,
                list_price=Decimal("34.99"),
                is_active=True,
                valid_from=APPLIES_FROM,
            )
        )
        await db.flush()

        # Two held proposals -- prints that took far longer than estimated -- so
        # the suite can accept one and reject the other. The second item exists
        # only to carry the second proposal.
        second = Model(
            id=uuid4(),
            tenant_id=tenant.id,
            sku=SECOND_MODEL_SKU,
            name="E2E Wyvern",
            print_time_minutes=100,
            prints_per_plate=1,
            is_active=True,
        )
        db.add(second)
        await db.flush()
        today = clock.today()
        for subject, values, prefix in (
            (model, ("420", "430", "440"), "e2e-dragon"),
            (second, ("300", "310", "320"), "e2e-wyvern"),
        ):
            await consider_outcomes(
                db,
                tenant,
                subject,
                entity_type="model",
                field_name="print_time_minutes",
                outcomes=[
                    Outcome(
                        run_id=f"{prefix}-run-{i}",
                        value=Decimal(v),
                        observed_on=today - timedelta(days=i),
                    )
                    for i, v in enumerate(values)
                ],
                min_outcomes=3,
                divergence_threshold_pct=Decimal("25"),
            )

        await db.commit()
        logger.info(f"Seeded tenant {TENANT_SLUG} for the end-to-end suite")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "win32":
        # psycopg's async mode cannot run on the Proactor loop Windows defaults to.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(seed())
