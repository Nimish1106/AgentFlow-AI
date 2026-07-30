"""Knowledge tool namespace for the Enterprise MCP Server (SRS §31, §33)."""

from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.schemas import KnowledgeSearchResult
from app.mcp.server.runtime import run_tool
from app.services.knowledge_service import KnowledgeService


def register(mcp: FastMCP) -> None:
    """Register knowledge tools on the server."""

    @mcp.tool(name="knowledge_semantic_search")
    async def knowledge_semantic_search(
        query: str, top_k: int = 5, workflow_id: Optional[str] = None
    ) -> dict:
        """Semantic search across the enterprise knowledge base."""

        async def handler(session: AsyncSession) -> dict:
            result = await KnowledgeService().semantic_search(query, top_k=top_k)
            return KnowledgeSearchResult(**result).model_dump(mode="json")

        return await run_tool(
            "knowledge_semantic_search",
            handler,
            arguments={"query": query, "top_k": top_k},
            workflow_id=workflow_id,
        )

    @mcp.tool(name="knowledge_search_policy")
    async def knowledge_search_policy(
        query: str, workflow_id: Optional[str] = None
    ) -> dict:
        """Search policy documents (refund policies, SLAs)."""

        async def handler(session: AsyncSession) -> dict:
            result = await KnowledgeService().search_policy(query)
            return KnowledgeSearchResult(**result).model_dump(mode="json")

        return await run_tool(
            "knowledge_search_policy",
            handler,
            arguments={"query": query},
            workflow_id=workflow_id,
        )

    @mcp.tool(name="knowledge_search_runbook")
    async def knowledge_search_runbook(
        query: str, workflow_id: Optional[str] = None
    ) -> dict:
        """Search troubleshooting guides and internal runbooks."""

        async def handler(session: AsyncSession) -> dict:
            result = await KnowledgeService().search_runbook(query)
            return KnowledgeSearchResult(**result).model_dump(mode="json")

        return await run_tool(
            "knowledge_search_runbook",
            handler,
            arguments={"query": query},
            workflow_id=workflow_id,
        )
