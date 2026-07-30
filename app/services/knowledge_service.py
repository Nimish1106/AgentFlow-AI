"""Knowledge retrieval backing the Enterprise MCP knowledge tools (SRS §31, §33).

Phase 5 wires the Phase-3 tool contract to real Qdrant-backed retrieval. The
RAG rules from SRS §33 hold: retrieve before generation, return citations when
available, and report insufficient information instead of fabricating results
when nothing relevant is found.
"""

from typing import Optional, Sequence

from app.rag.retriever import KnowledgeRetriever, get_retriever
from app.rag.schemas import RetrievedChunk

INSUFFICIENT_INFORMATION = "insufficient_information"
OK = "ok"

# Document kinds behind each scoped search (SRS §20 lists the corpus).
POLICY_DOC_TYPES = ("refund_policy", "sla", "policy")
RUNBOOK_DOC_TYPES = ("runbook", "troubleshooting")


class KnowledgeService:
    """Searches the enterprise knowledge base in Qdrant."""

    def __init__(self, retriever: Optional[KnowledgeRetriever] = None) -> None:
        self._retriever = retriever

    async def semantic_search(self, query: str, top_k: int = 5) -> dict:
        """Semantic search across the whole knowledge base."""
        return await self._search(query, collection="knowledge", top_k=top_k)

    async def search_policy(self, query: str) -> dict:
        """Search policy documents (refund policies, SLAs)."""
        return await self._search(
            query, collection="policies", doc_types=POLICY_DOC_TYPES
        )

    async def search_runbook(self, query: str) -> dict:
        """Search troubleshooting guides and internal runbooks."""
        return await self._search(
            query, collection="runbooks", doc_types=RUNBOOK_DOC_TYPES
        )

    async def _search(
        self,
        query: str,
        *,
        collection: str,
        top_k: Optional[int] = None,
        doc_types: Optional[Sequence[str]] = None,
    ) -> dict:
        retriever = self._retriever or get_retriever()
        hits = await retriever.search(query, top_k=top_k, doc_types=doc_types)
        if not hits:
            return self._insufficient(query, collection=collection)
        return {
            "status": OK,
            "query": query,
            "collection": collection,
            "results": [self._citation(hit) for hit in hits],
            "message": None,
        }

    @staticmethod
    def _citation(hit: RetrievedChunk) -> dict:
        """One result with its citation (SRS §33: return citations)."""
        return {
            "text": hit.text,
            "source": hit.source,
            "title": hit.title,
            "doc_type": hit.doc_type,
            "score": round(hit.score, 4),
        }

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
