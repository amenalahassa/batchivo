"""CalibrationService rules (spec 009, T042): exact values, supersede chain, precedence."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.calibration import CalibrationCreate
from app.services.calibration_service import CalibrationError, CalibrationService

SLIDE = {
    "fit_type": "slide",
    "orientation": "vertical",
    "provenance": "measured",
    "material": "PLA",
}


@pytest.fixture
def service(db_session, test_tenant, test_user) -> CalibrationService:
    return CalibrationService(db_session, test_tenant, test_user)


@pytest.mark.parametrize(
    "given,stored",
    [
        (0.1, Decimal("0.100")),
        ("0.15", Decimal("0.150")),
        ("0.2000", Decimal("0.200")),
        (2, Decimal("2.000")),
    ],
)
def test_values_are_exact_to_the_micron(given, stored):
    assert CalibrationCreate(**SLIDE, value_mm=given).value_mm == stored


@pytest.mark.parametrize("bad", ["0.1234", "2.001", "-0.001"])
def test_out_of_range_or_too_precise(bad):
    with pytest.raises(ValidationError):
        CalibrationCreate(**SLIDE, value_mm=bad)


async def test_supersede_chain(service, test_printer, test_material_type):
    values = ["0.150", "0.180", "0.170"]
    rows = [
        await service.record(test_printer.id, CalibrationCreate(**SLIDE, value_mm=v))
        for v in values
    ]
    first, second, third = rows
    assert first.superseded_by_id == second.id and first.superseded_at is not None
    assert second.superseded_by_id == third.id
    assert third.is_current and third.value_mm == Decimal("0.170")
    current = await service.list_for_printer(test_printer.id, current_only=True)
    assert [c.id for c in current] == [third.id]


async def test_precedence(service, test_printer, test_filament_type, test_material_type):
    found, matched = await service.lookup(
        test_printer.id, "slide", "vertical", None, "PLA", test_filament_type.id
    )
    assert (found, matched) == (None, None)
    material = await service.record(test_printer.id, CalibrationCreate(**SLIDE, value_mm="0.15"))
    found, matched = await service.lookup(
        test_printer.id, "slide", "vertical", test_material_type.id, None, test_filament_type.id
    )
    assert (found.id, matched) == (material.id, "material")
    own = await service.record(
        test_printer.id,
        CalibrationCreate(**SLIDE, value_mm="0.12", filament_type_id=test_filament_type.id),
    )
    found, matched = await service.lookup(
        test_printer.id, "slide", "vertical", None, None, test_filament_type.id
    )
    assert (found.id, matched) == (own.id, "filament")
    other_fit, _ = await service.lookup(test_printer.id, "press", "vertical", None, "PLA", None)
    assert other_fit is None


async def test_lookup_without_material_or_filament(service, test_printer, test_material_type):
    with pytest.raises(CalibrationError) as raised:
        await service.lookup(test_printer.id, "slide", "vertical", None, None, None)
    assert raised.value.status_code == 422
