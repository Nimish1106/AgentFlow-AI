"""OpenTelemetry tracing (SRS §42).

What is traced
--------------
Three layers, matching the three tiers of the architecture:

- **FastAPI requests** - instrumented automatically at app startup.
- **LangGraph nodes** - one span per node, carrying ``workflow_id``,
  ``node_name``, execution time, tool-call count, confidence and retry count
  (the SRS §42 / §46 logging contract, as span attributes).
- **MCP tool calls** - one span per tool invocation with its outcome code.

Design constraints
------------------
**Tracing is optional and off by default.** ``configure_tracing()`` is the only
place the SDK is touched; when ``otel_enabled`` is false every helper degrades
to a no-op context manager. This matters because the unit suite, the local venv
and any offline run must work with no collector listening - an observability
layer that makes the system fail closed when the collector is down would be
worse than no observability at all.

**Never crash the caller.** Span helpers swallow their own errors. A workflow
must not fail because a span could not be recorded.

**Never record customer data** (SRS §43). Attributes are ids, durations, counts
and status codes. Ticket text, customer names, invoice amounts and LLM output
never become span attributes.

Exporting
---------
``OTEL_EXPORTER_OTLP_ENDPOINT`` sends spans to any OTLP/HTTP collector (Jaeger,
Tempo, Honeycomb). With tracing enabled and no endpoint set, spans go to the
console exporter, which is enough to see the trace tree in ``docker compose
logs`` without running a collector.
"""

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

#: Instrumentation scope name for every span this application emits.
TRACER_NAME = "agentflow"

#: Set once by configure_tracing(); None means tracing is disabled.
_tracer: Optional[Any] = None
_configured = False


def configure_tracing(app: Optional[Any] = None) -> None:
    """Initialise the tracer provider and instrument FastAPI if given.

    Safe to call from any process (API, dispatcher, MCP server) and safe to
    call more than once - the second call is ignored. Any failure to set up
    tracing is logged and swallowed: the application still runs, untraced.
    """
    global _tracer, _configured
    if _configured:
        return
    _configured = True

    settings = get_settings()
    if not settings.otel_enabled:
        logger.debug("tracing disabled (OTEL_ENABLED=false)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )

        resource = Resource.create(
            {
                "service.name": settings.otel_service_name,
                "service.version": settings.app_version,
                "deployment.environment": settings.environment,
            }
        )
        provider = TracerProvider(resource=resource)

        endpoint = settings.otel_exporter_otlp_endpoint.strip()
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            # Batched: an exporter that blocks the request path would turn a
            # collector outage into application latency.
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
            )
            logger.info("tracing enabled, exporting to %s", endpoint)
        else:
            # No collector configured: print spans so the trace tree is still
            # visible in container logs.
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
            logger.info("tracing enabled, exporting to console")

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(TRACER_NAME)
    except Exception:  # noqa: BLE001 - observability must never break startup
        logger.exception("tracing setup failed; continuing without tracing")
        _tracer = None
        return

    if app is not None:
        instrument_fastapi(app)


def instrument_fastapi(app: Any) -> None:
    """Attach the FastAPI instrumentor, if tracing is active."""
    if _tracer is None:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # /health is polled by Docker's healthcheck every few seconds; tracing
        # it would bury real request spans in noise.
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    except Exception:  # noqa: BLE001
        logger.exception("FastAPI instrumentation failed; continuing untraced")


def is_enabled() -> bool:
    """True when spans are actually being recorded."""
    return _tracer is not None


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Optional[Any]]:
    """Record one span, or do nothing when tracing is disabled.

    Yields the span so a caller can add attributes discovered mid-execution
    (via ``set_span_attributes``), or None when tracing is off.

    An exception raised inside the block is recorded on the span and
    re-raised - tracing observes failures, it never suppresses them.
    """
    if _tracer is None:
        yield None
        return

    # Start the span outside the yield path. If the tracer itself is broken we
    # fall back to an untraced block rather than failing the caller - and we
    # must not end up on a code path that could yield twice.
    manager = None
    active_span = None
    try:
        manager = _tracer.start_as_current_span(name)
        active_span = manager.__enter__()
        # Prefix here so a direct span() call and a node_span()/tool_span() call
        # produce identically-named attributes.
        _apply_attributes(active_span, _prefixed(attributes))
    except Exception:  # noqa: BLE001 - tracing must never break the caller
        logger.debug("could not start span %s", name, exc_info=True)
        manager = None
        active_span = None

    try:
        yield active_span
    except Exception as exc:
        # A LangGraph interrupt is control flow (a workflow pausing for human
        # approval, SRS §38), not a failure. Recording it as an error would
        # make every HITL approval show up as a fault in the trace - so the
        # span is closed as if it succeeded and the exception still propagates.
        control_flow = _is_control_flow(exc)
        if active_span is not None and not control_flow:
            _record_exception(active_span, exc)
        if manager is not None:
            # OTel's own __exit__ sets ERROR status when handed an exception,
            # so an interrupt must be closed with a clean exit.
            _exit_quietly(manager, None if control_flow else exc)
            manager = None
        raise
    finally:
        if manager is not None:
            _exit_quietly(manager, None)


@contextmanager
def node_span(node_name: str, workflow_id: str, **attributes: Any) -> Iterator[Optional[Any]]:
    """Span for one LangGraph node execution (SRS §42)."""
    with span(
        f"node.{node_name}",
        **{
            "agentflow.workflow_id": workflow_id,
            "agentflow.node": node_name,
            **_prefixed(attributes),
        },
    ) as active_span:
        yield active_span


@contextmanager
def tool_span(tool_name: str, workflow_id: Optional[str] = None) -> Iterator[Optional[Any]]:
    """Span for one Enterprise MCP tool call (SRS §42)."""
    attributes: Dict[str, Any] = {"agentflow.tool": tool_name}
    if workflow_id:
        attributes["agentflow.workflow_id"] = workflow_id
    with span(f"mcp.{tool_name}", **attributes) as active_span:
        yield active_span


def set_span_attributes(active_span: Optional[Any], **attributes: Any) -> None:
    """Add attributes to a span returned by one of the helpers above.

    Accepts None so callers never need to branch on whether tracing is on.
    """
    if active_span is None:
        return
    _apply_attributes(active_span, _prefixed(attributes))


def record_error(active_span: Optional[Any], error: BaseException | str) -> None:
    """Mark a span as failed. Accepts None, and never raises."""
    if active_span is None:
        return
    if isinstance(active_span, BaseException):  # defensive: argument order slip
        return
    if isinstance(error, BaseException):
        _record_exception(active_span, error)
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        active_span.set_status(Status(StatusCode.ERROR, str(error)))
    except Exception:  # noqa: BLE001
        logger.debug("could not record error on span", exc_info=True)


def _prefixed(attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Namespace bare attribute keys under ``agentflow.``."""
    return {
        key if "." in key else f"agentflow.{key}": value
        for key, value in attributes.items()
    }


def _apply_attributes(active_span: Any, attributes: Dict[str, Any]) -> None:
    """Set attributes defensively; OTel rejects None and arbitrary objects."""
    try:
        for key, value in attributes.items():
            if value is None:
                continue
            if isinstance(value, (str, bool, int, float)):
                active_span.set_attribute(key, value)
            else:
                active_span.set_attribute(key, str(value))
    except Exception:  # noqa: BLE001 - attributes are never worth a crash
        logger.debug("could not set span attributes", exc_info=True)


def _record_exception(active_span: Any, exc: BaseException) -> None:
    """Attach an exception and an ERROR status to a span."""
    try:
        from opentelemetry.trace import Status, StatusCode

        active_span.record_exception(exc)
        active_span.set_status(Status(StatusCode.ERROR, str(exc)))
    except Exception:  # noqa: BLE001
        logger.debug("could not record exception on span", exc_info=True)


def _is_control_flow(exc: BaseException) -> bool:
    """True for LangGraph's interrupt/bubble-up signals, which are not errors."""
    try:
        from langgraph.errors import GraphBubbleUp

        return isinstance(exc, GraphBubbleUp)
    except Exception:  # noqa: BLE001 - a probe must never break tracing
        return exc.__class__.__name__ in {"GraphInterrupt", "GraphBubbleUp"}


def _exit_quietly(manager: Any, exc: Optional[BaseException]) -> None:
    """Close a span context manager without letting its errors escape."""
    try:
        if exc is None:
            manager.__exit__(None, None, None)
        else:
            manager.__exit__(type(exc), exc, exc.__traceback__)
    except Exception:  # noqa: BLE001
        logger.debug("could not close span", exc_info=True)


def reset_for_testing() -> None:
    """Reset module state so a test can configure tracing again."""
    global _tracer, _configured
    _tracer = None
    _configured = False
