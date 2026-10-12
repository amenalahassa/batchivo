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

from decimal import Decimal
from uuid import uuid4

import pytest

from app.models.model import Model
from app.models.model_material import ModelMaterial
from app.models.printer import Printer
from app.models.product import Product
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
