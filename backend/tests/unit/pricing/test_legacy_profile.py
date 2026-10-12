"""The superseded model is reproducible without existing (task T062).

FR-052 requires the old figure to stay available during the migration so an
operator can see what changed. research.md D7 chose to satisfy that by running
the **one** engine with a profile of overrides, and rejected both alternatives
explicitly: keeping the old code behind a flag would be the parallel
implementation Constitution III forbids, and hardcoding the percentage
"reproduces one number for one product and proves nothing for any other".

So this file asserts two things, and the second matters more than the first:

1. The profile reproduces the superseded model's figure -- 66.4% -- on the
   golden item at the price the old model reported it at.
2. There is no second implementation for it to have come from. The figure is
   produced by :class:`CostingService` and by nothing else, and the methods
   that used to compute a parallel cost are gone.

Task T124 deletes this file and ``tests/fixtures/legacy_profile.py`` together
when FR-052 retires the comparison.
"""

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import fee_engine
from app.services.costing import CostingService
from tests.fixtures import golden_case as golden
from tests.fixtures import legacy_profile as legacy
from tests.unit.pricing.conftest import (
    make_channel,
    make_model,
    make_policy,
    make_printer,
    make_product,
)

AS_OF = date(2026, 6, 1)
CENT = Decimal("0.01")
MINUTES_PER_HOUR = Decimal("60")


def _legacy_item():
    """The golden item as the superseded model saw it.

    The one override that is not simply a zero: cost per gram divided by the
    spool's **nominal** weight, because the old model never knew about the
    unusable remainder on the core (FR-008d is the correction).
    """
    nominal_cost_per_gram = golden.SPOOL_LANDED_COST / golden.SPOOL_NOMINAL_GRAMS
    return make_model(cost_per_gram=nominal_cost_per_gram, **legacy.legacy_model_overrides())


def _legacy_breakdown():
    model = _legacy_item()
    return CostingService.product_breakdown(
        make_product(model),
        policy=legacy.legacy_policy(),
        printer_for_model={model.id: make_printer(**legacy.legacy_printer_overrides())},
    )


def _legacy_margin(price: Decimal = legacy.LEGACY_COMPARISON_PRICE):
    breakdown = _legacy_breakdown()
    channel = make_channel(**legacy.legacy_channel_overrides())
    context, treatment = fee_engine.exclusive_context(item_subtotal=price)
    return CostingService.margin(
        context=context,
        make_cost=breakdown.total_make_cost,
        channel=channel,
        fees=fee_engine.compute(channel, context, AS_OF),
        policy=legacy.legacy_policy(),
        tax=treatment,
        postage_paid=legacy.LEGACY_POSTAGE_PAID,
    )


# ============================================================================
# The figure
# ============================================================================


class TestTheSupersededFigureIsReproducible:
    def test_the_profile_reports_the_superseded_percentage(self) -> None:
        """FR-052: 66.4%, reproduced rather than stored."""
        assert _legacy_margin().margin_pct_display == Decimal("66.4")

    def test_the_percentage_is_derived_from_the_profile_inputs(self) -> None:
        """Recomputed here from the overrides, by the old model's own formula.

        Written out longhand on purpose: if the engine's legacy path and this
        arithmetic ever disagree, the override profile has stopped describing
        the superseded model and the comparison is worthless.
        """
        price = legacy.LEGACY_COMPARISON_PRICE

        material = golden.PART_GRAMS * golden.SPOOL_LANDED_COST / golden.SPOOL_NOMINAL_GRAMS
        handling = golden.AT_RISK_LABOR_MINUTES / MINUTES_PER_HOUR * legacy.LEGACY_LABOR_RATE
        packing = golden.PACKING_LABOR_MINUTES / MINUTES_PER_HOUR * legacy.LEGACY_LABOR_RATE
        overhead = (
            (material + handling + packing) * legacy.LEGACY_OVERHEAD_PERCENTAGE / Decimal("100")
        )
        cost = (
            material.quantize(CENT)
            + handling.quantize(CENT)
            + packing.quantize(CENT)
            + overhead.quantize(CENT)
            + golden.PACKAGING_COST.quantize(CENT)
        )
        fees = price * legacy.LEGACY_FEE_PERCENTAGE / Decimal("100") + legacy.LEGACY_FEE_FIXED
        expected = (price - cost - fees) / price * Decimal("100")

        assert expected.quantize(Decimal("0.1")) == Decimal("66.4")
        assert _legacy_margin().margin_pct_display == expected.quantize(Decimal("0.1"))

    def test_the_old_model_cost_the_item_less_than_the_new_one_does(self) -> None:
        """The whole reason the old margin flattered the business."""
        model = make_model()
        current = CostingService.product_breakdown(
            make_product(model),
            policy=make_policy(),
            printer_for_model={model.id: make_printer()},
        )

        assert _legacy_breakdown().total_make_cost == Decimal("9.81")
        assert current.total_make_cost == Decimal("20.30")


# ============================================================================
# Each override restores one thing the old model omitted
# ============================================================================


class TestWhatEachOverrideRestores:
    def test_the_old_model_costed_no_machine_occupancy(self) -> None:
        keys = {line.key for line in _legacy_breakdown().lines}

        assert "machine" not in keys

    def test_the_old_model_costed_no_purge_or_waste(self) -> None:
        keys = {line.key for line in _legacy_breakdown().lines}

        assert "waste" not in keys

    def test_the_old_model_charged_no_failure_premium(self) -> None:
        breakdown = _legacy_breakdown()

        assert breakdown.failure_premium == Decimal("0")
        assert breakdown.yield_applied == Decimal("1.0")

    def test_the_old_model_divided_by_nominal_rather_than_usable_weight(self) -> None:
        """FR-008d's correction, shown as a figure rather than described."""
        breakdown = _legacy_breakdown()
        material = next(line for line in breakdown.lines if line.key == "material")

        nominal = golden.PART_GRAMS * golden.SPOOL_LANDED_COST / golden.SPOOL_NOMINAL_GRAMS
        usable = (
            golden.PART_GRAMS
            * golden.SPOOL_LANDED_COST
            / (golden.SPOOL_NOMINAL_GRAMS - golden.SPOOL_UNUSABLE_REMAINDER_GRAMS)
        )

        assert material.amount == nominal.quantize(CENT)
        assert material.amount < usable.quantize(CENT)

    def test_the_old_model_absorbed_overhead_as_a_percentage(self) -> None:
        breakdown = _legacy_breakdown()
        overhead = next(line for line in breakdown.lines if line.key == "overhead")

        base = sum(
            (
                line.amount
                for line in breakdown.lines
                if line.key in ("material", "labor_handling", "labor_packing")
            ),
            Decimal("0"),
        )
        assert overhead.amount == (
            base * legacy.LEGACY_OVERHEAD_PERCENTAGE / Decimal("100")
        ).quantize(CENT)

    def test_the_old_model_held_no_reserves_and_knew_no_postage(self) -> None:
        result = _legacy_margin()

        assert result.deductions == []
        assert result.deduction_total == Decimal("0.00")
        assert result.postage_paid == Decimal("0.00")

    def test_the_whole_fee_stack_was_two_rules(self) -> None:
        """What the Tier 2 data migration produces from one channel."""
        result = _legacy_margin()

        assert [charge.name for charge in result.fees] == list(legacy.MIGRATED_RULE_NAMES)

    def test_the_two_rules_reproduce_the_single_percentage_plus_fixed(self) -> None:
        """FR-030, at the level of one sale."""
        price = legacy.LEGACY_COMPARISON_PRICE
        result = _legacy_margin(price)

        single_figure = (
            price * legacy.LEGACY_FEE_PERCENTAGE / Decimal("100") + legacy.LEGACY_FEE_FIXED
        )
        assert result.fee_total == single_figure.quantize(CENT)


# ============================================================================
# And no second implementation exists
# ============================================================================


class TestNoSecondCostImplementationExists:
    """research.md D7's actual requirement, which outlives the 66.4%."""

    def test_the_legacy_figure_comes_from_the_one_engine(self) -> None:
        """Nothing but `CostingService` produced the number above."""
        breakdown = _legacy_breakdown()

        assert breakdown is not None
        assert type(breakdown).__module__.startswith("app.schemas"), (
            "the legacy comparison returned something other than the engine's "
            "own breakdown type, which means a second path produced it"
        )

    def test_the_old_parallel_methods_are_gone(self) -> None:
        """Tier 0 deleted them; this fails if either is reintroduced."""
        from app.models.product import Product

        assert not hasattr(Product, "calculate_make_cost")
        assert not hasattr(Product, "_calculate_model_cost")

    def test_no_module_outside_the_engine_computes_a_make_cost(self) -> None:
        """A cheap structural guard against the defect coming back.

        Any function named like a cost calculation, anywhere under `app/`
        except the costing engine and its own callers' type hints, is a second
        implementation waiting to drift. The engine's public entry points are
        listed so adding one is a deliberate edit here.
        """
        allowed = {
            "app/services/costing.py",
            "app/services/landed_cost.py",
        }
        offenders: list[str] = []
        root = Path(__file__).resolve().parents[3] / "app"
        for path in root.rglob("*.py"):
            relative = path.relative_to(root.parent).as_posix()
            if relative in allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in (
                    "calculate_make_cost",
                    "_calculate_model_cost",
                ):
                    offenders.append(f"{relative}:{node.lineno} {node.name}")

        assert not offenders, (
            "a second make-cost implementation has appeared, which is what "
            f"Constitution III forbids: {offenders}"
        )

    def test_the_profile_is_data_and_deletable(self) -> None:
        """FR-052 retires this comparison; task T124 is one deletion.

        The profile is a fixture of plain values and the engine knows nothing
        about it, so retiring it removes two files and no production code.
        """
        import tests.fixtures.legacy_profile as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            name.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for name in node.names
        }
        assert "CostingService" not in imports, (
            "the legacy profile imported the engine, which would make it code rather than data"
        )

    def test_nothing_in_app_imports_the_legacy_profile(self) -> None:
        """Production code must not depend on a fixture that is about to go."""
        root = Path(__file__).resolve().parents[3] / "app"
        offenders = [
            path.relative_to(root.parent).as_posix()
            for path in root.rglob("*.py")
            if "legacy_profile" in path.read_text(encoding="utf-8")
        ]

        assert offenders == []


# ============================================================================
# The comparison the operator actually sees
# ============================================================================


class TestTheDeltaIsAttributable:
    def test_the_gap_between_old_and_new_is_the_lines_the_old_model_omitted(self) -> None:
        """FR-050's sibling: every change attributable to a named cause.

        The new cost is CA$20.30 and the old was CA$9.81. The difference must
        be exactly the lines the overrides removed plus the premium they
        suppressed -- not a residue nobody can explain.
        """
        model = make_model()
        current = CostingService.product_breakdown(
            make_product(model),
            policy=make_policy(),
            printer_for_model={model.id: make_printer()},
        )
        old = _legacy_breakdown()

        current_lines = {line.key: line.amount for line in current.lines}
        old_lines = {line.key: line.amount for line in old.lines}

        introduced = sum(
            (amount for key, amount in current_lines.items() if key not in old_lines),
            Decimal("0"),
        )
        moved = sum(
            (current_lines[key] - old_lines[key] for key in old_lines if key in current_lines),
            Decimal("0"),
        )
        gap = current.total_make_cost - old.total_make_cost

        assert gap == introduced + moved + current.failure_premium - old.failure_premium

    @pytest.mark.parametrize("key", ["machine", "waste"])
    def test_each_newly_introduced_line_is_named(self, key: str) -> None:
        current_keys = {
            line.key
            for line in CostingService.item_breakdown(
                make_model(), policy=make_policy(), printer=make_printer()
            ).lines
        }
        old_keys = {line.key for line in _legacy_breakdown().lines}

        assert key in current_keys
        assert key not in old_keys
