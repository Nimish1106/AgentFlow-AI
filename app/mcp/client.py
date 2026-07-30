"""Async client for the Enterprise MCP Server (streamable-http transport).

Phase 3 uses this for end-to-end verification; the Phase 4 LangGraph ToolNode
is the only workflow component that may consume it (SRS §31). Agents and
FastAPI routes must never call MCP directly.
"""

import json
import logging
from functools import lru_cache
from typing import Any, List

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


class EnterpriseMCPClient:
    """Thin wrapper around the MCP streamable-http client.

    Each call opens a fresh session — the server is stateless, and this keeps
    the client safe to use from concurrent workflow branches.
    """

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._endpoint = f"{base_url.rstrip('/')}/mcp"
        self._timeout = timeout

    async def list_tools(self) -> List[str]:
        """Return the names of every tool exposed by the server."""
        async with streamablehttp_client(
            self._endpoint, timeout=self._timeout
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [tool.name for tool in result.tools]

    async def call_tool(self, name: str, arguments: dict) -> dict[str, Any]:
        """Call a tool by name and return its structured payload."""
        async with streamablehttp_client(
            self._endpoint, timeout=self._timeout
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)

        if result.structuredContent is not None:
            payload = result.structuredContent
            # FastMCP wraps plain dict returns under a "result" key.
            return payload.get("result", payload)

        text = "".join(
            block.text for block in result.content if hasattr(block, "text")
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("tool=%s returned non-JSON content", name)
            return {"error": text or "empty tool response", "code": "invalid_response"}


@lru_cache
def get_enterprise_mcp_client() -> EnterpriseMCPClient:
    """Return a cached client built from application settings.

    The client is stateless (fresh session per call), so one shared instance is
    safe for concurrent workflow branches.
    """
    from app.config.settings import get_settings

    settings = get_settings()
    return EnterpriseMCPClient(
        settings.mcp_server_url, timeout=settings.mcp_tool_timeout_seconds
    )
