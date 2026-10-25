"""A database built from migrations alone has the product_variants table.

No revision created ``product_variants`` until ``create_product_variants_v1``;
the earlier ones only altered it where it already existed, so a freshly
migrated database (CI's end-to-end stage) failed the product list with
``relation "product_variants" does not exist``. These tests hold the creating
revision to the model, and to leaving an existing table alone.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from app.models.product_variant import ProductVariant

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261025_create_product_variants.py"
)


def _load_migration(op: MagicMock) -> ModuleType:
    spec = importlib.util.spec_from_file_location("create_product_variants", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = op  # type: ignore[attr-defined]
    return module


def _op(table_exists: bool) -> MagicMock:
    op = MagicMock()
    op.get_bind.return_value.execute.return_value.scalar.return_value = table_exists
    return op


def test_creates_the_table_with_every_column_the_model_maps() -> None:
    op = _op(table_exists=False)
    _load_migration(op).upgrade()

    op.create_table.assert_called_once()
    name, *elements = op.create_table.call_args.args
    assert name == "product_variants"
    created = {element.name for element in elements if hasattr(element, "type")}
    assert created == {column.name for column in ProductVariant.__table__.columns}


@pytest.mark.parametrize("nullable_column", ["lead_time_days", "material_cost_pence"])
def test_matches_the_model_on_nullability(nullable_column: str) -> None:
    op = _op(table_exists=False)
    _load_migration(op).upgrade()

    _, *elements = op.create_table.call_args.args
    column = next(e for e in elements if getattr(e, "name", None) == nullable_column)
    assert column.nullable == ProductVariant.__table__.columns[nullable_column].nullable


def test_leaves_an_existing_table_alone() -> None:
    op = _op(table_exists=True)
    _load_migration(op).upgrade()

    op.create_table.assert_not_called()
    op.create_index.assert_not_called()


def test_downgrade_never_drops_the_table() -> None:
    op = _op(table_exists=True)
    _load_migration(op).downgrade()

    op.drop_table.assert_not_called()
