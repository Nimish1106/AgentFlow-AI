"""Tests for LangSmith observability integration (SRS §42)."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from app.config.settings import Settings
from app.graph.tools import call_mcp_tool_with_retry
from app.observability.langsmith import (
    configure_langsmith,
    is_langsmith_enabled,
    reset_for_testing,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Reset LangSmith configuration state before and after each test."""
    from app.config.settings import get_settings

    env_vars = [
        "LANGSMITH_TRACING",
        "LANGSMITH_API_KEY",
        "LANGSMITH_PROJECT",
        "LANGSMITH_ENDPOINT",
        "LANGCHAIN_TRACING_V2",
        "LANGCHAIN_API_KEY",
        "LANGCHAIN_PROJECT",
        "LANGCHAIN_ENDPOINT",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    settings = get_settings()
    monkeypatch.setattr(settings, "langsmith_tracing", False)
    monkeypatch.setattr(settings, "langsmith_api_key", "")

    reset_for_testing()
    yield
    reset_for_testing()
    get_settings.cache_clear()


def test_disabled_by_default(monkeypatch):
    """LangSmith tracing is disabled by default."""
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)

    enabled = configure_langsmith()
    assert not enabled
    assert not is_langsmith_enabled()


def test_enabled_with_env_vars(monkeypatch):
    """LANGSMITH_TRACING=true and API key enables LangSmith and populates env."""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_test_key_123")
    monkeypatch.setenv("LANGSMITH_PROJECT", "test_project")

    enabled = configure_langsmith()
    assert enabled
    assert is_langsmith_enabled()
    assert os.getenv("LANGCHAIN_TRACING_V2") == "true"
    assert os.getenv("LANGCHAIN_API_KEY") == "lsv2_pt_test_key_123"
    assert os.getenv("LANGCHAIN_PROJECT") == "test_project"


def test_enabled_with_langchain_prefix(monkeypatch):
    """LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY also enables tracing."""
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "lsv2_pt_langchain_key")

    enabled = configure_langsmith()
    assert enabled
    assert is_langsmith_enabled()
    assert os.getenv("LANGSMITH_TRACING") == "true"
    assert os.getenv("LANGSMITH_API_KEY") == "lsv2_pt_langchain_key"


def test_requested_without_api_key_stays_disabled(monkeypatch, caplog):
    """Tracing requested without an API key logs a warning and stays disabled."""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)

    enabled = configure_langsmith()
    assert not enabled
    assert not is_langsmith_enabled()
    assert "no API key provided" in caplog.text


def test_settings_override(monkeypatch):
    """Pydantic Settings instance properties control LangSmith configuration."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    custom_settings = Settings(
        langsmith_tracing=True,
        langsmith_api_key="lsv2_pt_custom",
        langsmith_project="custom_proj",
    )

    with patch("app.observability.langsmith.get_settings", return_value=custom_settings):
        enabled = configure_langsmith()
        assert enabled
        assert os.getenv("LANGCHAIN_PROJECT") == "custom_proj"


@pytest.mark.asyncio
async def test_traceable_mcp_tool_wrapper():
    """call_mcp_tool_with_retry executes cleanly with @traceable decorator."""
    mock_client = AsyncMock()
    mock_client.call_tool.return_value = {"status": "ok", "data": "test_data"}

    res = await call_mcp_tool_with_retry(
        mock_client,
        "billing_get_invoice",
        {"invoice_id": "inv-101"},
        workflow_id="wf-test-uuid",
    )

    assert res == {"status": "ok", "data": "test_data"}
    mock_client.call_tool.assert_called_once_with(
        "billing_get_invoice",
        {"invoice_id": "inv-101", "workflow_id": "wf-test-uuid"},
    )
