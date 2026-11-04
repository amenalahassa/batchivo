"""Production runs weigh an item as the cost does (``grams_per_item``).

The cost reads a model's filament from the planned printer's measured per-item
weight when its per-printer row has one, else from the bill of materials (a
whole plate run) divided by items per plate. Production runs weigh successful
items through ``grams_per_item``; these tests hold the two to one answer.
"""

from decimal import Decimal
from uuid import uuid4

from app.models.model_printer_config import ModelPrinterConfig
from app.services.costing import CostingService, grams_per_item
from tests.unit.pricing.conftest import make_model, make_policy, make_printer

MILLE = Decimal("0.001")


def _material_cost(model, printer) -> Decimal:
    flat = CostingService.calculate_model_cost(model, policy=make_policy(), printer=printer)
    return flat.material_cost


def _per_gram(model) -> Decimal:
    return model.materials[0].cost_per_gram


def test_the_bill_divided_by_items_matches_the_material_line():
    printer = make_printer()
    model = make_model(prints_per_plate=4, waste_grams=Decimal("0"))
    expected = (grams_per_item(model, printer.id) * _per_gram(model)).quantize(MILLE)
    assert expected == _material_cost(model, printer)


def test_a_measured_per_printer_weight_matches_the_material_line():
    printer = make_printer()
    model = make_model(prints_per_plate=4, waste_grams=Decimal("0"))
    model.printer_configs = [
        ModelPrinterConfig(
            id=uuid4(),
            model_id=model.id,
            printer_id=printer.id,
            material_weight_grams=Decimal("18"),
        )
    ]
    assert grams_per_item(model, printer.id) == Decimal("18")
    expected = (Decimal("18") * _per_gram(model)).quantize(MILLE)
    assert expected == _material_cost(model, printer)


def test_a_printers_own_items_per_plate_matches_the_material_line():
    printer = make_printer()
    model = make_model(prints_per_plate=4, waste_grams=Decimal("0"))
    model.printer_configs = [
        ModelPrinterConfig(id=uuid4(), model_id=model.id, printer_id=printer.id, prints_per_plate=6)
    ]
    bill = model.materials[0].weight_grams
    assert grams_per_item(model, printer.id) == bill / 6
    expected = (grams_per_item(model, printer.id) * _per_gram(model)).quantize(MILLE)
    assert expected == _material_cost(model, printer)
