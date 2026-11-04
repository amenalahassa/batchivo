"""A margin built on catalogue packaging says its cost is assumed, or missing (spec 006, T033).

FR-014: a seeded item's typical cost is recorded ``assumed``, and the packaging
line carries that origin into the breakdown's observed share; an item seeded
without a cost (a currency the catalogue quotes no price in) makes the margin
say the packaging cost is missing rather than costing it at zero silently.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.models.consumable import ConsumableType
from app.services.costing import CostingService, packaging_cost_missing
from app.services.provenance import FieldOrigin, breakdown_observed_share
from tests.unit.pricing.conftest import make_model, make_policy, make_printer, make_product

AS_OF = date(2026, 11, 1)


def _box(cost):
    return ConsumableType(
        id=uuid4(),
        tenant_id=uuid4(),
        sku="PKG-BOX-CUBE-100",
        name="Box cube 100",
        packaging_kind="box",
        current_cost_per_unit=Decimal(cost) if cost is not None else None,
        catalogue_key="box-cube-100",
        purchases=[],
    )


def _breakdown(box, origins=None):
    model = make_model()
    product = make_product(model, packaging_quantity=1)
    product.packaging_consumable = box
    return product, CostingService.product_breakdown(
        product,
        policy=make_policy(),
        printer_for_model={model.id: make_printer()},
        origins=origins,
    )


class TestAssumedPackagingCost:
    def test_the_packaging_line_carries_the_assumed_origin(self):
        box = _box("0.95")
        origins = {
            ("consumable_type", box.id, "current_cost_per_unit"): FieldOrigin("assumed", AS_OF)
        }
        _, breakdown = _breakdown(box, origins)
        line = next(line for line in breakdown.lines if line.key == "packaging")
        assert line.amount == Decimal("0.95")
        assert line.source == "assumed" and line.as_of == AS_OF

    def test_an_assumed_line_counts_against_the_observed_share(self):
        box = _box("0.95")
        assumed = {
            ("consumable_type", box.id, "current_cost_per_unit"): FieldOrigin("assumed", AS_OF)
        }
        measured = {
            ("consumable_type", box.id, "current_cost_per_unit"): FieldOrigin("measured", AS_OF)
        }
        _, with_assumed = _breakdown(box, assumed)
        _, with_measured = _breakdown(box, measured)
        assert (
            breakdown_observed_share(with_assumed)[1] > breakdown_observed_share(with_measured)[1]
        )

    def test_a_known_cost_is_not_reported_missing(self):
        product, breakdown = _breakdown(_box("0.95"))
        assert packaging_cost_missing(product) is None
        assert not any("packaging cost is missing" in r for r in breakdown.incomplete_reasons)


class TestMissingPackagingCost:
    def test_a_seeded_item_without_cost_makes_the_margin_say_so(self):
        product, breakdown = _breakdown(_box(None))
        assert "packaging" not in {line.key for line in breakdown.lines}
        assert any(
            "Box cube 100" in r and "packaging cost is missing" in r
            for r in breakdown.incomplete_reasons
        )
        assert packaging_cost_missing(product) is not None

    def test_a_product_without_packaging_is_not_reported(self):
        model = make_model()
        product = make_product(model)
        assert packaging_cost_missing(product) is None
