"""Shared agent machinery: the bind_tools -> ToolNode -> AgentResult loop.

SRS §31 implementation rule: the agent LLM binds MCP tool definitions and emits
``tool_call`` messages; a LangGraph **ToolNode** executes them against the
Enterprise MCP client. Each agent runs its ToolNode over a private message list
so parallel domain agents never interleave in the shared ``messages`` channel -
only the closing summary is written back to GraphState.

Parallel-safety: domain agents run in the same superstep, so their nodes write
*reduced* GraphState keys only (``agent_results``, ``errors``,
``completed_agents``, ``tool_history``, ``shared_context``, ``messages``).
Writing an unreduced key such as ``current_node`` from a parallel branch would
make LangGraph raise ``InvalidUpdateError``.
"""

import logging
import time
from typing import Awaitable, Callable, Dict, List, Sequence, Tuple, Type

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime

from app.agents.schemas import AgentOutcome
from app.config.settings import get_settings
from app.graph.constants import AgentName
from app.graph.state import AgentResult, GraphState
from app.graph.tools import build_agent_tools
from app.mcp.client import EnterpriseMCPClient

logger = logging.getLogger(__name__)

_FINALIZE_INSTRUCTION = (
    "You are done using tools. Produce your final structured outcome now, "
    "based only on the conversation above."
)


async def run_agent_loop(
    *,
    llm: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    user_prompt: str,
    outcome_schema: Type[AgentOutcome],
    max_rounds: int,
) -> Tuple[AgentOutcome, List[str]]:
    """Run one agent conversation: tool loop, then a structured closing call.

    Returns the parsed outcome and the ordered list of tool names the agent
    called (for ``AgentResult.tool_calls`` / ``tool_history``).
    """
    messages: List[BaseMessage] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    tool_calls_made: List[str] = []

    if tools:
        bound = llm.bind_tools(tools)
        tool_node = ToolNode(tools)
        # The ToolNode runs over this agent's private message list, outside the
        # outer graph, so it needs an explicit Runtime in its config.
        tool_config = {"configurable": {"__pregel_runtime": Runtime(context=None)}}
        for _ in range(max_rounds):
            ai_message: AIMessage = await bound.ainvoke(messages)
            messages.append(ai_message)
            tool_calls = getattr(ai_message, "tool_calls", None) or []
            if not tool_calls:
                break
            tool_calls_made.extend(call["name"] for call in tool_calls)
            tool_result = await tool_node.ainvoke(
                {"messages": [ai_message]}, config=tool_config
            )
            messages.extend(tool_result["messages"])

    finalizer = llm.with_structured_output(outcome_schema)
    outcome = await finalizer.ainvoke(
        [*messages, HumanMessage(content=_FINALIZE_INSTRUCTION)]
    )
    return outcome, tool_calls_made


def build_user_prompt(state: GraphState) -> str:
    """Render the ticket and everything already discovered into one prompt."""
    shared_context = state.get("shared_context", {})
    return (
        f"Ticket ID: {state.get('ticket_id')}\n"
        f"Customer ID: {state.get('customer_id')}\n"
        f"Customer tier: {state.get('customer_tier')}\n"
        f"Priority: {state.get('ticket_priority')}\n"
        f"Intent: {shared_context.get('intent', 'unknown')}\n\n"
        f"Ticket text:\n\"\"\"\n{state.get('issue_text', '')}\n\"\"\"\n\n"
        f"Shared context (facts other agents already discovered):\n"
        f"{shared_context}"
    )


def make_domain_agent_node(
    *,
    agent: AgentName,
    system_prompt: str,
    llm: BaseChatModel | None = None,
    mcp_client: EnterpriseMCPClient | None = None,
) -> Callable[[GraphState], Awaitable[Dict]]:
    """Build a tool-using domain agent node (Billing / Account / Technical).

    ``llm`` and ``mcp_client`` are injectable for tests; both default to the
    configured instances, resolved lazily so the graph compiles without
    credentials or a running MCP server.
    """

    async def agent_node(state: GraphState) -> Dict:
        """Run the agent and return a parallel-safe GraphState update."""
        started = time.perf_counter()
        workflow_id = state.get("workflow_id", "")

        model = llm if llm is not None else _default_llm()
        client = mcp_client if mcp_client is not None else _default_mcp_client()
        tools = build_agent_tools(client, agent, workflow_id=workflow_id)

        try:
            outcome, tool_calls = await run_agent_loop(
                llm=model,
                tools=tools,
                system_prompt=system_prompt,
                user_prompt=build_user_prompt(state),
                outcome_schema=AgentOutcome,
                max_rounds=get_settings().agent_max_tool_rounds,
            )
        except Exception as exc:  # noqa: BLE001 - branch degrades, policy gates
            # SRS §35/§40: continue with partial results where safe. The failed
            # AgentResult is visible to the Policy Agent, which decides whether
            # the workflow may still resolve.
            logger.exception(
                "workflow_id=%s node=%s agent loop failed", workflow_id, agent.value
            )
            return {
                "agent_results": [_failed_result(agent, exc)],
                "completed_agents": [agent.value],
                "errors": [f"{agent.value}: {exc}"],
            }

        result = AgentResult(
            agent_name=agent.value,
            status="success",
            summary=outcome.summary,
            confidence=outcome.confidence,
            actions_taken=outcome.actions_taken,
            tool_calls=tool_calls,
            output_data=outcome.output_data,
        )

        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "workflow_id=%s node=%s status=success confidence=%.2f tool_calls=%s "
            "execution_time_ms=%.1f retry_count=%s",
            workflow_id,
            agent.value,
            outcome.confidence,
            tool_calls,
            elapsed_ms,
            state.get("retry_count", 0),
        )

        return {
            "agent_results": [result],
            "completed_agents": [agent.value],
            "tool_history": tool_calls,
            "shared_context": {agent.value: outcome.output_data},
            "messages": [AIMessage(content=f"{agent.value}: {outcome.summary}")],
        }

    return agent_node


def _failed_result(agent: AgentName, exc: Exception) -> AgentResult:
    """Uniform failed AgentResult so the aggregator sees the same shape."""
    return AgentResult(
        agent_name=agent.value,
        status="failed",
        summary=f"{agent.value} failed: {exc}",
        confidence=0.0,
        actions_taken=[],
        tool_calls=[],
        output_data={},
    )


def _default_llm() -> BaseChatModel:
    from app.graph.llm import get_llm

    return get_llm()


def _default_mcp_client() -> EnterpriseMCPClient:
    from app.mcp.client import get_enterprise_mcp_client

    return get_enterprise_mcp_client()
