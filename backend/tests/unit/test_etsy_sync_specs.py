"""The size line in an Etsy listing's specifications (T067, research D12)."""

from decimal import Decimal
from uuid import uuid4

from app.models.product import Product
from app.services.etsy_sync import EtsySyncService


def _product(**overrides) -> Product:
    """An unsaved product: the listing is built from its attributes alone."""
    return Product(
        id=uuid4(),
        name="Dragon",
        sku="DRG-01",
        shop_description="A dragon.",
        weight_grams=180,
        **overrides,
    )


def _description(product) -> str:
    service = EtsySyncService(db=None, tenant_id=uuid4())  # type: ignore[arg-type]
    return service._build_etsy_listing_data(product)["description"]


def test_dimensions_give_the_size_in_mm() -> None:
    product = _product(
        length_mm=Decimal("120"), width_mm=Decimal("80"), height_mm=Decimal("45"), size_cm="12"
    )
    description = _description(product)
    assert "• Size: 120.0 × 80.0 × 45.0 mm" in description
    assert "12cm" not in description


def test_without_dimensions_the_free_text_size_stays() -> None:
    assert "• Size: 12cm" in _description(_product(size_cm="12"))


def test_without_either_there_is_no_size_line() -> None:
    assert "Size:" not in _description(_product())
