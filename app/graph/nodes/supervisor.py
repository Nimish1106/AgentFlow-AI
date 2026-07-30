"""Supervisor node: classify ticket intent, domains and priority (SRS §30.1).

LLM: yes. MCP: no. The Supervisor reasons over the ticket text alone and writes
its classification into ``shared_context`` for downstream nodes.
"""

import logging
import time
from typing import Awaitable, Callable, Dict, List

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from app.graph.constants import AgentName, Domain
from app.graph.state import GraphState
from app.prompts.supervisor import (
    SUPERVISOR_SYSTEM_PROMPT,
    SUPERVISOR_USER_PROMPT,
)

logger = logging.getLogger(__name__)

NODE_NAME = "supervisor"


class SupervisorClassification(BaseModel):
    """Structured Supervisor output (SRS §30.1).

    Constraining domains to the ``Domain`` enum stops the LLM inventing a domain
    the planner has no agent for.
    """

    model_config = ConfigDict(from_attributes=True)

    intent: str = Field(description="Short noun phrase naming the core problem.")
    domains: List[Domain] = Field(
        default_factory=list,
        description="Business domains the ticket touches.",
    )
    priority: str = Field(
        default="medium",
        description="One of: low, medium, high, critical.",
    )


def make_supervisor_node(
    llm: BaseChatModel,
) -> Callable[[GraphState], Awaitable[Dict]]:
    """Build the Supervisor node bound to a chat model.

    Injecting the model keeps the node unit-testable without network access and
    without reading configuration itself.
    """
    classifier = llm.with_structured_output(SupervisorClassification)

    async def supervisor_node(state: GraphState) -> Dict:
        """Classify the ticket and return a GraphState update."""
        started = time.perf_counter()
        prompt = SUPERVISOR_USER_PROMPT.format(
            customer_tier=state.get("customer_tier", "unknown"),
            ticket_priority=state.get("ticket_priority", "unknown"),
            issue_text=state.get("issue_text", ""),
        )
        messages = [
            SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        try:
            classification: SupervisorClassification = await classifier.ainvoke(
                messages
            )
        except Exception as exc:  # noqa: BLE001 - recorded, then workflow stops
            # SRS §35: a classification we cannot produce is non-recoverable -
            # stop the workflow rather than planning against a guessed intent.
            logger.exception(
                "workflow_id=%s node=%s classification failed",
                state.get("workflow_id"),
                NODE_NAME,
            )
            return {
                "current_node": NODE_NAME,
                "workflow_status": "failed",
                "errors": [f"supervisor: classification failed: {exc}"],
            }

        domains = [domain.value for domain in classification.domains]
        elapsed_ms = (time.perf_counter() - started) * 1000

        # SRS §46 logging: workflow_id, node, execution time, retries, errors.
        logger.info(
            "workflow_id=%s node=%s intent=%r domains=%s priority=%s "
            "execution_time_ms=%.1f retry_count=%s",
            state.get("workflow_id"),
            NODE_NAME,
            classification.intent,
            domains,
            classification.priority,
            elapsed_ms,
            state.get("retry_count", 0),
        )

        summary = (
            f"Classified as {classification.intent!r} "
            f"(domains={domains or ['none']}, priority={classification.priority})"
        )

        return {
            "current_node": NODE_NAME,
            "workflow_status": "running",
            "ticket_priority": classification.priority,
            "shared_context": {
                **state.get("shared_context", {}),
                "intent": classification.intent,
                "domains": domains,
                "priority": classification.priority,
            },
            "completed_agents": [
                *state.get("completed_agents", []),
                AgentName.SUPERVISOR.value,
            ],
            "messages": [AIMessage(content=summary)],
        }

    return supervisor_node


async def supervisor_node(state: GraphState) -> Dict:
    """Default Supervisor node using the configured Groq model."""
    from app.graph.llm import get_llm

    return await make_supervisor_node(get_llm())(state)
