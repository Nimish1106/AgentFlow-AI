"""Billing Agent (SRS §30.3): verify invoices, detect duplicates, refunds."""

from typing import Awaitable, Callable, Dict

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.base import make_domain_agent_node
from app.graph.constants import AgentName
from app.graph.state import GraphState
from app.mcp.client import EnterpriseMCPClient
from app.prompts.agents import BILLING_SYSTEM_PROMPT

NODE_NAME = AgentName.BILLING.value


def make_billing_agent_node(
    llm: BaseChatModel | None = None,
    mcp_client: EnterpriseMCPClient | None = None,
) -> Callable[[GraphState], Awaitable[Dict]]:
    """Build the Billing Agent node with injectable LLM and MCP client."""
    return make_domain_agent_node(
        agent=AgentName.BILLING,
        system_prompt=BILLING_SYSTEM_PROMPT,
        llm=llm,
        mcp_client=mcp_client,
    )
