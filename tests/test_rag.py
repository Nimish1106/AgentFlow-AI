"""Unit tests for the RAG pipeline: embeddings, vector store, ingestion,
retriever (SRS §32, §33). No network, no model downloads, no running Qdrant."""

import sys
import types
from types import SimpleNamespace

import pytest

from app.config.settings import get_settings
from app.rag.embeddings import FastEmbedModel, get_embedding_model
from app.rag.ingestion import ingest_directory, load_documents, parse_document
from app.rag.retriever import KnowledgeRetriever
from app.rag.schemas import KnowledgeChunk, RetrievedChunk
from app.rag.vector_store import KnowledgeVectorStore, chunk_point_id


def make_chunk(index: int = 0, **overrides) -> KnowledgeChunk:
    payload = {
        "text": f"chunk {index}",
        "source": "refund-policy.md",
        "title": "Refund Policy",
        "doc_type": "refund_policy",
        "chunk_index": index,
    }
    payload.update(overrides)
    return KnowledgeChunk(**payload)


class FakeEmbedder:
    """Deterministic embedder: one 3-dim vector per text."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def embed(self, texts):
        self.batches.append(list(texts))
        return [[1.0, 0.0, float(len(text))] for text in texts]


class FakeQdrantClient:
    """AsyncQdrantClient stand-in recording calls."""

    def __init__(self, *, exists: bool = False, points: list | None = None) -> None:
        self.exists = exists
        self.created: list = []
        self.upserted: list = []
        self.queries: list[dict] = []
        self.points = points or []

    async def collection_exists(self, name):
        return self.exists

    async def create_collection(self, collection_name, vectors_config):
        self.created.append((collection_name, vectors_config))

    async def upsert(self, collection_name, points):
        self.upserted.append((collection_name, points))

    async def query_points(self, **kwargs):
        self.queries.append(kwargs)
        return SimpleNamespace(points=self.points)


def scored_point(score: float = 0.8, **payload_overrides) -> SimpleNamespace:
    payload = {
        "text": "Duplicate charges are refunded in full.",
        "source": "refund-policy.md",
        "title": "Refund Policy",
        "doc_type": "refund_policy",
        "chunk_index": 0,
    }
    payload.update(payload_overrides)
    return SimpleNamespace(payload=payload, score=score)


class TestEmbeddings:
    def test_factory_reads_the_configured_model_name(self):
        """SRS §46: keep the embedding model configurable."""
        get_embedding_model.cache_clear()
        try:
            model = get_embedding_model()
            assert model.model_name == get_settings().embedding_model
            assert model.model_name == "BAAI/bge-small-en-v1.5"
        finally:
            get_embedding_model.cache_clear()

    async def test_empty_batch_never_loads_the_model(self):
        model = FastEmbedModel("BAAI/bge-small-en-v1.5")
        assert await model.embed([]) == []
        assert model._model is None

    async def test_embed_calls_fastembed_lazily(self, monkeypatch):
        loaded = []

        class _Vector(list):
            def tolist(self):
                return list(self)

        class FakeTextEmbedding:
            def __init__(self, model_name):
                loaded.append(model_name)

            def embed(self, texts):
                return [_Vector([0.1, 0.2]) for _ in texts]

        fake_module = types.ModuleType("fastembed")
        fake_module.TextEmbedding = FakeTextEmbedding
        monkeypatch.setitem(sys.modules, "fastembed", fake_module)

        model = FastEmbedModel("some/model")
        assert model._model is None  # nothing loaded at construction
        vectors = await model.embed(["a", "b"])
        assert vectors == [[0.1, 0.2], [0.1, 0.2]]
        assert loaded == ["some/model"]

        await model.embed(["c"])
        assert loaded == ["some/model"]  # loaded once, reused


class TestVectorStore:
    async def test_ensure_collection_creates_when_missing(self):
        client = FakeQdrantClient(exists=False)
        store = KnowledgeVectorStore(client, collection="knowledge")
        await store.ensure_collection()
        [(name, params)] = client.created
        assert name == "knowledge"
        assert params.size == get_settings().embedding_dimensions

    async def test_ensure_collection_is_idempotent(self):
        client = FakeQdrantClient(exists=True)
        await KnowledgeVectorStore(client).ensure_collection()
        assert client.created == []

    async def test_upsert_writes_one_point_per_chunk_with_payload(self):
        client = FakeQdrantClient()
        store = KnowledgeVectorStore(client, collection="knowledge")
        chunks = [make_chunk(0), make_chunk(1)]
        written = await store.upsert_chunks(chunks, [[0.1], [0.2]])
        assert written == 2
        [(_, points)] = client.upserted
        assert points[0].payload["source"] == "refund-policy.md"
        assert points[0].payload["doc_type"] == "refund_policy"
        assert points[1].payload["chunk_index"] == 1

    async def test_point_ids_are_deterministic_for_idempotent_reingestion(self):
        client = FakeQdrantClient()
        store = KnowledgeVectorStore(client)
        await store.upsert_chunks([make_chunk(0)], [[0.1]])
        await store.upsert_chunks([make_chunk(0)], [[0.9]])
        first, second = (points[0].id for _, points in client.upserted)
        assert first == second == chunk_point_id("refund-policy.md", 0)

    async def test_upsert_rejects_mismatched_lengths(self):
        store = KnowledgeVectorStore(FakeQdrantClient())
        with pytest.raises(ValueError, match="same length"):
            await store.upsert_chunks([make_chunk(0)], [])

    async def test_search_maps_hits_to_retrieved_chunks(self):
        client = FakeQdrantClient(points=[scored_point(score=0.83)])
        store = KnowledgeVectorStore(client, collection="knowledge")
        hits = await store.search([0.1, 0.2], top_k=5, score_threshold=0.35)
        assert hits == [
            RetrievedChunk(
                text="Duplicate charges are refunded in full.",
                source="refund-policy.md",
                title="Refund Policy",
                doc_type="refund_policy",
                score=0.83,
            )
        ]
        [query] = client.queries
        assert query["limit"] == 5
        assert query["score_threshold"] == 0.35
        assert query["query_filter"] is None

    async def test_search_filters_by_doc_type(self):
        client = FakeQdrantClient()
        store = KnowledgeVectorStore(client)
        await store.search(
            [0.1], top_k=3, score_threshold=0.5, doc_types=["runbook", "sla"]
        )
        [query] = client.queries
        [condition] = query["query_filter"].must
        assert condition.key == "doc_type"
        assert condition.match.any == ["runbook", "sla"]


class TestDocumentParsing:
    def test_front_matter_is_parsed_into_metadata(self):
        raw = "---\ntitle: Refund Policy\ndoc_type: refund_policy\n---\n\nBody text."
        document = parse_document("refund-policy.md", raw)
        assert document.title == "Refund Policy"
        assert document.doc_type == "refund_policy"
        assert document.text == "Body text."

    def test_missing_front_matter_degrades_to_defaults(self):
        document = parse_document("troubleshooting-access.md", "Just a body.")
        assert document.title == "Troubleshooting Access"
        assert document.doc_type == "product_doc"
        assert document.text == "Just a body."

    def test_load_documents_reads_markdown_recursively_sorted(self, tmp_path):
        (tmp_path / "b.md").write_text("---\ntitle: B\ndoc_type: faq\n---\nB body.")
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "a.md").write_text("A body.")
        (tmp_path / "ignored.txt").write_text("not markdown")
        (tmp_path / "empty.md").write_text("---\ntitle: E\ndoc_type: faq\n---\n\n")

        documents = load_documents(tmp_path)
        assert [d.source for d in documents] == ["b.md", "nested/a.md"]

    def test_load_documents_missing_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_documents(tmp_path / "nope")


class TestIngestion:
    async def test_ingest_directory_chunks_embeds_and_upserts(self, tmp_path):
        (tmp_path / "refund-policy.md").write_text(
            "---\ntitle: Refund Policy\ndoc_type: refund_policy\n---\n\n"
            "Duplicate charges are refunded in full.\n\nPending invoices "
            "have not been paid."
        )
        (tmp_path / "faq.md").write_text("---\ntitle: FAQ\ndoc_type: faq\n---\n\nQ&A.")
        client = FakeQdrantClient()
        embedder = FakeEmbedder()

        report = await ingest_directory(
            tmp_path,
            store=KnowledgeVectorStore(client, collection="knowledge"),
            embedder=embedder,
        )

        assert report.documents == 2
        assert report.chunks >= 2
        assert report.collection == "knowledge"
        assert report.sources == ["faq.md", "refund-policy.md"]
        assert client.created  # collection ensured before writing
        [(_, points)] = client.upserted
        assert len(points) == report.chunks
        assert len(embedder.batches[0]) == report.chunks
        doc_types = {p.payload["doc_type"] for p in points}
        assert doc_types == {"refund_policy", "faq"}

    async def test_real_seed_corpus_ingests(self):
        """The shipped docs/knowledge corpus must load, chunk, and index."""
        from pathlib import Path

        client = FakeQdrantClient()
        report = await ingest_directory(
            Path("docs/knowledge"),
            store=KnowledgeVectorStore(client, collection="knowledge"),
            embedder=FakeEmbedder(),
        )
        assert report.documents == 6
        assert report.chunks >= 6
        doc_types = {
            p.payload["doc_type"] for _, points in client.upserted for p in points
        }
        assert doc_types == {
            "refund_policy",
            "sla",
            "faq",
            "product_doc",
            "troubleshooting",
            "runbook",
        }


class TestRetriever:
    async def test_search_embeds_query_and_passes_settings(self):
        client = FakeQdrantClient(points=[scored_point()])
        embedder = FakeEmbedder()
        retriever = KnowledgeRetriever(
            embedder=embedder, store=KnowledgeVectorStore(client)
        )

        hits = await retriever.search("refund policy")

        assert embedder.batches == [["refund policy"]]
        assert len(hits) == 1
        [query] = client.queries
        assert query["limit"] == get_settings().rag_top_k
        assert query["score_threshold"] == get_settings().rag_score_threshold

    async def test_search_forwards_top_k_and_doc_types(self):
        client = FakeQdrantClient()
        retriever = KnowledgeRetriever(
            embedder=FakeEmbedder(), store=KnowledgeVectorStore(client)
        )
        await retriever.search("locked", top_k=2, doc_types=["runbook"])
        [query] = client.queries
        assert query["limit"] == 2
        [condition] = query["query_filter"].must
        assert condition.match.any == ["runbook"]
