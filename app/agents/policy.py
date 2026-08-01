"""Policy Agent (SRS §30.6): validate rules, assess risk, gate the workflow.

LLM: yes. MCP: no. The Policy Agent judges the other agents' results against
policy; on conflicts its verdict wins (SRS §40). It runs after the domain
agents have joined, so it is alone in its superstep and may write unreduced
keys such as ``current_node`` and ``risk_score``.
"""

import json
import logging
import time
from typing import Awaitable, Callable, Dict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.base import build_user_prompt
from app.agents.schemas import PolicyOutcome
from app.graph.constants import AgentName
from app.graph.state import AgentResult, GraphState, build_node_execution
from app.prompts.agents import POLICY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

NODE_NAME = AgentName.POLICY.value

#: SRS §39 risk levels mapped onto the numeric GraphState.risk_score.
RISK_SCORES: Dict[str, float] = {"low": 0.2, "medium": 0.5, "high": 0.9}


def format_agent_results(state: GraphState) -> str:
    """Render prior AgentResults for the prompt (empty-safe)."""
    results = state.get("agent_results", [])
    if not results:
        return "No domain agents ran for this ticket."
    return json.dumps(results, indent=2, default=str)


def make_policy_agent_node(
    llm: BaseChatModel | None = None,
) -> Callable[[GraphState], Awaitable[Dict]]:
    """Build the Policy Agent node with an injectable LLM."""

    async def policy_agent_node(state: GraphState) -> Dict:
        """Evaluate policy compliance and return a GraphState update."""
        started = time.perf_counter()
        workflow_id = state.get("workflow_id", "")

        model = llm
        if model is None:
            from app.graph.llm import get_llm

            model = get_llm()

        prompt = (
            f"{build_user_prompt(state)}\n\n"
            f"Agent results to evaluate:\n{format_agent_results(state)}"
        )
        judge = model.with_structured_output(PolicyOutcome)

        try:
            outcome: PolicyOutcome = await judge.ainvoke(
                [
                    SystemMessage(content=POLICY_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
        except Exception as exc:  # noqa: BLE001 - policy gate cannot be skipped
            # SRS §35: no policy verdict means the workflow must not proceed to
            # a customer-facing response - stop it.
            logger.exception(
                "workflow_id=%s node=%s policy evaluation failed",
                workflow_id,
                NODE_NAME,
            )
            return {
                "current_node": NODE_NAME,
                "workflow_status": "failed",
                "completed_agents": [NODE_NAME],
                "errors": [f"{NODE_NAME}: policy evaluation failed: {exc}"],
                "node_executions": [
                    build_node_execution(
                        node=NODE_NAME,
                        status="failed",
                        execution_time_ms=(time.perf_counter() - started) * 1000,
                        summary=f"policy evaluation failed: {exc}",
                    )
                ],
            }

        result = AgentResult(
            agent_name=NODE_NAME,
            status="success",
            summary=outcome.summary,
            confidence=outcome.confidence,
            actions_taken=outcome.actions_taken or ["evaluated_policy"],
            tool_calls=[],
            output_data={
                "approved": outcome.approved,
                "risk": outcome.risk,
                **outcome.output_data,
            },
        )

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "workflow_id=%s node=%s approved=%s risk=%s confidence=%.2f "
            "execution_time_ms=%.1f retry_count=%s",
            workflow_id,
            NODE_NAME,
            outcome.approved,
            outcome.risk,
            outcome.confidence,
            elapsed_ms,
            state.get("retry_count", 0),
        )

        return {
            "current_node": NODE_NAME,
            "agent_results": [result],
            "completed_agents": [NODE_NAME],
            "risk_score": RISK_SCORES[outcome.risk],
            "shared_context": {
                NODE_NAME: {"approved": outcome.approved, "risk": outcome.risk}
            },
            "messages": [AIMessage(content=f"{NODE_NAME}: {outcome.summary}")],
            "node_executions": [
                build_node_execution(
                    node=NODE_NAME,
                    status="success",
                    execution_time_ms=elapsed_ms,
                    confidence=outcome.confidence,
                    summary=outcome.summary,
                )
            ],
        }

    return policy_agent_node
