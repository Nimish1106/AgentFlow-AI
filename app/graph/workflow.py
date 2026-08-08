"""LangGraph workflow assembly (SRS §37).

Phase 6 completes the topology::

    START -> supervisor -> task_planner
          -> [billing | account | technical]   (parallel, plan-driven)
          -> policy -> results_aggregator -> risk_engine
          -> human_approval (only when risk demands it)
          -> response -> dispatcher -> END

The Aggregator, Risk Engine and Dispatcher are deterministic Python (no LLM, no
MCP). ``human_approval`` interrupts the run; ``POST /approvals/{workflow_id}``
resumes the same thread, keyed by ``workflow_id`` as ``thread_id`` (SRS §38).
"""

import logging
from typing import List, Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.account import make_account_agent_node
from app.agents.billing import make_billing_agent_node
from app.agents.policy import NODE_NAME as POLICY_NODE
from app.agents.policy import make_policy_agent_node
from app.agents.response import NODE_NAME as RESPONSE_NODE
from app.agents.response import make_response_agent_node
from app.agents.technical import make_technical_agent_node
from app.graph.constants import AgentName
from app.graph.instrumentation import traced_node
from app.graph.nodes.aggregator import NODE_NAME as AGGREGATOR_NODE
from app.graph.nodes.aggregator import aggregator_node
from app.graph.nodes.dispatcher import NODE_NAME as DISPATCHER_NODE
from app.graph.nodes.dispatcher import dispatcher_node
from app.graph.nodes.hitl import NODE_NAME as HITL_NODE
from app.graph.nodes.hitl import hitl_node
from app.graph.nodes.planner import NODE_NAME as PLANNER_NODE
from app.graph.nodes.planner import planner_node
from app.graph.nodes.risk_engine import NODE_NAME as RISK_NODE
from app.graph.nodes.risk_engine import risk_engine_node
from app.graph.nodes.supervisor import NODE_NAME as SUPERVISOR_NODE
from app.graph.nodes.supervisor import make_supervisor_node, supervisor_node
from app.graph.state import GraphState
from app.mcp.client import EnterpriseMCPClient

logger = logging.getLogger(__name__)

#: Domain agent node names in canonical order (matches the planner's output).
DOMAIN_AGENT_NODES: tuple[str, ...] = (
    AgentName.BILLING.value,
    AgentName.ACCOUNT.value,
    AgentName.TECHNICAL.value,
)


def route_after_supervisor(state: GraphState) -> Literal["task_planner", "__end__"]:
    """Stop the workflow when the Supervisor could not classify the ticket.

    SRS §35: a non-recoverable failure stops the workflow rather than letting the
    planner build a plan from a guessed intent.
    """
    if state.get("workflow_status") == "failed":
        return END
    return PLANNER_NODE


def route_after_planner(state: GraphState) -> List[str]:
    """Fan out to every domain agent the plan assigned (SRS §37).

    Domain tasks carry no dependencies, so all planned domain agents run in
    parallel. A plan with no domain tasks goes straight to the Policy Agent -
    policy and response alone are still a valid workflow.
    """
    planned = {
        task["assigned_agent"]
        for task in state.get("execution_plan", [])
        if task["assigned_agent"] in DOMAIN_AGENT_NODES
    }
    targets = [node for node in DOMAIN_AGENT_NODES if node in planned]
    return targets or [POLICY_NODE]


def route_after_policy(state: GraphState) -> Literal["results_aggregator", "__end__"]:
    """Stop before aggregating when the policy gate itself failed.

    A policy *rejection* (approved=False) still continues - the Risk Engine will
    route it to human review and the customer is told the request is under
    review. Only a failed evaluation (no verdict at all) ends the workflow
    (SRS §35).
    """
    if state.get("workflow_status") == "failed":
        return END
    return AGGREGATOR_NODE


def route_after_risk(state: GraphState) -> Literal["human_approval", "response_agent"]:
    """Send risky workflows to a human before any customer-facing reply (SRS §38)."""
    if state.get("requires_hitl"):
        return HITL_NODE
    return RESPONSE_NODE


def route_after_response(state: GraphState) -> Literal["dispatcher", "__end__"]:
    """Skip delivery when no response was produced (SRS §35)."""
    if state.get("workflow_status") == "failed":
        return END
    return DISPATCHER_NODE


def build_workflow_graph(
    *,
    llm: Optional[BaseChatModel] = None,
    mcp_client: Optional[EnterpriseMCPClient] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
):
    """Build and compile the workflow graph.

    Args:
        llm: Chat model shared by every reasoning node. Defaults to the
            configured Groq model, resolved lazily at invocation so the graph
            compiles without an API key.
        mcp_client: Enterprise MCP client used by the domain agents' ToolNodes.
            Defaults to the configured client, resolved lazily so the graph
            compiles without a running MCP server.
        checkpointer: Checkpoint backend. Defaults to an in-memory saver, which
            is enough for tests and single-process runs; the dispatcher passes
            the Postgres saver so interrupted workflows survive a restart
            (``app.graph.checkpointer.checkpointer_context``).

    Returns:
        The compiled graph, ready for ``ainvoke``.
    """
    graph = StateGraph(GraphState)

    # Every node goes through `add` so it is traced identically (SRS §42) and a
    # new node cannot be registered untraced by accident.
    def add(name: str, node_fn) -> None:
        graph.add_node(name, traced_node(name, node_fn))

    add(
        SUPERVISOR_NODE,
        make_supervisor_node(llm) if llm is not None else supervisor_node,
    )
    add(PLANNER_NODE, planner_node)
    add(
        AgentName.BILLING.value,
        make_billing_agent_node(llm=llm, mcp_client=mcp_client),
    )
    add(
        AgentName.ACCOUNT.value,
        make_account_agent_node(llm=llm, mcp_client=mcp_client),
    )
    add(
        AgentName.TECHNICAL.value,
        make_technical_agent_node(llm=llm, mcp_client=mcp_client),
    )
    add(POLICY_NODE, make_policy_agent_node(llm=llm))
    add(AGGREGATOR_NODE, aggregator_node)
    add(RISK_NODE, risk_engine_node)
    add(HITL_NODE, hitl_node)
    add(RESPONSE_NODE, make_response_agent_node(llm=llm))
    add(DISPATCHER_NODE, dispatcher_node)

    graph.add_edge(START, SUPERVISOR_NODE)
    graph.add_conditional_edges(
        SUPERVISOR_NODE,
        route_after_supervisor,
        {PLANNER_NODE: PLANNER_NODE, END: END},
    )
    graph.add_conditional_edges(
        PLANNER_NODE,
        route_after_planner,
        [*DOMAIN_AGENT_NODES, POLICY_NODE],
    )
    for node in DOMAIN_AGENT_NODES:
        graph.add_edge(node, POLICY_NODE)
    graph.add_conditional_edges(
        POLICY_NODE,
        route_after_policy,
        {AGGREGATOR_NODE: AGGREGATOR_NODE, END: END},
    )
    graph.add_edge(AGGREGATOR_NODE, RISK_NODE)
    graph.add_conditional_edges(
        RISK_NODE,
        route_after_risk,
        {HITL_NODE: HITL_NODE, RESPONSE_NODE: RESPONSE_NODE},
    )
    graph.add_edge(HITL_NODE, RESPONSE_NODE)
    graph.add_conditional_edges(
        RESPONSE_NODE,
        route_after_response,
        {DISPATCHER_NODE: DISPATCHER_NODE, END: END},
    )
    graph.add_edge(DISPATCHER_NODE, END)

    # Checkpoint after every node (SRS §46) so a run is resumable.
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


#: Top-level compiled graph instance for LangGraph Studio / LangGraph CLI.
graph = build_workflow_graph()


