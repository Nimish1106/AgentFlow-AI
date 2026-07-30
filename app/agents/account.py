"""Account Agent (SRS §30.4): verify accounts, unlock dashboards, flags."""

from typing import Awaitable, Callable, Dict

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.base import make_domain_agent_node
from app.graph.constants import AgentName
from app.graph.state import GraphState
from app.mcp.client import EnterpriseMCPClient
from app.prompts.agents import ACCOUNT_SYSTEM_PROMPT

NODE_NAME = AgentName.ACCOUNT.value


def make_account_agent_node(
    llm: BaseChatModel | None = None,
    mcp_client: EnterpriseMCPClient | None = None,
) -> Callable[[GraphState], Awaitable[Dict]]:
    """Build the Account Agent node with injectable LLM and MCP client."""
    return make_domain_agent_node(
        agent=AgentName.ACCOUNT,
        system_prompt=ACCOUNT_SYSTEM_PROMPT,
        llm=llm,
        mcp_client=mcp_client,
    )
