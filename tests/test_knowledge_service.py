"""Unit tests for KnowledgeService Phase 3 stubs (RAG contract, SRS §33)."""

import pytest

from app.services.knowledge_service import (
    INSUFFICIENT_INFORMATION,
    KnowledgeService,
)


@pytest.mark.parametrize(
    ("method", "collection"),
    [
        ("semantic_search", "knowledge"),
        ("search_policy", "policies"),
        ("search_runbook", "runbooks"),
    ],
)
async def test_searches_report_insufficient_information(method, collection):
    result = await getattr(KnowledgeService(), method)("refund policy")
    assert result["status"] == INSUFFICIENT_INFORMATION
    assert result["collection"] == collection
    assert result["results"] == []
    assert result["query"] == "refund policy"
    assert "insufficient" in result["status"]
