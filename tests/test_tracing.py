"""Tests for OpenTelemetry tracing (SRS §42).

The disabled path is the default everywhere, so the enabled path needs
deliberate coverage: a tracing layer that silently records nothing would pass
every other test in the suite.

Spans are captured with the SDK's ``InMemorySpanExporter`` rather than a mock,
so these assert against real span objects.
"""

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from app.observability import tracing


@pytest.fixture
def spans():
    """Capture spans in memory with tracing forced on."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    tracing.reset_for_testing()
    tracing._tracer = provider.get_tracer("test")
    tracing._configured = True
    yield exporter
    tracing.reset_for_testing()


@pytest.fixture
def tracing_disabled():
    """Guarantee the disabled state regardless of test ordering."""
    tracing.reset_for_testing()
    yield
    tracing.reset_for_testing()


class TestDisabledByDefault:
    def test_helpers_are_no_ops_when_disabled(self, tracing_disabled):
        """The unit suite and offline runs must need no collector."""
        assert tracing.is_enabled() is False
        with tracing.span("anything") as span:
            assert span is None
        with tracing.node_span("supervisor", "wf-1") as span:
            assert span is None
        with tracing.tool_span("billing_get_invoice") as span:
            assert span is None

    def test_attribute_helpers_accept_none(self, tracing_disabled):
        """Callers never branch on whether tracing is on."""
        tracing.set_span_attributes(None, anything="value")
        tracing.record_error(None, "boom")

    def test_configure_is_a_no_op_when_setting_is_false(self, tracing_disabled):
        tracing.configure_tracing()
        assert tracing.is_enabled() is False

    def test_exceptions_still_propagate_when_disabled(self, tracing_disabled):
        with pytest.raises(ValueError, match="boom"):
            with tracing.span("anything"):
                raise ValueError("boom")


class TestSpanRecording:
    def test_records_a_span_with_attributes(self, spans):
        with tracing.span("test.operation", workflow_id="wf-1", count=3):
            pass

        [span] = spans.get_finished_spans()
        assert span.name == "test.operation"
        assert span.attributes["agentflow.workflow_id"] == "wf-1"
        assert span.attributes["agentflow.count"] == 3

    def test_node_span_carries_the_observability_contract(self, spans):
        """SRS §42: workflow_id, node, execution time, tool calls, retries."""
        with tracing.node_span("billing_agent", "wf-7", retry_count=2) as span:
            tracing.set_span_attributes(
                span, execution_time_ms=3177.0, tool_calls=4, confidence=0.7
            )

        [span] = spans.get_finished_spans()
        assert span.name == "node.billing_agent"
        assert span.attributes["agentflow.workflow_id"] == "wf-7"
        assert span.attributes["agentflow.node"] == "billing_agent"
        assert span.attributes["agentflow.retry_count"] == 2
        assert span.attributes["agentflow.execution_time_ms"] == 3177.0
        assert span.attributes["agentflow.tool_calls"] == 4
        assert span.attributes["agentflow.confidence"] == 0.7

    def test_tool_span_names_the_mcp_tool(self, spans):
        with tracing.tool_span("billing_get_invoice", "wf-9") as span:
            tracing.set_span_attributes(span, outcome="success")

        [span] = spans.get_finished_spans()
        assert span.name == "mcp.billing_get_invoice"
        assert span.attributes["agentflow.tool"] == "billing_get_invoice"
        assert span.attributes["agentflow.outcome"] == "success"

    def test_nested_spans_form_a_tree(self, spans):
        """A tool call inside a node must be a child of that node's span."""
        with tracing.node_span("billing_agent", "wf-1"):
            with tracing.tool_span("billing_get_invoice", "wf-1"):
                pass

        finished = {s.name: s for s in spans.get_finished_spans()}
        tool_span = finished["mcp.billing_get_invoice"]
        node_span = finished["node.billing_agent"]
        assert tool_span.parent.span_id == node_span.context.span_id

    def test_records_an_exception_and_re_raises(self, spans):
        with pytest.raises(RuntimeError, match="mcp down"):
            with tracing.span("node.billing_agent"):
                raise RuntimeError("mcp down")

        [span] = spans.get_finished_spans()
        assert span.status.status_code is trace.StatusCode.ERROR
        assert any(event.name == "exception" for event in span.events)

    def test_an_interrupt_is_not_recorded_as_an_error(self, spans):
        """SRS §38: a HITL pause is control flow, not a fault."""
        from langgraph.errors import GraphInterrupt

        with pytest.raises(GraphInterrupt):
            with tracing.span("node.human_approval"):
                raise GraphInterrupt(())

        [span] = spans.get_finished_spans()
        assert span.status.status_code is not trace.StatusCode.ERROR

    def test_record_error_accepts_a_string(self, spans):
        with tracing.span("node.policy_agent") as span:
            tracing.record_error(span, "policy evaluation failed")

        [span] = spans.get_finished_spans()
        assert span.status.status_code is trace.StatusCode.ERROR

    def test_non_primitive_attributes_are_stringified(self, spans):
        """OTel rejects arbitrary objects; they must not raise."""
        with tracing.span("test", payload={"a": 1}, items=[1, 2]):
            pass

        [span] = spans.get_finished_spans()
        assert isinstance(span.attributes["agentflow.payload"], str)

    def test_none_attributes_are_dropped(self, spans):
        with tracing.span("test", present="yes", absent=None):
            pass

        [span] = spans.get_finished_spans()
        assert "agentflow.absent" not in span.attributes
        assert span.attributes["agentflow.present"] == "yes"


class TestNeverBreaksTheCaller:
    def test_a_broken_tracer_does_not_break_the_block(self, tracing_disabled):
        """An observability failure must never take the workflow with it."""

        class ExplodingTracer:
            def start_as_current_span(self, name):
                raise RuntimeError("tracer exploded")

        tracing._tracer = ExplodingTracer()
        tracing._configured = True

        executed = False
        with tracing.span("node.supervisor") as span:
            executed = True
            assert span is None
        assert executed is True

    def test_a_broken_tracer_still_propagates_real_errors(self, tracing_disabled):
        class ExplodingTracer:
            def start_as_current_span(self, name):
                raise RuntimeError("tracer exploded")

        tracing._tracer = ExplodingTracer()
        tracing._configured = True

        with pytest.raises(ValueError, match="real failure"):
            with tracing.span("node.supervisor"):
                raise ValueError("real failure")

    def test_configure_survives_a_broken_sdk(self, tracing_disabled, monkeypatch):
        """A tracing setup failure must not stop the process booting."""
        from app.config.settings import Settings

        monkeypatch.setattr(
            tracing, "get_settings", lambda: Settings(otel_enabled=True)
        )

        import builtins

        real_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name.startswith("opentelemetry"):
                raise ImportError("no opentelemetry here")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", failing_import)

        tracing.configure_tracing()  # must not raise
        assert tracing.is_enabled() is False

    def test_configure_is_idempotent(self, tracing_disabled):
        tracing.configure_tracing()
        tracing.configure_tracing()
        assert tracing.is_enabled() is False


class TestNoCustomerDataLeaks:
    def test_node_spans_carry_ids_and_metrics_only(self, spans):
        """SRS §43: telemetry leaves the process, so it must not carry PII.

        Guards the attribute-building path in the graph wrapper, which is what
        decides what actually reaches a collector.
        """
        from app.graph.instrumentation import _attributes_from

        update = {
            "workflow_status": "completed",
            "risk_score": 0.9,
            "final_response": "Dear Paul Carr, your 49 USD refund is approved.",
            "node_executions": [
                {
                    "node": "billing_agent",
                    "status": "success",
                    "execution_time_ms": 3177.0,
                    "tool_calls": ["billing_get_invoice"],
                    "confidence": 0.7,
                    "summary": "Customer Paul Carr was charged twice for 49 USD.",
                }
            ],
        }
        attributes = _attributes_from(update, 0.0)

        serialised = " ".join(f"{k}={v}" for k, v in attributes.items())
        assert "Paul Carr" not in serialised
        assert "49 USD" not in serialised
        # The metrics the SRS does ask for are present.
        assert attributes["agentflow.execution_time_ms"] == 3177.0
        assert attributes["agentflow.tool_calls"] == 1
        assert attributes["agentflow.confidence"] == 0.7
