"""Unit tests for the Qdrant-backed KnowledgeService (RAG contract, SRS §33)."""

import pytest

from app.rag.schemas import RetrievedChunk
from app.services.knowledge_service import (
    INSUFFICIENT_INFORMATION,
    OK,
    POLICY_DOC_TYPES,
    RUNBOOK_DOC_TYPES,
    KnowledgeService,
)


def hit(**overrides) -> RetrievedChunk:
    payload = {
        "text": "Duplicate charges are refunded in full.",
        "source": "refund-policy.md",
        "title": "Refund Policy",
        "doc_type": "refund_policy",
        "score": 0.81234,
    }
    payload.update(overrides)
    return RetrievedChunk(**payload)


class TestGroundedSearch:
    async def test_semantic_search_returns_results_with_citations(
        self, fake_retriever_factory
    ):
        retriever = fake_retriever_factory(hits=[hit()])
        result = await KnowledgeService(retriever).semantic_search("refunds")

        assert result["status"] == OK
        assert result["collection"] == "knowledge"
        [citation] = result["results"]
        assert citation["source"] == "refund-policy.md"
        assert citation["title"] == "Refund Policy"
        assert citation["score"] == 0.8123
        assert "refunded in full" in citation["text"]

    async def test_semantic_search_is_unfiltered_and_forwards_top_k(
        self, fake_retriever_factory
    ):
        retriever = fake_retriever_factory(hits=[hit()])
        await KnowledgeService(retriever).semantic_search("refunds", top_k=3)
        assert retriever.calls == [
            {"query": "refunds", "top_k": 3, "doc_types": None}
        ]

    async def test_search_policy_filters_policy_doc_types(
        self, fake_retriever_factory
    ):
        retriever = fake_retriever_factory(hits=[hit(doc_type="sla")])
        result = await KnowledgeService(retriever).search_policy("uptime credits")
        assert result["status"] == OK
        assert result["collection"] == "policies"
        assert retriever.calls[0]["doc_types"] == POLICY_DOC_TYPES

    async def test_search_runbook_filters_runbook_doc_types(
        self, fake_retriever_factory
    ):
        retriever = fake_retriever_factory(hits=[hit(doc_type="runbook")])
        result = await KnowledgeService(retriever).search_runbook("billing dispute")
        assert result["status"] == OK
        assert result["collection"] == "runbooks"
        assert retriever.calls[0]["doc_types"] == RUNBOOK_DOC_TYPES


class TestInsufficientInformation:
    """SRS §33: no relevant context -> insufficient information, never fabricate."""

    @pytest.mark.parametrize(
        ("method", "collection"),
        [
            ("semantic_search", "knowledge"),
            ("search_policy", "policies"),
            ("search_runbook", "runbooks"),
        ],
    )
    async def test_no_hits_reports_insufficient_information(
        self, fake_retriever_factory, method, collection
    ):
        service = KnowledgeService(fake_retriever_factory(hits=[]))
        result = await getattr(service, method)("something unknown")
        assert result["status"] == INSUFFICIENT_INFORMATION
        assert result["collection"] == collection
        assert result["results"] == []
        assert "Do not answer" in result["message"]


class TestRetrieverErrors:
    async def test_retriever_failure_propagates_for_the_mcp_runtime_to_handle(
        self, fake_retriever_factory
    ):
        """The MCP runtime converts exceptions into structured ToolErrors and
        audits the failure; the service must not swallow them into fake
        'insufficient information' answers."""

        class FailingRetriever:
            async def search(self, query, *, top_k=None, doc_types=None):
                raise ConnectionError("qdrant unreachable")

        with pytest.raises(ConnectionError, match="qdrant unreachable"):
            await KnowledgeService(FailingRetriever()).semantic_search("refunds")
