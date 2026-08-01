"""Task Planner node: wrap the deterministic planner as a LangGraph node.

The planning logic itself lives in ``app.graph.planner`` and stays free of
LangGraph types so it can be tested as plain Python (SRS §30.2).
"""

import logging
import time
from typing import Dict

from app.graph.planner import build_execution_plan
from app.graph.state import GraphState, build_node_execution

logger = logging.getLogger(__name__)

NODE_NAME = "task_planner"


async def planner_node(state: GraphState) -> Dict:
    """Build the execution plan from the Supervisor's classification."""
    started = time.perf_counter()
    shared_context = state.get("shared_context", {})

    plan = build_execution_plan(
        {
            "domains": shared_context.get("domains", []),
            "priority": shared_context.get("priority", state.get("ticket_priority")),
        }
    )

    agents = [task["assigned_agent"] for task in plan]
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "workflow_id=%s node=%s tasks=%s agents=%s execution_time_ms=%.1f",
        state.get("workflow_id"),
        NODE_NAME,
        len(plan),
        agents,
        elapsed_ms,
    )

    return {
        "current_node": NODE_NAME,
        "execution_plan": plan,
        "node_executions": [
            build_node_execution(
                node=NODE_NAME,
                status="success",
                execution_time_ms=elapsed_ms,
                summary=(
                    f"Planned {len(plan)} task(s) for {agents or ['no domain agents']}"
                ),
            )
        ],
    }
