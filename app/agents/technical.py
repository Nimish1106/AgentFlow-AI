"""Technical Agent (SRS §30.5): retrieve docs, FAQs, troubleshooting guides.

RAG rule: never answer without retrieved context; the Phase 3 knowledge tools
currently return ``insufficient_information``, and the prompt requires the
agent to report exactly that rather than hallucinate a solution.
"""

from typing import Awaitable, Callable, Dict

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.base import make_domain_agent_node
from app.graph.constants import AgentName
from app.graph.state import GraphState
from app.mcp.client import EnterpriseMCPClient
from app.prompts.agents import TECHNICAL_SYSTEM_PROMPT

NODE_NAME = AgentName.TECHNICAL.value


def make_technical_agent_node(
    llm: BaseChatModel | None = None,
    mcp_client: EnterpriseMCPClient | None = None,
) -> Callable[[GraphState], Awaitable[Dict]]:
    """Build the Technical Agent node with injectable LLM and MCP client."""
    return make_domain_agent_node(
        agent=AgentName.TECHNICAL,
        system_prompt=TECHNICAL_SYSTEM_PROMPT,
        llm=llm,
        mcp_client=mcp_client,
    )
