"""Tests for the MCP tool adapters and retry policy (SRS §31, §41)."""

import json

import pytest

from app.config.settings import get_settings
from app.graph.constants import AgentName
from app.graph.tools import (
    AGENT_TOOL_NAMES,
    build_agent_tools,
    call_mcp_tool_with_retry,
)


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """Zero backoff so retry tests run instantly."""
    monkeypatch.setattr(get_settings(), "mcp_retry_backoff_seconds", 0.0)


class TestAgentToolSets:
    """SRS §30.3-§30.5: each agent binds only its allowed tools."""

    def test_billing_agent_tools(self, fake_mcp_client_factory):
        tools = build_agent_tools(
            fake_mcp_client_factory(), AgentName.BILLING, workflow_id="wf"
        )
        assert [t.name for t in tools] == [
            "billing_get_invoice",
            "billing_get_subscription",
            "billing_calculate_refund",
        ]

    def test_account_agent_tools(self, fake_mcp_client_factory):
        tools = build_agent_tools(
            fake_mcp_client_factory(), AgentName.ACCOUNT, workflow_id="wf"
        )
        assert [t.name for t in tools] == [
            "account_get_customer",
            "account_unlock_dashboard",
            "account_update_feature_flag",
        ]

    def test_technical_agent_binds_only_semantic_search(
        self, fake_mcp_client_factory
    ):
        """SRS §30.5 lists knowledge_semantic_search as the only tool."""
        tools = build_agent_tools(
            fake_mcp_client_factory(), AgentName.TECHNICAL, workflow_id="wf"
        )
        assert [t.name for t in tools] == ["knowledge_semantic_search"]

    @pytest.mark.parametrize(
        "agent", [AgentName.POLICY, AgentName.RESPONSE, AgentName.SUPERVISOR]
    )
    def test_non_domain_agents_bind_no_tools(self, fake_mcp_client_factory, agent):
        assert build_agent_tools(
            fake_mcp_client_factory(), agent, workflow_id="wf"
        ) == []

    def test_every_allowed_tool_has_a_spec(self):
        from app.graph.tools import _TOOL_SPECS

        for names in AGENT_TOOL_NAMES.values():
            for name in names:
                assert name in _TOOL_SPECS


class TestToolExecution:
    async def test_tool_calls_client_and_injects_workflow_id(
        self, fake_mcp_client_factory
    ):
        client = fake_mcp_client_factory(
            {"billing_get_invoice": {"id": "inv-1", "payment_status": "duplicate"}}
        )
        tools = build_agent_tools(client, AgentName.BILLING, workflow_id="wf-42")

        raw = await tools[0].coroutine(invoice_id="inv-1")

        assert json.loads(raw)["payment_status"] == "duplicate"
        name, arguments = client.calls[0]
        assert name == "billing_get_invoice"
        assert arguments["workflow_id"] == "wf-42"
        assert arguments["invoice_id"] == "inv-1"


class TestRetryPolicy:
    """SRS §41: retry recoverable failures only, max 3, log every retry."""

    async def test_success_is_not_retried(self, fake_mcp_client_factory):
        client = fake_mcp_client_factory({"t": {"ok": True}})
        result = await call_mcp_tool_with_retry(client, "t", {}, workflow_id="wf")
        assert result == {"ok": True}
        assert len(client.calls) == 1

    @pytest.mark.parametrize("code", ["invalid_input", "not_found"])
    async def test_structured_business_errors_are_not_retried(
        self, fake_mcp_client_factory, code
    ):
        client = fake_mcp_client_factory({"t": {"error": "nope", "code": code}})
        result = await call_mcp_tool_with_retry(client, "t", {}, workflow_id="wf")
        assert result["code"] == code
        assert len(client.calls) == 1

    async def test_timeout_is_retried_until_success(self, fake_mcp_client_factory):
        client = fake_mcp_client_factory(
            {
                "t": [
                    {"error": "timed out", "code": "timeout"},
                    {"ok": True},
                ]
            }
        )
        result = await call_mcp_tool_with_retry(client, "t", {}, workflow_id="wf")
        assert result == {"ok": True}
        assert len(client.calls) == 2

    async def test_transport_error_is_retried_until_success(
        self, fake_mcp_client_factory
    ):
        client = fake_mcp_client_factory(
            {"t": [ConnectionError("server down"), {"ok": True}]}
        )
        result = await call_mcp_tool_with_retry(client, "t", {}, workflow_id="wf")
        assert result == {"ok": True}
        assert len(client.calls) == 2

    async def test_exhausted_retries_return_structured_unavailable(
        self, fake_mcp_client_factory
    ):
        client = fake_mcp_client_factory(
            {"t": {"error": "timed out", "code": "timeout"}}
        )
        result = await call_mcp_tool_with_retry(client, "t", {}, workflow_id="wf")
        assert result["code"] == "unavailable"
        assert len(client.calls) == get_settings().mcp_retry_max_attempts

    async def test_persistent_transport_failure_never_raises(
        self, fake_mcp_client_factory
    ):
        client = fake_mcp_client_factory({"t": ConnectionError("server down")})
        result = await call_mcp_tool_with_retry(client, "t", {}, workflow_id="wf")
        assert result["code"] == "unavailable"
        assert "server down" in result["error"]
