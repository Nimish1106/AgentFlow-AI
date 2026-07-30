"""LangGraph workflow assembly (SRS §37).

Phase 4 wires the full agent pipeline::

    START -> supervisor -> task_planner
          -> [billing | account | technical]   (parallel, plan-driven)
          -> policy -> response -> END

The Results Aggregator, Risk Engine, HITL interrupt and Dispatcher nodes are
Phase 6; until then the Policy Agent's verdict and risk land in GraphState and
the Response Agent always runs after policy succeeds.
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
from app.graph.nodes.planner import NODE_NAME as PLANNER_NODE
from app.graph.nodes.planner import planner_node
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


def route_after_policy(state: GraphState) -> Literal["response_agent", "__end__"]:
    """Stop before drafting a reply when the policy gate itself failed.

    A policy *rejection* (approved=False) still reaches the Response Agent -
    the customer is told the request is under review. Only a failed evaluation
    (no verdict at all) ends the workflow (SRS §35).
    """
    if state.get("workflow_status") == "failed":
        return END
    return RESPONSE_NODE


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
        checkpointer: Checkpoint backend. Defaults to an in-memory saver; the
            Postgres-backed saver arrives with workflow resume in Phase 6.

    Returns:
        The compiled graph, ready for ``ainvoke``.
    """
    graph = StateGraph(GraphState)

    graph.add_node(
        SUPERVISOR_NODE,
        make_supervisor_node(llm) if llm is not None else supervisor_node,
    )
    graph.add_node(PLANNER_NODE, planner_node)
    graph.add_node(
        AgentName.BILLING.value,
        make_billing_agent_node(llm=llm, mcp_client=mcp_client),
    )
    graph.add_node(
        AgentName.ACCOUNT.value,
        make_account_agent_node(llm=llm, mcp_client=mcp_client),
    )
    graph.add_node(
        AgentName.TECHNICAL.value,
        make_technical_agent_node(llm=llm, mcp_client=mcp_client),
    )
    graph.add_node(POLICY_NODE, make_policy_agent_node(llm=llm))
    graph.add_node(RESPONSE_NODE, make_response_agent_node(llm=llm))

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
        {RESPONSE_NODE: RESPONSE_NODE, END: END},
    )
    graph.add_edge(RESPONSE_NODE, END)

    # Checkpoint after every node (SRS §46) so a run is resumable.
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
