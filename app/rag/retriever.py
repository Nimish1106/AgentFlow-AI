"""Runtime knowledge retrieval for the MCP knowledge tools (SRS §33).

Retrieve before generation: the retriever embeds the query with the same
configured model used at ingestion time and returns the top-k chunks above the
relevance threshold. An empty result is meaningful — the caller must report
insufficient information rather than let the LLM fill the gap.
"""

from functools import lru_cache
from typing import List, Optional, Sequence

from app.config.settings import get_settings
from app.rag.embeddings import EmbeddingModel, get_embedding_model
from app.rag.schemas import RetrievedChunk
from app.rag.vector_store import KnowledgeVectorStore


class KnowledgeRetriever:
    """Embeds a query and searches the Qdrant knowledge collection."""

    def __init__(
        self,
        embedder: Optional[EmbeddingModel] = None,
        store: Optional[KnowledgeVectorStore] = None,
    ) -> None:
        self._embedder = embedder or get_embedding_model()
        self._store = store or KnowledgeVectorStore()

    async def search(
        self,
        query: str,
        *,
        top_k: Optional[int] = None,
        doc_types: Optional[Sequence[str]] = None,
    ) -> List[RetrievedChunk]:
        """Return relevant chunks for ``query`` (possibly none)."""
        settings = get_settings()
        [vector] = await self._embedder.embed([query])
        return await self._store.search(
            vector,
            top_k=top_k or settings.rag_top_k,
            score_threshold=settings.rag_score_threshold,
            doc_types=doc_types,
        )


@lru_cache
def get_retriever() -> KnowledgeRetriever:
    """Shared retriever for the MCP server process."""
    return KnowledgeRetriever()
