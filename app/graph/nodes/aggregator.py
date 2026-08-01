"""Results Aggregator node (SRS §40, §14).

Deterministic Python - no LLM, no MCP. It merges the AgentResults produced by
the domain agents and the Policy Agent into one consolidated view the Risk
Engine can score:

- de-duplicate results (a retried agent may append twice; the last one wins)
- separate successes from failures
- detect conflicting recommendations, resolving them in favour of the Policy
  Agent and recording the conflict for the audit trail (SRS §40)
- publish the merged facts into ``shared_context`` for downstream nodes

The aggregator runs alone in its superstep (the domain agents have joined by
then), so it may write unreduced keys such as ``current_node``.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

from app.graph.constants import AgentName
from app.graph.state import AgentResult, GraphState, build_node_execution

logger = logging.getLogger(__name__)

NODE_NAME = "results_aggregator"

#: shared_context key holding the aggregated view.
CONTEXT_KEY = "aggregation"

#: output_data keys whose truthiness means "this agent recommends acting".
_RECOMMENDATION_KEYS: Tuple[str, ...] = (
    "refund_eligible",
    "eligible",
    "action_recommended",
)


def deduplicate_results(results: List[AgentResult]) -> List[AgentResult]:
    """Collapse repeated results per agent, keeping the most recent (SRS §40).

    Order is preserved by first appearance so the merged view reads in
    execution order even when an agent was retried.
    """
    latest: Dict[str, AgentResult] = {}
    order: List[str] = []
    for result in results:
        name = result.get("agent_name", "unknown")
        if name not in latest:
            order.append(name)
        latest[name] = result
    return [latest[name] for name in order]


def _policy_result(results: List[AgentResult]) -> Optional[AgentResult]:
    """Return the Policy Agent's result, if it ran."""
    for result in results:
        if result.get("agent_name") == AgentName.POLICY.value:
            return result
    return None


def _recommends_action(result: AgentResult) -> Optional[bool]:
    """Read an agent's recommendation from its output_data, if it made one."""
    output = result.get("output_data") or {}
    for key in _RECOMMENDATION_KEYS:
        if key in output:
            return bool(output[key])
    return None


def detect_conflicts(results: List[AgentResult]) -> List[str]:
    """Describe disagreements between domain agents and the Policy Agent.

    A conflict is a domain agent recommending an action the Policy Agent did
    not approve (or vice versa). The Policy verdict wins (SRS §40); this
    function only records what disagreed so the caller can audit it.
    """
    policy = _policy_result(results)
    if policy is None or policy.get("status") != "success":
        return []
    approved = policy.get("output_data", {}).get("approved")
    if approved is None:
        return []

    conflicts: List[str] = []
    for result in results:
        if result.get("agent_name") == AgentName.POLICY.value:
            continue
        if result.get("status") != "success":
            continue
        recommendation = _recommends_action(result)
        if recommendation is None or recommendation == bool(approved):
            continue
        conflicts.append(
            f"{result['agent_name']} recommended action={recommendation} but "
            f"policy_agent approved={bool(approved)}; policy_agent wins"
        )
    return conflicts


def merge_output_data(results: List[AgentResult]) -> Dict:
    """Merge successful agents' output_data under their agent names.

    Namespacing avoids two agents fighting over the same key, and keeps the
    provenance of every fact obvious to the Risk Engine and Response Agent.
    """
    return {
        result["agent_name"]: result.get("output_data") or {}
        for result in results
        if result.get("status") == "success"
    }


async def aggregator_node(state: GraphState) -> Dict:
    """Merge AgentResults into a consolidated workflow view (SRS §40)."""
    started = time.perf_counter()
    workflow_id = state.get("workflow_id", "")

    merged = deduplicate_results(list(state.get("agent_results", [])))
    successful = [r for r in merged if r.get("status") == "success"]
    failed = [r for r in merged if r.get("status") == "failed"]
    conflicts = detect_conflicts(merged)

    aggregation = {
        "agent_count": len(merged),
        "successful_agents": [r["agent_name"] for r in successful],
        "failed_agents": [r["agent_name"] for r in failed],
        "conflicts": conflicts,
        "confidences": {
            r["agent_name"]: r.get("confidence", 0.0) for r in successful
        },
        "findings": merge_output_data(successful),
    }

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "workflow_id=%s node=%s agents=%s failed=%s conflicts=%s "
        "execution_time_ms=%.1f retry_count=%s",
        workflow_id,
        NODE_NAME,
        aggregation["successful_agents"],
        aggregation["failed_agents"],
        len(conflicts),
        elapsed_ms,
        state.get("retry_count", 0),
    )

    return {
        "current_node": NODE_NAME,
        "shared_context": {CONTEXT_KEY: aggregation},
        "node_executions": [
            build_node_execution(
                node=NODE_NAME,
                status="success",
                execution_time_ms=elapsed_ms,
                summary=(
                    f"Merged {len(merged)} agent result(s); "
                    f"{len(failed)} failed, {len(conflicts)} conflict(s)"
                ),
            )
        ],
    }
