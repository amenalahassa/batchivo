"""Unit tests for PrintQueueService._is_printer_compatible (pure async method)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.print_queue_service import PrintQueueService


@pytest.fixture
def service() -> PrintQueueService:
    """PrintQueueService with mocked dependencies."""
    return PrintQueueService(db=AsyncMock(), tenant=MagicMock())


def make_printer(printer_id=None, capabilities=None):
    """Build a minimal Printer-like namespace."""
    return SimpleNamespace(
        id=printer_id or uuid4(),
        capabilities=capabilities,
    )


def make_model(printer_configs=None, materials=None):
    """Build a minimal Model-like namespace."""
    return SimpleNamespace(
        printer_configs=printer_configs or [],
        materials=materials or [],
    )


def make_config(printer_id):
    """Build a minimal PrinterConfig-like namespace."""
    return SimpleNamespace(printer_id=printer_id)


def make_material(material_code):
    """Build a bill-of-materials line shaped like the real one.

    The code lives on the material type, reached through the line's spool and
    the spool's filament type. An earlier version of this helper put
    `material_code` on the line itself, an attribute `ModelMaterial` does not
    have, so these tests passed while auto-assign raised AttributeError
    (bug print-queue-material-code).
    """
    material_type = SimpleNamespace(code=material_code)
    spool = SimpleNamespace(filament_type=SimpleNamespace(material_type=material_type))
    return SimpleNamespace(spool=spool)


class TestIsPrinterCompatible:
    """Tests for PrintQueueService._is_printer_compatible."""

    @pytest.mark.asyncio
    async def test_specific_config_match_returns_true(self, service: PrintQueueService):
        printer_id = uuid4()
        printer = make_printer(printer_id=printer_id)
        model = make_model(printer_configs=[make_config(printer_id)])
        result = await service._is_printer_compatible(printer, model)
        assert result is True

    @pytest.mark.asyncio
    async def test_specific_config_for_different_printer_not_matched(
        self, service: PrintQueueService
    ):
        printer = make_printer(printer_id=uuid4())
        other_id = uuid4()
        # Model has config for another printer, no materials restrictions
        model = make_model(printer_configs=[make_config(other_id)])
        # No capabilities on printer, no materials on model → should fall through to True
        result = await service._is_printer_compatible(printer, model)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_config_no_materials_returns_true(self, service: PrintQueueService):
        printer = make_printer()
        model = make_model()
        result = await service._is_printer_compatible(printer, model)
        assert result is True

    @pytest.mark.asyncio
    async def test_printer_supports_required_material(self, service: PrintQueueService):
        printer = make_printer(capabilities={"materials": ["PLA", "PETG"]})
        model = make_model(materials=[make_material("PLA")])
        result = await service._is_printer_compatible(printer, model)
        assert result is True

    @pytest.mark.asyncio
    async def test_printer_missing_required_material_returns_false(
        self, service: PrintQueueService
    ):
        printer = make_printer(capabilities={"materials": ["PLA"]})
        model = make_model(materials=[make_material("ABS")])
        result = await service._is_printer_compatible(printer, model)
        assert result is False

    @pytest.mark.asyncio
    async def test_all_materials_must_be_supported(self, service: PrintQueueService):
        # Model needs both PLA and ABS; printer only has PLA
        printer = make_printer(capabilities={"materials": ["PLA"]})
        model = make_model(materials=[make_material("PLA"), make_material("ABS")])
        result = await service._is_printer_compatible(printer, model)
        assert result is False

    @pytest.mark.asyncio
    async def test_all_materials_supported_returns_true(self, service: PrintQueueService):
        printer = make_printer(capabilities={"materials": ["PLA", "ABS", "PETG"]})
        model = make_model(materials=[make_material("PLA"), make_material("ABS")])
        result = await service._is_printer_compatible(printer, model)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_capabilities_with_materials_skips_check(self, service: PrintQueueService):
        # If printer has no capabilities dict, material check is skipped → True
        printer = make_printer(capabilities=None)
        model = make_model(materials=[make_material("ABS")])
        result = await service._is_printer_compatible(printer, model)
        assert result is True

    @pytest.mark.asyncio
    async def test_capabilities_without_materials_key_uses_empty_list(
        self, service: PrintQueueService
    ):
        # capabilities exists but has no "materials" key → empty list → any material fails
        printer = make_printer(capabilities={"color": "blue"})
        model = make_model(materials=[make_material("PLA")])
        result = await service._is_printer_compatible(printer, model)
        assert result is False

    @pytest.mark.asyncio
    async def test_specific_config_match_overrides_material_check(self, service: PrintQueueService):
        # If printer has an explicit config for this model, material check is skipped entirely
        printer_id = uuid4()
        printer = make_printer(printer_id=printer_id, capabilities={"materials": ["PLA"]})
        model = make_model(
            printer_configs=[make_config(printer_id)],
            materials=[make_material("ABS")],  # Would fail material check
        )
        result = await service._is_printer_compatible(printer, model)
        assert result is True  # Early return from config match

    @pytest.mark.asyncio
    async def test_multiple_configs_correct_one_matches(self, service: PrintQueueService):
        printer_id = uuid4()
        other_id = uuid4()
        printer = make_printer(printer_id=printer_id)
        model = make_model(
            printer_configs=[make_config(other_id), make_config(printer_id)],
        )
        result = await service._is_printer_compatible(printer, model)
        assert result is True


class TestMaterialCodeResolution:
    @pytest.mark.asyncio
    async def test_a_line_with_no_spool_does_not_block_assignment(self, service: PrintQueueService):
        printer = make_printer(capabilities={"materials": ["PLA"]})
        model = make_model(materials=[SimpleNamespace(spool=None)])
        assert await service._is_printer_compatible(printer, model) is True

    @pytest.mark.asyncio
    async def test_codes_compare_without_regard_to_case(self, service: PrintQueueService):
        printer = make_printer(capabilities={"materials": ["pla"]})
        model = make_model(materials=[make_material("PLA")])
        assert await service._is_printer_compatible(printer, model) is True

    @pytest.mark.asyncio
    async def test_the_real_model_has_no_material_code(self) -> None:
        """Pin the shape the helper above mirrors."""
        from app.models.model_material import ModelMaterial

        assert not hasattr(ModelMaterial, "material_code")
        assert hasattr(ModelMaterial, "spool")
