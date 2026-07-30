"""Async Qdrant wrapper for the knowledge collection (SRS §20, §32).

One collection holds every knowledge chunk; the document kind travels in the
``doc_type`` payload field so policy/runbook searches filter rather than
maintain separate collections. Point ids are deterministic (UUID5 of
``source:chunk_index``), which makes re-ingestion an idempotent upsert.
"""

import uuid
from typing import List, Optional, Sequence

from qdrant_client import AsyncQdrantClient, models

from app.config.settings import get_settings
from app.rag.schemas import PAYLOAD_DOC_TYPE, KnowledgeChunk, RetrievedChunk


def chunk_point_id(source: str, chunk_index: int) -> str:
    """Deterministic point id so re-ingesting a document overwrites in place."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}:{chunk_index}"))


class KnowledgeVectorStore:
    """Thin async wrapper over the Qdrant knowledge collection."""

    def __init__(
        self,
        client: Optional[AsyncQdrantClient] = None,
        *,
        collection: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self._client = client or AsyncQdrantClient(url=settings.qdrant_url)
        self.collection = collection or settings.qdrant_collection

    async def ensure_collection(self) -> None:
        """Create the knowledge collection if it does not exist yet."""
        if await self._client.collection_exists(self.collection):
            return
        await self._client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=get_settings().embedding_dimensions,
                distance=models.Distance.COSINE,
            ),
        )

    async def upsert_chunks(
        self, chunks: Sequence[KnowledgeChunk], vectors: Sequence[List[float]]
    ) -> int:
        """Upsert one point per chunk; returns the number of points written."""
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return 0
        points = [
            models.PointStruct(
                id=chunk_point_id(chunk.source, chunk.chunk_index),
                vector=list(vector),
                payload=chunk.payload(),
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        await self._client.upsert(collection_name=self.collection, points=points)
        return len(points)

    async def search(
        self,
        vector: List[float],
        *,
        top_k: int,
        score_threshold: float,
        doc_types: Optional[Sequence[str]] = None,
    ) -> List[RetrievedChunk]:
        """Return the top-k chunks above the score threshold, with citations."""
        query_filter = None
        if doc_types:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key=PAYLOAD_DOC_TYPE,
                        match=models.MatchAny(any=list(doc_types)),
                    )
                ]
            )
        response = await self._client.query_points(
            collection_name=self.collection,
            query=list(vector),
            limit=top_k,
            score_threshold=score_threshold,
            query_filter=query_filter,
            with_payload=True,
        )
        return [
            RetrievedChunk(
                text=point.payload["text"],
                source=point.payload["source"],
                title=point.payload["title"],
                doc_type=point.payload["doc_type"],
                score=point.score,
            )
            for point in response.points
        ]
