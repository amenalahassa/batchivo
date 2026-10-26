"""A printer whose bed the model does not fit is not offered (T066, research D12)."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.print_queue_service import PrintQueueService, fits_bed

pytestmark = pytest.mark.asyncio


def _model(dims=None, configs=()) -> SimpleNamespace:
    length, width, height = (Decimal(str(v)) for v in dims) if dims else (None, None, None)
    return SimpleNamespace(
        sku="M-1",
        length_mm=length,
        width_mm=width,
        height_mm=height,
        printer_configs=list(configs),
        materials=[],
    )


def _printer(bed=(256, 256, 256)) -> SimpleNamespace:
    x, y, z = bed if bed else (None, None, None)
    return SimpleNamespace(
        id=uuid4(),
        name="P1S",
        bed_size_x_mm=x,
        bed_size_y_mm=y,
        bed_size_z_mm=z,
        bed_size_str=f"{x}x{y}x{z}",
        capabilities=None,
    )


async def _compatible(printer, model) -> bool:
    service = PrintQueueService.__new__(PrintQueueService)
    return await service._is_printer_compatible(printer, model)  # type: ignore[arg-type]


async def test_too_long_for_the_bed_is_excluded() -> None:
    assert await _compatible(_printer(), _model((300, 100, 50))) is False


async def test_a_footprint_that_fits_turned_is_included() -> None:
    printer = _printer((300, 200, 200))
    assert fits_bed(_model((180, 250, 50)), printer) is True  # type: ignore[arg-type]
    assert await _compatible(printer, _model((180, 250, 50))) is True


async def test_too_tall_is_excluded() -> None:
    assert await _compatible(_printer((256, 256, 100)), _model((50, 50, 120))) is False


async def test_without_model_dimensions_nothing_changes() -> None:
    assert await _compatible(_printer(), _model()) is True


async def test_without_all_bed_sizes_nothing_changes() -> None:
    printer = _printer((256, 256, None))
    assert await _compatible(printer, _model((900, 900, 900))) is True


async def test_an_explicit_printer_config_still_wins() -> None:
    printer = _printer()
    config = SimpleNamespace(printer_id=printer.id)
    assert await _compatible(printer, _model((900, 900, 900), configs=[config])) is True
