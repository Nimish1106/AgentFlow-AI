"""LangGraph state contracts: GraphState, ExecutionTask, AgentResult (SRS §21-§23).

GraphState is the single source of truth during workflow execution. Nodes read it
and return a *state update dictionary* - they never mutate it in place (SRS §46).

Fields that concurrent branches write must carry a reducer, otherwise the last
branch to finish clobbers the others. `agent_results` and `errors` use
``operator.add`` so parallel agents append; `messages` uses LangGraph's
``add_messages``.
"""

import operator
from typing import Annotated, Dict, List, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

TaskStatus = Literal["pending", "running", "completed", "failed", "skipped"]
TaskPriority = Literal["low", "medium", "high"]
AgentStatus = Literal["success", "failed", "skipped"]


def merge_dicts(left: Dict, right: Dict) -> Dict:
    """Reducer for ``shared_context``: later writes win key-by-key.

    Parallel domain agents each write a namespaced key (``billing_agent``,
    ``account_agent`` ...) so concurrent merges never collide.
    """
    return {**left, **right}


class ExecutionTask(TypedDict):
    """One unit of work in the execution plan (SRS §22).

    Produced by the deterministic Task Planner, never by an LLM.
    """

    task_id: str
    task_name: str
    assigned_agent: str
    priority: TaskPriority
    depends_on: List[str]
    status: TaskStatus


class AgentResult(TypedDict):
    """Uniform result contract returned by every agent (SRS §23).

    The Results Aggregator relies on this shape being identical across agents.
    """

    agent_name: str
    status: AgentStatus
    summary: str
    confidence: float
    actions_taken: List[str]
    tool_calls: List[str]
    output_data: Dict


class NodeExecution(TypedDict):
    """One node's execution record, for the operations timeline (SRS §18.6).

    Every node - reasoning agent *and* deterministic governance node - appends
    exactly one of these, so the ordered list is the workflow's execution trace.
    ``AgentResult`` cannot serve this purpose: it is a fixed SRS §23 contract
    that only the reasoning agents produce, and it carries no timing.

    The dispatcher persists these as ``agent_execution_logs`` rows, which is
    what ``GET /workflows/{id}/trace`` serves to the dashboard. ``confidence``
    is None for deterministic nodes - they do not reason, so they have no
    confidence to report.
    """

    node: str
    status: AgentStatus
    execution_time_ms: float
    tool_calls: List[str]
    confidence: Optional[float]
    summary: str


class GraphState(TypedDict):
    """Single source of truth for a workflow run (SRS §21)."""

    workflow_id: str
    ticket_id: str
    customer_id: str
    issue_text: str
    customer_tier: str
    ticket_priority: str

    execution_plan: List[ExecutionTask]
    # Reducers on the fields below: parallel domain agents all write them in the
    # same superstep, and LangGraph rejects concurrent writes to unreduced keys.
    completed_agents: Annotated[List[str], operator.add]
    current_node: str
    shared_context: Annotated[Dict, merge_dicts]

    messages: Annotated[List[BaseMessage], add_messages]
    tool_history: Annotated[List[str], operator.add]

    risk_score: float
    requires_hitl: bool
    approval_status: Optional[str]
    workflow_status: str
    retry_count: int

    final_response: Optional[str]

    # Reducers: parallel agent branches append instead of overwriting (SRS §21).
    agent_results: Annotated[List[AgentResult], operator.add]
    errors: Annotated[List[str], operator.add]
    #: Ordered execution trace, one entry per node. Reduced because parallel
    #: domain agents all append in the same superstep.
    node_executions: Annotated[List[NodeExecution], operator.add]


def build_initial_state(
    *,
    workflow_id: str,
    ticket_id: str,
    customer_id: str,
    issue_text: str,
    customer_tier: str = "basic",
    ticket_priority: str = "medium",
) -> GraphState:
    """Build a fully-populated GraphState for a new workflow run.

    Every key is set explicitly so nodes can read any field without a KeyError;
    TypedDict gives no runtime defaults.
    """
    return GraphState(
        workflow_id=workflow_id,
        ticket_id=ticket_id,
        customer_id=customer_id,
        issue_text=issue_text,
        customer_tier=customer_tier,
        ticket_priority=ticket_priority,
        execution_plan=[],
        completed_agents=[],
        current_node="",
        shared_context={},
        messages=[],
        tool_history=[],
        risk_score=0.0,
        requires_hitl=False,
        approval_status=None,
        workflow_status="pending",
        retry_count=0,
        final_response=None,
        agent_results=[],
        errors=[],
        node_executions=[],
    )


def build_node_execution(
    *,
    node: str,
    status: AgentStatus,
    execution_time_ms: float,
    summary: str,
    tool_calls: Optional[List[str]] = None,
    confidence: Optional[float] = None,
) -> NodeExecution:
    """Build one execution-trace entry (SRS §18.6 agent_execution_logs)."""
    return NodeExecution(
        node=node,
        status=status,
        execution_time_ms=round(execution_time_ms, 1),
        tool_calls=list(tool_calls or []),
        confidence=confidence,
        summary=summary,
    )
