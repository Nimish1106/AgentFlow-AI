"""Embedding model factory (SRS §32: BAAI/bge-small-en-v1.5, configurable).

The model name and dimensions come from settings (SRS §46: keep the embedding
model configurable). ``fastembed`` runs the model on CPU via ONNX; inference is
synchronous, so it is pushed onto a worker thread to keep the event loop free
(SRS §16.11: fully asynchronous system).
"""

import asyncio
from functools import lru_cache
from typing import List, Protocol

from app.config.settings import get_settings


class EmbeddingModel(Protocol):
    """Anything that can embed a batch of texts (test seam)."""

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Return one vector per input text."""
        ...


class FastEmbedModel:
    """fastembed-backed embedder, lazily loaded on first use.

    Loading downloads the ONNX weights on first call, so neither module import
    nor construction touches the network — only ``embed`` does.
    """

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed ``texts`` on a worker thread (model inference is sync CPU work)."""
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: List[str]) -> List[List[float]]:
        model = self._load()
        return [vector.tolist() for vector in model.embed(texts)]


@lru_cache
def get_embedding_model() -> FastEmbedModel:
    """Return the shared embedder built from settings."""
    return FastEmbedModel(get_settings().embedding_model)
