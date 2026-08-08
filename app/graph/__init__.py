"""LangGraph orchestration: state contracts, deterministic planning, workflow graph."""

from app.graph.constants import AgentName, Domain
from app.graph.planner import build_execution_plan
from app.graph.state import (
    AgentResult,
    ExecutionTask,
    GraphState,
    build_initial_state,
)

__all__ = [
    "AgentName",
    "AgentResult",
    "Domain",
    "ExecutionTask",
    "GraphState",
    "build_execution_plan",
    "build_initial_state",
    "build_workflow_graph",
]


def __getattr__(name: str):
    if name == "build_workflow_graph":
        from app.graph.workflow import build_workflow_graph

        return build_workflow_graph
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

