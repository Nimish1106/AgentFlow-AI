"""LangChain tool adapters over the Enterprise MCP client (SRS §31, §34, §41).

Agents never execute HTTP requests. They bind these tool *definitions* via
``bind_tools()`` and emit tool_calls; the LangGraph ToolNode executes the
coroutines below, which are the only workflow code that touches the MCP client.

Retry policy (SRS §41): only recoverable failures are retried - an MCP-side
tool timeout (structured ``code == "timeout"``) or a transport error reaching
the server. Structured business errors (``invalid_input``, ``not_found``) are
returned to the agent verbatim so the LLM can reason about them; they are
never retried.
"""

import asyncio
import json
import logging
from typing import Awaitable, Callable, Dict, List

from langchain_core.tools import StructuredTool
from langsmith import traceable
from pydantic import BaseModel, Field

from app.config.settings import get_settings
from app.graph.constants import AgentName
from app.mcp.client import EnterpriseMCPClient

logger = logging.getLogger(__name__)

#: Structured error codes the MCP server may return that are worth retrying.
RETRYABLE_ERROR_CODES = frozenset({"timeout"})


@traceable(name="mcp_tool_call", run_type="tool")
async def call_mcp_tool_with_retry(
    client: EnterpriseMCPClient,
    tool_name: str,
    arguments: dict,
    *,
    workflow_id: str,
) -> dict:
    """Call one MCP tool, retrying only recoverable failures (SRS §41).

    Recoverable: transport exceptions (server unreachable, connection dropped)
    and a structured ``timeout`` error from the server. Max 3 attempts with
    exponential backoff, every retry logged.

    Non-recoverable structured errors are returned as-is; if all attempts fail
    on transport errors, a structured ``unavailable`` error is returned so the
    agent loop degrades instead of crashing the branch.
    """
    settings = get_settings()
    max_attempts = settings.mcp_retry_max_attempts
    payload = {**arguments, "workflow_id": workflow_id}
    last_error = "unknown error"

    for attempt in range(1, max_attempts + 1):
        try:
            result = await client.call_tool(tool_name, payload)
        except Exception as exc:  # noqa: BLE001 - transport failure is recoverable
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "workflow_id=%s tool=%s attempt=%s/%s transport error: %s",
                workflow_id,
                tool_name,
                attempt,
                max_attempts,
                last_error,
            )
        else:
            code = result.get("code") if isinstance(result, dict) else None
            if code not in RETRYABLE_ERROR_CODES:
                return result
            last_error = result.get("error", "tool timeout")
            logger.warning(
                "workflow_id=%s tool=%s attempt=%s/%s recoverable tool error: %s",
                workflow_id,
                tool_name,
                attempt,
                max_attempts,
                last_error,
            )

        if attempt < max_attempts:
            await asyncio.sleep(settings.mcp_retry_backoff_seconds * 2 ** (attempt - 1))

    return {
        "error": f"{tool_name} failed after {max_attempts} attempts: {last_error}",
        "code": "unavailable",
    }


class _InvoiceArgs(BaseModel):
    invoice_id: str = Field(description="UUID of the invoice.")


class _CustomerArgs(BaseModel):
    customer_id: str = Field(description="UUID of the customer.")


class _FeatureFlagArgs(BaseModel):
    customer_id: str = Field(description="UUID of the customer.")
    flag_name: str = Field(description="Name of the feature flag.")
    enabled: bool = Field(description="Desired flag value.")


class _TicketArgs(BaseModel):
    ticket_id: str = Field(description="UUID of the support ticket.")


class _TicketUpdateArgs(BaseModel):
    ticket_id: str = Field(description="UUID of the support ticket.")
    status: str | None = Field(
        default=None,
        description="New status: open, in_progress, resolved, closed.",
    )
    priority: str | None = Field(
        default=None, description="New priority: low, medium, high, critical."
    )


class _TicketNoteArgs(BaseModel):
    ticket_id: str = Field(description="UUID of the support ticket.")
    author: str = Field(description="Agent name writing the note.")
    note: str = Field(description="Internal note text.")


class _SearchArgs(BaseModel):
    query: str = Field(description="Natural-language search query.")


#: tool name -> (args schema, description). The names must match the Enterprise
#: MCP Server registrations exactly (SRS §31).
_TOOL_SPECS: Dict[str, tuple[type[BaseModel], str]] = {
    "billing_get_invoice": (
        _InvoiceArgs,
        "Fetch an invoice by id, including amount and payment status.",
    ),
    "billing_get_subscription": (
        _CustomerArgs,
        "Fetch the customer's most recent subscription.",
    ),
    "billing_calculate_refund": (
        _InvoiceArgs,
        "Deterministically evaluate refund eligibility for an invoice.",
    ),
    "account_get_customer": (
        _CustomerArgs,
        "Fetch a customer account, including status and feature flags.",
    ),
    "account_unlock_dashboard": (
        _CustomerArgs,
        "Unlock a locked customer dashboard (locked -> active only).",
    ),
    "account_update_feature_flag": (
        _FeatureFlagArgs,
        "Enable or disable a feature flag on a customer account.",
    ),
    "ticket_get_ticket": (
        _TicketArgs,
        "Fetch a support ticket by id.",
    ),
    "ticket_update_ticket": (
        _TicketUpdateArgs,
        "Update a support ticket's status and/or priority.",
    ),
    "ticket_add_internal_note": (
        _TicketNoteArgs,
        "Attach an internal note to a support ticket.",
    ),
    "knowledge_semantic_search": (
        _SearchArgs,
        "Semantic search across the enterprise knowledge base.",
    ),
    "knowledge_search_policy": (
        _SearchArgs,
        "Search policy documents (refund policies, SLAs).",
    ),
    "knowledge_search_runbook": (
        _SearchArgs,
        "Search operational runbooks and troubleshooting guides.",
    ),
}

#: Which MCP tools each agent may bind (SRS §30.3-§30.5). Policy and Response
#: agents bind no tools at all.
AGENT_TOOL_NAMES: Dict[AgentName, tuple[str, ...]] = {
    AgentName.BILLING: (
        "billing_get_invoice",
        "billing_get_subscription",
        "billing_calculate_refund",
    ),
    AgentName.ACCOUNT: (
        "account_get_customer",
        "account_unlock_dashboard",
        "account_update_feature_flag",
    ),
    AgentName.TECHNICAL: ("knowledge_semantic_search",),
}

MCPToolCaller = Callable[..., Awaitable[dict]]


def build_agent_tools(
    client: EnterpriseMCPClient,
    agent: AgentName,
    *,
    workflow_id: str,
) -> List[StructuredTool]:
    """Build the StructuredTool set one agent may bind (SRS §30).

    ``workflow_id`` is baked into every call so MCP-side audit logs attribute
    the tool call to the running workflow - the LLM never sees or supplies it.
    """
    tools: List[StructuredTool] = []
    for tool_name in AGENT_TOOL_NAMES.get(agent, ()):
        args_schema, description = _TOOL_SPECS[tool_name]
        tools.append(
            StructuredTool.from_function(
                coroutine=_make_tool_coroutine(client, tool_name, workflow_id),
                name=tool_name,
                description=description,
                args_schema=args_schema,
            )
        )
    return tools


def _make_tool_coroutine(
    client: EnterpriseMCPClient, tool_name: str, workflow_id: str
) -> MCPToolCaller:
    """Bind tool name + workflow id into a coroutine ToolNode can execute."""

    async def call(**arguments) -> str:
        result = await call_mcp_tool_with_retry(
            client, tool_name, arguments, workflow_id=workflow_id
        )
        return json.dumps(result)

    return call
