"""Tracing wrapper applied to LangGraph nodes at graph-assembly time (SRS §42).

Wrapping nodes here rather than decorating each one keeps the instrumentation in
a single place: every node the graph registers is traced identically, and a new
node cannot be added untraced by accident.

Each span carries the SRS §42 / §46 observability contract as attributes:
``workflow_id``, ``node``, ``execution_time_ms``, ``tool_calls``, ``confidence``,
``retry_count``, and any errors the node reported.

A node's own return value is the only source of these attributes, so this
wrapper never inspects databases, LLMs or MCP - it observes, it does not act.
"""

import logging
import time
from typing import Any, Awaitable, Callable, Dict

from app.graph.state import GraphState
from app.observability import tracing

logger = logging.getLogger(__name__)

NodeFn = Callable[[GraphState], Awaitable[Dict]]


def traced_node(node_name: str, node_fn: NodeFn) -> NodeFn:
    """Wrap a node coroutine so each execution emits one span.

    The wrapper is transparent: it returns the node's update unchanged and
    re-raises whatever the node raised. ``GraphInterrupt`` from the HITL node is
    control flow rather than failure (SRS §38), so it is recorded as a normal
    span outcome - marking it an error would make every human approval look like
    a fault in the trace.
    """

    async def instrumented(state: GraphState) -> Dict:
        workflow_id = state.get("workflow_id", "")
        started = time.perf_counter()

        with tracing.node_span(
            node_name,
            workflow_id,
            retry_count=state.get("retry_count", 0),
            customer_tier=state.get("customer_tier"),
        ) as span:
            try:
                update = await node_fn(state)
            except Exception:
                # `span()` records the exception and sets ERROR status, except
                # for LangGraph interrupts, which it correctly treats as
                # control flow. Only the timing needs adding here.
                tracing.set_span_attributes(
                    span, execution_time_ms=_elapsed_ms(started)
                )
                raise

            tracing.set_span_attributes(span, **_attributes_from(update, started))
            if update.get("errors"):
                tracing.record_error(span, "; ".join(str(e) for e in update["errors"]))
            return update

    # Keep the wrapped function recognisable in tracebacks and LangGraph errors.
    instrumented.__name__ = f"traced_{node_name}"
    instrumented.__qualname__ = instrumented.__name__
    return instrumented


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _attributes_from(update: Dict, started: float) -> Dict[str, Any]:
    """Derive span attributes from a node's state update.

    Prefers the node's own ``node_executions`` entry, which already carries the
    node's measured duration, tool calls and confidence, and falls back to the
    wrapper's own timing when a node reports no trace entry.

    Keys are returned already namespaced, matching what lands on a span.
    """
    attributes: Dict[str, Any] = {
        "agentflow.execution_time_ms": _elapsed_ms(started)
    }

    executions = update.get("node_executions") or []
    entry = executions[0] if executions else None
    if isinstance(entry, dict):
        if entry.get("execution_time_ms") is not None:
            attributes["agentflow.execution_time_ms"] = entry["execution_time_ms"]
        attributes["agentflow.status"] = entry.get("status")
        attributes["agentflow.tool_calls"] = len(entry.get("tool_calls") or [])
        if entry.get("confidence") is not None:
            attributes["agentflow.confidence"] = entry["confidence"]

    if update.get("workflow_status"):
        attributes["agentflow.workflow_status"] = update["workflow_status"]
    if update.get("requires_hitl") is not None:
        attributes["agentflow.requires_hitl"] = update["requires_hitl"]
    if update.get("risk_score") is not None:
        attributes["agentflow.risk_score"] = update["risk_score"]
    return attributes
