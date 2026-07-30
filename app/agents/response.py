"""Response Agent (SRS §30.7): generate the customer-facing resolution.

Rules: uses ONLY GraphState and AgentResults - never calls MCP, never queries
databases (SRS §34 forbids Response Agent -> MCP). It is the last agent node,
so it may write unreduced keys (``final_response``, ``workflow_status``).
"""

import logging
import time
from typing import Awaitable, Callable, Dict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.base import build_user_prompt
from app.agents.policy import format_agent_results
from app.agents.schemas import ResponseOutcome
from app.graph.constants import AgentName
from app.graph.state import AgentResult, GraphState
from app.prompts.agents import RESPONSE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

NODE_NAME = AgentName.RESPONSE.value


def make_response_agent_node(
    llm: BaseChatModel | None = None,
) -> Callable[[GraphState], Awaitable[Dict]]:
    """Build the Response Agent node with an injectable LLM."""

    async def response_agent_node(state: GraphState) -> Dict:
        """Draft the final response from GraphState and return the update."""
        started = time.perf_counter()
        workflow_id = state.get("workflow_id", "")

        model = llm
        if model is None:
            from app.graph.llm import get_llm

            model = get_llm()

        prompt = (
            f"{build_user_prompt(state)}\n\n"
            f"Agent results to base the response on:\n"
            f"{format_agent_results(state)}"
        )
        writer = model.with_structured_output(ResponseOutcome)

        try:
            outcome: ResponseOutcome = await writer.ainvoke(
                [
                    SystemMessage(content=RESPONSE_SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ]
            )
        except Exception as exc:  # noqa: BLE001 - no response means failure
            logger.exception(
                "workflow_id=%s node=%s response generation failed",
                workflow_id,
                NODE_NAME,
            )
            return {
                "current_node": NODE_NAME,
                "workflow_status": "failed",
                "completed_agents": [NODE_NAME],
                "errors": [f"{NODE_NAME}: response generation failed: {exc}"],
            }

        result = AgentResult(
            agent_name=NODE_NAME,
            status="success",
            summary=outcome.resolution_summary,
            confidence=outcome.confidence,
            actions_taken=["generated_customer_response"],
            tool_calls=[],
            output_data={
                "customer_response": outcome.customer_response,
                "internal_note": outcome.internal_note,
                "resolution_summary": outcome.resolution_summary,
            },
        )

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "workflow_id=%s node=%s confidence=%.2f execution_time_ms=%.1f "
            "retry_count=%s",
            workflow_id,
            NODE_NAME,
            outcome.confidence,
            elapsed_ms,
            state.get("retry_count", 0),
        )

        return {
            "current_node": NODE_NAME,
            "agent_results": [result],
            "completed_agents": [NODE_NAME],
            "final_response": outcome.customer_response,
            "workflow_status": "completed",
            "messages": [AIMessage(content=outcome.customer_response)],
        }

    return response_agent_node
