"""Base LangGraph workflow assembly (SRS §37).

Phase 2 wires the deterministic front half of the graph::

    START -> supervisor -> task_planner -> END

Later phases insert the domain agents, Results Aggregator, Risk Engine, HITL,
Response Agent and Dispatcher between the planner and END.
"""

import logging
from typing import Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.graph.nodes.planner import NODE_NAME as PLANNER_NODE
from app.graph.nodes.planner import planner_node
from app.graph.nodes.supervisor import NODE_NAME as SUPERVISOR_NODE
from app.graph.nodes.supervisor import make_supervisor_node, supervisor_node
from app.graph.state import GraphState

logger = logging.getLogger(__name__)


def route_after_supervisor(state: GraphState) -> Literal["task_planner", "__end__"]:
    """Stop the workflow when the Supervisor could not classify the ticket.

    SRS §35: a non-recoverable failure stops the workflow rather than letting the
    planner build a plan from a guessed intent.
    """
    if state.get("workflow_status") == "failed":
        return END
    return PLANNER_NODE


def build_workflow_graph(
    *,
    llm: Optional[BaseChatModel] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
):
    """Build and compile the workflow graph.

    Args:
        llm: Chat model for the Supervisor. Defaults to the configured Groq model,
            resolved lazily at invocation so the graph compiles without an API key.
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

    graph.add_edge(START, SUPERVISOR_NODE)
    graph.add_conditional_edges(
        SUPERVISOR_NODE,
        route_after_supervisor,
        {PLANNER_NODE: PLANNER_NODE, END: END},
    )
    graph.add_edge(PLANNER_NODE, END)

    # Checkpoint after every node (SRS §46) so a run is resumable.
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
