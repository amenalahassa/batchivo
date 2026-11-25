"""Spans on the pricing paths (T122).

Observability has one hard rule: it must not change what it observes. So most
of this file is about what the spans *do not* do -- they do not swallow an
exception, do not alter a return value, do not require a tracer, and do not
carry a tenant's commercial figures off to a backend with a different audience
and a different retention from the application's own data.

The rest confirms the spans actually exist, because a decorator that silently
stopped wrapping would leave a slow pricing screen indistinguishable from a
slow database, which is the problem T122 exists to solve.
"""

from datetime import date
from decimal import Decimal

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.observability.tracing import pricing_span, traced
from app.services import fee_engine
from app.services.costing import CostingService
from app.services.pricing_solver import ladder, solve
from tests.fixtures import golden_case as golden
from tests.unit.pricing.conftest import (
    golden_order_context,
    make_channel,
    make_model,
    make_policy,
    make_printer,
    make_product,
)

AS_OF = date(2026, 6, 1)

# The golden case's make cost for one item, before packaging. Asserted here so
# a decorator that quietly altered a return value could not pass unnoticed.
ITEM_MAKE_COST = Decimal("19.38")


@pytest.fixture
def recorded():
    """A real tracer provider whose spans land in memory.

    The global is restored afterwards. OpenTelemetry refuses a second
    `set_tracer_provider`, so the private attribute is put back by hand -- the
    alternative is a test that poisons every later test in the process.

    The snapshot is `trace._TRACER_PROVIDER` itself, **not**
    `trace.get_tracer_provider()`. The accessor returns a proxy provider when
    none is set, and that proxy resolves its tracer by calling the accessor
    again -- so restoring its return value as the global makes every later
    `get_tracer` call recurse until the stack runs out. Which it duly did,
    hundreds of tests later, in a suite that had nothing to do with pricing.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    previous = trace._TRACER_PROVIDER  # noqa: SLF001 - no public getter for the raw global
    trace._TRACER_PROVIDER = provider  # noqa: SLF001 - no public setter to undo
    try:
        yield exporter
    finally:
        trace._TRACER_PROVIDER = previous  # noqa: SLF001


def names(exporter) -> list[str]:
    return [span.name for span in exporter.get_finished_spans()]


# ---------------------------------------------------------------------------
# The spans exist
# ---------------------------------------------------------------------------


class TestThePricingPathsAreTraced:
    def test_costing_an_item_opens_a_span(self, recorded) -> None:
        CostingService.item_breakdown(make_model(), policy=make_policy(), printer=make_printer())

        assert "cost.item_breakdown" in names(recorded)

    def test_costing_a_product_opens_a_span(self, recorded) -> None:
        CostingService.product_breakdown(make_product(make_model()), policy=make_policy())

        assert "cost.product_breakdown" in names(recorded)

    def test_the_fee_engine_opens_a_span(self, recorded) -> None:
        channel = make_channel()
        fee_engine.compute(channel, golden_order_context(), AS_OF)

        assert "fee.compute" in names(recorded)

    def test_a_margin_opens_a_span(self, recorded) -> None:
        channel = make_channel()
        context, treatment = fee_engine.exclusive_context(item_subtotal=golden.LIST_PRICE)
        CostingService.margin(
            context=context,
            make_cost=ITEM_MAKE_COST + golden.PACKAGING_COST,
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(),
            tax=treatment,
        )

        assert "cost.margin" in names(recorded)

    def test_the_solver_opens_a_span(self, recorded) -> None:
        solve(
            channel=make_channel(),
            make_cost=ITEM_MAKE_COST + golden.PACKAGING_COST,
            target_margin_pct=Decimal("35"),
            as_of=AS_OF,
            postage_paid=golden.POSTAGE_PAID,
            policy=make_policy(),
        )

        assert "price.solve" in names(recorded)

    def test_the_ladder_opens_a_span(self, recorded) -> None:
        ladder(
            channel=make_channel(),
            make_cost=ITEM_MAKE_COST + golden.PACKAGING_COST,
            start=Decimal("60.00"),
            stop=Decimal("62.00"),
            step=Decimal("1.00"),
            as_of=AS_OF,
            policy=make_policy(),
        )

        assert "price.ladder" in names(recorded)

    def test_a_bundle_nests_its_children(self, recorded) -> None:
        # The useful shape: the trace shows how deep the bill of materials went
        # and which child cost the time.
        CostingService.product_breakdown(make_product(make_model()), policy=make_policy())

        assert names(recorded).count("cost.product_breakdown") >= 1
        assert "cost.item_breakdown" in names(recorded)


# ---------------------------------------------------------------------------
# What the spans must not do
# ---------------------------------------------------------------------------


class TestTracingDoesNotChangeWhatItObserves:
    def test_the_cost_is_the_same_figure(self, recorded) -> None:
        # The acceptance case, through an instrumented engine. If a decorator
        # ever altered a return value this is where it would show.
        breakdown = CostingService.item_breakdown(
            make_model(), policy=make_policy(), printer=make_printer()
        )

        assert breakdown.total_make_cost == ITEM_MAKE_COST

    def test_the_product_keeps_its_packaging_line(self, recorded) -> None:
        # A decorator on the recursive product path must leave the composed
        # breakdown intact, lines and all.
        breakdown = CostingService.product_breakdown(
            make_product(make_model()), policy=make_policy()
        )

        packaging = [line for line in breakdown.lines if line.key == "packaging"]
        assert [line.amount for line in packaging] == [golden.PACKAGING_COST]

    def test_it_works_with_no_tracer_configured(self) -> None:
        # The ordinary case in development and in the test suite: no provider,
        # so OpenTelemetry hands back a non-recording tracer.
        breakdown = CostingService.item_breakdown(
            make_model(), policy=make_policy(), printer=make_printer()
        )

        assert breakdown.total_make_cost == ITEM_MAKE_COST

    def test_an_exception_propagates_unchanged(self, recorded) -> None:
        @traced("test.raises")
        def explode() -> None:
            raise ValueError("the body failed")

        with pytest.raises(ValueError, match="the body failed"):
            explode()

    def test_the_failing_span_is_still_recorded(self, recorded) -> None:
        # A failure that leaves no span is a failure nobody can find.
        @traced("test.raises")
        def explode() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            explode()

        assert "test.raises" in names(recorded)

    def test_a_broken_tracer_does_not_break_the_body(self, monkeypatch) -> None:
        # An observability backend misconfigured at startup must not take the
        # pricing engine down with it.
        def _explode(_name):
            raise RuntimeError("tracer provider is misconfigured")

        monkeypatch.setattr("app.observability.tracing.trace.get_tracer", _explode)

        ran = []
        with pricing_span("test.unavailable"):
            ran.append(True)

        assert ran == [True]

    def test_a_bad_attribute_does_not_break_the_body(self, recorded) -> None:
        class Awkward:
            def __str__(self) -> str:
                raise RuntimeError("cannot be rendered")

        ran = []
        with pricing_span("test.awkward", thing=Awkward()):
            ran.append(True)

        assert ran == [True]

    def test_the_decorator_keeps_the_function_identity(self) -> None:
        # `functools.wraps`, so a traced function still reads as itself in a
        # traceback and in the OpenAPI schema FastAPI builds from signatures.
        @traced("test.named")
        def original(first: int, second: int = 2) -> int:
            """A docstring worth keeping."""
            return first + second

        assert original.__name__ == "original"
        assert original.__doc__ == "A docstring worth keeping."
        assert original(1, second=4) == 5


class TestNoCommercialFigureLeavesInASpan:
    """A trace goes to a backend with a different audience and retention from
    the application's own data. A span attribute carrying a margin is a
    tenant's commercial position leaving by a side door."""

    def test_no_span_carries_a_money_or_identity_attribute(self, recorded) -> None:
        channel = make_channel()
        context, treatment = fee_engine.exclusive_context(item_subtotal=golden.LIST_PRICE)
        CostingService.margin(
            context=context,
            make_cost=ITEM_MAKE_COST + golden.PACKAGING_COST,
            channel=channel,
            fees=fee_engine.compute(channel, context, AS_OF),
            policy=make_policy(),
            tax=treatment,
            machine_hours=golden.PRINT_HOURS,
        )
        CostingService.product_breakdown(make_product(make_model()), policy=make_policy())

        forbidden = (
            "price",
            "cost",
            "margin",
            "profit",
            "amount",
            "tenant",
            "product_id",
            "sku",
        )
        for span in recorded.get_finished_spans():
            for key in span.attributes or {}:
                assert not any(word in key.removeprefix("pricing.") for word in forbidden), (
                    f"{span.name} carries {key}, which is tenant data"
                )

    def test_a_span_carries_no_attributes_it_was_not_given(self, recorded) -> None:
        with pricing_span("test.bare"):
            pass

        bare = [span for span in recorded.get_finished_spans() if span.name == "test.bare"]
        assert bare
        assert not bare[0].attributes

    def test_a_none_attribute_is_dropped_rather_than_sent_as_null(self, recorded) -> None:
        with pricing_span("test.partial", rungs=4, missing=None):
            pass

        span = next(s for s in recorded.get_finished_spans() if s.name == "test.partial")
        assert span.attributes is not None
        assert span.attributes.get("pricing.rungs") == 4
        assert "pricing.missing" not in span.attributes


class TestTheFixtureLeavesTheGlobalAsItFoundIt:
    """Because the first version of it did not.

    Restoring `get_tracer_provider()`'s return value instead of the raw global
    left a proxy provider installed as the provider it proxies. Nothing failed
    here; a production-run test three thousand cases later died of a
    `RecursionError` inside OpenTelemetry, which is the worst kind of failure
    to debug -- the symptom is nowhere near the cause.
    """

    def test_the_global_provider_is_untouched_after_a_recorded_test(self, recorded) -> None:
        with pricing_span("test.installed"):
            pass

    def test_a_tracer_can_still_be_got_after_the_fixture_tore_down(self) -> None:
        # Runs after the test above, with no `recorded` fixture of its own: if
        # teardown left a self-delegating provider behind, this recurses.
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("test.after"):
            pass
