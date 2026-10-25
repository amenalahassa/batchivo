"""A bill-of-materials line costs at its spool's landed figure (task T254).

The line used to carry whatever per-gram figure the browser computed when it
was added -- purchase price over nominal weight -- so the landed cost of
FR-008 never reached a make-cost. These tests pin the resolution order: an
operator override, else the spool's landed cost, else an honest "cannot be
derived" rather than zero (FR-019).
"""

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.services.costing import _item_lines
from app.services.landed_cost import material_cost_per_gram

from tests.unit.pricing.conftest import make_policy


def _spool(price="25.00", weight="1000", remainder=None, purchase_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        spool_id="S-1",
        purchase_price=Decimal(price) if price is not None else None,
        initial_weight=Decimal(weight),
        unusable_remainder_grams=Decimal(remainder) if remainder is not None else None,
        filament_purchase_id=purchase_id,
    )


def _line(spool, grams="100", override=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        spool=spool,
        weight_grams=Decimal(grams),
        cost_per_gram=Decimal(override) if override is not None else None,
    )


class TestTheResolutionOrder:
    def test_an_empty_override_costs_at_the_spools_landed_figure(self) -> None:
        resolved = material_cost_per_gram(_line(_spool("30.00", "1000", remainder="250")))
        # 30.00 over 750 usable grams, not over the nominal 1000.
        assert resolved.cost_per_gram == Decimal("30.00") / Decimal("750")
        assert not resolved.overridden

    def test_an_override_wins_over_the_spool(self) -> None:
        resolved = material_cost_per_gram(_line(_spool("30.00"), override="0.0500"))
        assert resolved.cost_per_gram == Decimal("0.0500")
        assert resolved.overridden

    def test_a_spool_with_no_price_is_reported_not_zero(self) -> None:
        resolved = material_cost_per_gram(_line(_spool(price=None)))
        assert resolved.cost_per_gram is None
        assert resolved.incomplete_reasons


class TestTheEngineUsesIt:
    def test_the_material_line_follows_the_remainder(self) -> None:
        model = SimpleNamespace(
            id=uuid.uuid4(),
            materials=[_line(_spool("30.00", "1000", remainder="250"), grams="100")],
            prints_per_plate=1,
            print_time_minutes=60,
        )
        lines = _item_lines(model, make_policy())
        assert lines.amount("material") == Decimal("100") * Decimal("30.00") / Decimal("750")

    def test_an_underivable_line_makes_the_cost_incomplete(self) -> None:
        model = SimpleNamespace(
            id=uuid.uuid4(),
            materials=[_line(_spool(price=None))],
            prints_per_plate=1,
            print_time_minutes=60,
        )
        lines = _item_lines(model, make_policy())
        assert lines.amount("material") == Decimal("0")
        assert any(reason.startswith("material:") for reason in lines.incomplete_reasons)


def _load_report_script():
    path = Path(__file__).resolve().parents[3] / "scripts" / "material_cost_delta_report.py"
    spec = importlib.util.spec_from_file_location("material_cost_delta_report", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheMigrationsRuleForWhichFiguresWereDerivations:
    """The delta report must classify rows exactly as the migration's SQL does."""

    def test_the_browser_prefill_is_recognised(self) -> None:
        report = _load_report_script()
        # 24.99 / 1000 = 0.02499, which the browser kept at four places.
        assert report.is_browser_prefill(Decimal("0.0250"), Decimal("24.99"), Decimal("1000"))

    def test_a_typed_figure_is_kept(self) -> None:
        report = _load_report_script()
        assert not report.is_browser_prefill(Decimal("0.0300"), Decimal("24.99"), Decimal("1000"))

    def test_a_spool_without_price_or_weight_has_no_prefill(self) -> None:
        report = _load_report_script()
        assert not report.is_browser_prefill(Decimal("0.0250"), None, Decimal("1000"))
        assert not report.is_browser_prefill(Decimal("0.0250"), Decimal("25"), Decimal("0"))

    def test_the_report_names_the_cause_of_every_change(self) -> None:
        report = _load_report_script()
        rendered = report.render(
            [
                {
                    "tenant": "t",
                    "sku": "A",
                    "before": Decimal("10.00"),
                    "after": Decimal("10.40"),
                    "lines_cleared": 1,
                    "incomplete": [],
                }
            ]
        )
        assert "| t | A | 10.00 | 10.40 | 0.40 | 1 | landed_cost |" in rendered
