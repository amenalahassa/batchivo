"""OpenTelemetry tracing and instrumentation setup."""

import functools
import logging
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

F = TypeVar("F", bound=Callable[..., object])


def setup_tracing() -> None:
    """
    Set up OpenTelemetry tracing for the application.

    Instruments:
    - FastAPI (HTTP requests)
    - SQLAlchemy (database queries)

    Exports traces to OTLP endpoint (Tempo via Grafana Agent).
    """
    if not settings.enable_tracing:
        logger.info("Tracing disabled (ENABLE_TRACING=false)")
        return

    # Create resource with service information
    resource = Resource.create(
        attributes={
            "service.name": settings.otel_service_name,
            "service.version": "0.1.0",
            "deployment.environment": settings.otel_environment,
        }
    )

    # Set up tracer provider
    provider = TracerProvider(resource=resource)

    # Add OTLP exporter (sends to Tempo)
    try:
        otlp_exporter = OTLPSpanExporter(
            endpoint=settings.otel_exporter_otlp_endpoint,
            insecure=True,  # Use insecure for local development
        )
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        logger.info(f"OTLP exporter configured: {settings.otel_exporter_otlp_endpoint}")
    except Exception as e:
        logger.warning(f"Failed to configure OTLP exporter: {e}")
        logger.warning("Continuing without tracing export...")

    # Set global tracer provider
    trace.set_tracer_provider(provider)
    logger.info(f"OpenTelemetry tracer initialized: {settings.otel_service_name}")


def instrument_app(app, engine) -> None:
    """
    Instrument FastAPI app and SQLAlchemy engine.

    Args:
        app: FastAPI application instance
        engine: SQLAlchemy async engine
    """
    if not settings.enable_tracing:
        return

    # Instrument FastAPI
    try:
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumentation enabled")
    except Exception as e:
        logger.warning(f"FastAPI instrumentation failed: {e}")

    # Instrument SQLAlchemy
    try:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        logger.info("SQLAlchemy instrumentation enabled")
    except Exception as e:
        logger.warning(f"SQLAlchemy instrumentation failed: {e}")


# ---------------------------------------------------------------------------
# Spans for the pricing paths (task T122)
# ---------------------------------------------------------------------------
#
# The cost engine, the fee engine and the solver are the three places where a
# pricing screen spends its time, and the only ones where the time depends on
# the operator's own data: a product with a deep bill of materials costs more
# work than a flat one, and a ladder walks the whole margin chain once per
# rung. Without spans, a slow pricing screen is indistinguishable from a slow
# database.
#
# ## What these spans deliberately do not carry
#
# No monetary amounts, no product or tenant identifiers. A trace is shipped to
# an observability backend with a different retention and a different audience
# from the application's own data, and a span attribute carrying a margin is a
# tenant's commercial position leaving the system by a side door. The
# attributes below are shapes and counts -- how many lines, how many rungs,
# whether anything was incomplete -- which is what a latency question actually
# needs.


@contextmanager
def pricing_span(name: str, **attributes: object) -> Iterator[None]:
    """A span around one pricing computation, and a no-op when tracing is off.

    Safe to call from the synchronous engine: with no tracer provider
    configured OpenTelemetry hands back a non-recording tracer, so this costs a
    function call and nothing else.

    It never changes behaviour. An exception from the body propagates unchanged
    -- recorded on the span on its way out -- while a failure in the tracing
    machinery itself is swallowed and the body still runs. A cost calculation
    that failed because a span could not be started would be an observability
    tool breaking the thing it observes.
    """
    try:
        tracer = trace.get_tracer(__name__)
        started = tracer.start_as_current_span(name)
    except Exception as exc:  # noqa: BLE001 - tracing must not break pricing
        logger.debug(f"Could not start the span {name!r}: {exc}")
        yield
        return

    with started as current:
        try:
            if attributes and current.is_recording():
                for key, value in attributes.items():
                    if value is None:
                        continue
                    # Stringified where it is not a type OTLP accepts, so a
                    # Decimal count or an enum cannot drop the whole span.
                    if isinstance(value, (bool, int, float, str)):
                        current.set_attribute(f"pricing.{key}", value)
                    else:
                        current.set_attribute(f"pricing.{key}", str(value))
        except Exception as exc:  # noqa: BLE001 - as above
            logger.debug(f"Could not set attributes on the span {name!r}: {exc}")
        yield


def traced(name: str, **attributes: object) -> Callable[[F], F]:
    """Wrap one pricing function in a span, without touching its body.

    A decorator rather than a `with` block inside each function, so adding
    observability does not reindent the arithmetic -- a diff that moves every
    line of the cost engine is a diff nobody can review for correctness.

    On a recursive function (`product_breakdown` costing a bundle) each nested
    call opens a child span, which is the useful shape: the trace then shows
    how deep the bill of materials went and which child cost the time.
    """

    def decorate(fn: F) -> F:
        @functools.wraps(fn)
        def inner(*args: object, **kwargs: object) -> object:
            with pricing_span(name, **attributes):
                return fn(*args, **kwargs)

        return inner  # type: ignore[return-value]

    return decorate


__all__ = ["instrument_app", "pricing_span", "setup_tracing", "traced"]
