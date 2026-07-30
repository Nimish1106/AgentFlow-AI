"""Knowledge retrieval backing the Enterprise MCP knowledge tools (SRS §31, §33).

Phase 3 ships the tool contract only. Qdrant-backed semantic search arrives in
Phase 5; until then every search follows the RAG rule from SRS §33 and reports
insufficient information instead of fabricating results.
"""

INSUFFICIENT_INFORMATION = "insufficient_information"


class KnowledgeService:
    """Searches the enterprise knowledge base (Qdrant in Phase 5)."""

    async def semantic_search(self, query: str, top_k: int = 5) -> dict:
        """Semantic search across the whole knowledge base."""
        return self._insufficient(query, collection="knowledge")

    async def search_policy(self, query: str) -> dict:
        """Search policy documents (refund policies, SLAs)."""
        return self._insufficient(query, collection="policies")

    async def search_runbook(self, query: str) -> dict:
        """Search troubleshooting guides and internal runbooks."""
        return self._insufficient(query, collection="runbooks")

    @staticmethod
    def _insufficient(query: str, *, collection: str) -> dict:
        return {
            "status": INSUFFICIENT_INFORMATION,
            "query": query,
            "collection": collection,
            "results": [],
            "message": (
                "No relevant context found in the knowledge base. "
                "Do not answer from unsupported knowledge."
            ),
        }
