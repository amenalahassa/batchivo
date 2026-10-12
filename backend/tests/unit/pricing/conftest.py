"""Builders that turn the golden fixture's **inputs** into objects to cost.

`tests/fixtures/golden_case.py` holds inputs and no expected values, on purpose.
This module is the other half of that arrangement: it assembles those inputs
into the records the engine costs, so each test can recompute its own expected
figure from the same inputs rather than from a literal somebody pasted in.

Real ORM classes are used, unsaved. A transient SQLAlchemy instance is an
ordinary Python object, so the engine sees exactly the attributes it will see
in production -- including :meth:`Printer.machine_rate_components`, which a
hand-rolled stub would have had to reimplement and could therefore have got
wrong in the same direction as the code under test.

Column defaults are applied by the database at flush, not by the constructor,
so every field the engine reads is set explicitly here. A ``None`` that the
engine happens to treat as zero is not the same as a tested default.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.fee_rule import COUNT_BASES, FeeRule
from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.printer import Printer
from app.models.product import Product
from app.models.sales_channel import SalesChannel
from app.services.fee_engine import OrderContext
from app.services.pricing_policy import CostPolicy
from tests.fixtures import golden_case as golden

MINUTES_PER_HOUR = Decimal("60")


def golden_cost_per_gram() -> Decimal:
    """Landed cost per **usable** gram, from the fixture's own figures.

    FR-008d: the divisor is nominal weight less the unusable remainder, never
    the nominal weight. Unrounded -- rounding here would seed every figure
    below with an error.
    """
    usable = golden.SPOOL_NOMINAL_GRAMS - golden.SPOOL_UNUSABLE_REMAINDER_GRAMS
    return golden.SPOOL_LANDED_COST / usable


def golden_machine_rate_per_hour() -> Decimal:
    """Hourly machine rate, from the fixture (FR-010)."""
    lifetime = Decimal(golden.PRINTER_EXPECTED_LIFETIME_HOURS)
    depreciation = golden.PRINTER_PURCHASE_PRICE / lifetime
    maintenance = golden.PRINTER_MAINTENANCE_RESERVE_TOTAL / lifetime
    power = (golden.PRINTER_MEASURED_WATTS / Decimal("1000")) * golden.ELECTRICITY_RATE_PER_KWH
    return depreciation + maintenance + power


def golden_overhead_rate_per_machine_hour() -> Decimal:
    """Overhead absorbed per machine-hour, from the fixture (FR-014)."""
    return golden.MONTHLY_OVERHEAD_POOL / golden.EXPECTED_MONTHLY_MACHINE_HOURS


def make_printer(**overrides) -> Printer:
    """The golden case's machine, with a complete cost policy."""
    defaults = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Golden A1",
        purchase_price=golden.PRINTER_PURCHASE_PRICE,
        expected_lifetime_hours=golden.PRINTER_EXPECTED_LIFETIME_HOURS,
        maintenance_reserve_total=golden.PRINTER_MAINTENANCE_RESERVE_TOTAL,
        measured_watts=golden.PRINTER_MEASURED_WATTS,
        electricity_rate_per_kwh=golden.ELECTRICITY_RATE_PER_KWH,
    )
    defaults.update(overrides)
    printer = Printer(**defaults)
    printer.model_printer_configs = []
    return printer


def make_policy(**overrides) -> CostPolicy:
    """The golden case's operator policy, absorbing overhead per machine-hour."""
    defaults = dict(
        print_labor_rate=golden.LABOR_RATE_PER_HOUR,
        finishing_labor_rate=golden.LABOR_RATE_PER_HOUR,
        overhead_method="per_machine_hour",
        overhead_monthly_pool=golden.MONTHLY_OVERHEAD_POOL,
        expected_monthly_machine_hours=golden.EXPECTED_MONTHLY_MACHINE_HOURS,
        electricity_rate_per_kwh=golden.ELECTRICITY_RATE_PER_KWH,
    )
    defaults.update(overrides)
    return CostPolicy(**defaults)


def make_model(**overrides) -> Model:
    """The golden case's printed item.

    The 15 at-risk minutes are recorded as handling labor and the 5 packing
    minutes as packing labor, which is the split FR-015 turns on: the premium
    reaches the first and never the second.
    """
    cost_per_gram = overrides.pop("cost_per_gram", golden_cost_per_gram())
    part_grams = overrides.pop("part_grams", golden.PART_GRAMS)
    prints_per_plate = overrides.pop("prints_per_plate", golden.PRINTS_PER_PLATE)

    defaults = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        sku=f"GOLD-{uuid4().hex[:6]}",
        name="Golden case part",
        labor_hours=Decimal("0"),
        labor_rate_override=None,
        overhead_percentage=Decimal("0"),
        print_time_minutes=int(golden.PRINT_HOURS * MINUTES_PER_HOUR),
        prints_per_plate=prints_per_plate,
        waste_grams=golden.PURGE_GRAMS,
        expected_yield=golden.EXPECTED_YIELD,
        failure_mode="per_part",
        labor_hours_per_plate=Decimal("0"),
        labor_hours_per_item=golden.AT_RISK_LABOR_MINUTES / MINUTES_PER_HOUR,
        finishing_hours_per_item=Decimal("0"),
        packing_hours_per_item=golden.PACKING_LABOR_MINUTES / MINUTES_PER_HOUR,
        actual_production_cost=None,
        is_active=True,
    )
    defaults.update(overrides)
    model = Model(**defaults)
    # A plate's material weight is recorded for the whole plate, which is why
    # the engine divides it by the plate count.
    model.materials = [
        ModelMaterial(
            id=uuid4(),
            model_id=model.id,
            spool_id=uuid4(),
            weight_grams=part_grams * Decimal(prints_per_plate),
            cost_per_gram=cost_per_gram,
        )
    ]
    model.components = []
    model.printer_configs = []
    return model


def make_product(model: Model, **overrides) -> Product:
    """A sellable unit holding one of the golden items, plus its packaging."""
    from app.models.product_model import ProductModel

    defaults = dict(
        id=uuid4(),
        tenant_id=model.tenant_id,
        sku=f"GOLD-PROD-{uuid4().hex[:6]}",
        name="Golden case product",
        packaging_cost=golden.PACKAGING_COST,
        packaging_quantity=1,
        assembly_minutes=0,
        is_active=True,
    )
    defaults.update(overrides)
    product = Product(**defaults)
    link = ProductModel(id=uuid4(), product_id=product.id, model_id=model.id, quantity=1)
    link.model = model
    product.product_models = [link]
    product.child_products = []
    product.packaging_consumable = None
    return product


@pytest.fixture
def golden_printer() -> Printer:
    return make_printer()


@pytest.fixture
def golden_policy() -> CostPolicy:
    return make_policy()


@pytest.fixture
def golden_model() -> Model:
    return make_model()


@pytest.fixture
def golden_product(golden_model: Model) -> Product:
    return make_product(golden_model)


# ---------------------------------------------------------------------------
# The channel side (User Story 3)
# ---------------------------------------------------------------------------


def make_fee_rule(
    name: str,
    basis: str,
    *,
    rate_pct: Decimal = Decimal("0"),
    fixed_amount: Decimal = Decimal("0"),
    sort_order: int = 0,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    incidence_pct: Decimal | None = None,
    applies_from: date | None = None,
    applies_to: date | None = None,
    **overrides,
) -> FeeRule:
    """One unsaved fee rule.

    Dates default to a rule that has always applied and still does, because
    almost every test is about arithmetic rather than about effective periods;
    the ones that are about periods pass them explicitly.
    """
    defaults = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        sales_channel_id=uuid4(),
        name=name,
        basis=basis,
        rate_pct=rate_pct,
        fixed_amount=fixed_amount,
        min_amount=min_amount,
        max_amount=max_amount,
        incidence_pct=incidence_pct,
        sort_order=sort_order,
        applies_from=applies_from or date(2020, 1, 1),
        applies_to=applies_to,
    )
    defaults.update(overrides)
    return FeeRule(**defaults)


def golden_fee_rules() -> list[FeeRule]:
    """The golden channel's fee stack, built from the fixture's rows."""
    return [
        make_fee_rule(
            name,
            basis,
            rate_pct=rate,
            fixed_amount=fixed,
            sort_order=order,
        )
        for name, basis, rate, fixed, order in golden.CHANNEL_FEE_RULES
    ]


def golden_variable_rate_pct() -> Decimal:
    """The aggregate percentage the golden channel charges, from its rules.

    research.md D10 names 12.5%. It is recomputed here rather than asserted as
    a constant, so changing one rule's rate fails the case that depends on the
    aggregate instead of quietly moving it.
    """
    return sum(
        (rate for _, basis, rate, _, _ in golden.CHANNEL_FEE_RULES if basis not in COUNT_BASES),
        Decimal("0"),
    )


def golden_fixed_fee_total() -> Decimal:
    """The aggregate fixed amount the golden channel charges, from its rules."""
    return sum((fixed for _, _, _, fixed, _ in golden.CHANNEL_FEE_RULES), Decimal("0"))


def make_channel(**overrides) -> SalesChannel:
    """The golden case's channel, with its economics complete.

    Every lever is set explicitly: column defaults are applied by the database
    at flush, not by the constructor, so an unsaved instance carries ``None``
    where the schema would carry a default, and a ``None`` the engine happens
    to treat as zero is not the same as a tested default.
    """
    rules = overrides.pop("fee_rules", None)
    defaults = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        name="Golden Marketplace",
        platform_type="etsy",
        fee_percentage=Decimal("0"),
        fee_fixed=Decimal("0"),
        monthly_cost=Decimal("0"),
        tax_remitter=golden.CHANNEL_TAX_REMITTER,
        expected_discount_pct=golden.CHANNEL_EXPECTED_DISCOUNT_PCT,
        expected_refund_pct=golden.CHANNEL_EXPECTED_REFUND_PCT,
        free_shipping_threshold=None,
        rounding_rule=None,
        currency_code=golden.CHANNEL_CURRENCY_CODE,
        offsite_ads_opt_in=False,
        is_active=True,
    )
    defaults.update(overrides)
    channel = SalesChannel(**defaults)
    channel.fee_rules = golden_fee_rules() if rules is None else list(rules)
    for rule in channel.fee_rules:
        rule.sales_channel_id = channel.id
        rule.tenant_id = channel.tenant_id
    return channel


def golden_order_context(**overrides) -> OrderContext:
    """The golden sale: one unit at CA$64.99 with free shipping."""
    defaults = dict(
        item_subtotal=golden.LIST_PRICE,
        shipping_revenue=golden.CHANNEL_SHIPPING_REVENUE,
        quantity=1,
    )
    defaults.update(overrides)
    return OrderContext(**defaults)


@pytest.fixture
def golden_channel() -> SalesChannel:
    return make_channel()


@pytest.fixture
def golden_context() -> OrderContext:
    return golden_order_context()
