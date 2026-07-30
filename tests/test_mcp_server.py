"""In-process tests for the Enterprise MCP Server (SRS §31).

Tools are exercised through a real MCP ClientSession connected over in-memory
streams — no network, no running server — against the aiosqlite test database
injected via the runtime session factory.
"""

import json
import uuid
from decimal import Decimal

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from sqlalchemy import select

import app.mcp.server.runtime as mcp_runtime
from app.mcp.server.main import create_mcp_server
from app.models import AuditLog, Invoice, SupportTicket, User
from app.models.enums import AccountStatus, PaymentStatus

EXPECTED_TOOLS = {
    "billing_get_invoice",
    "billing_get_subscription",
    "billing_calculate_refund",
    "account_get_customer",
    "account_unlock_dashboard",
    "account_update_feature_flag",
    "ticket_get_ticket",
    "ticket_update_ticket",
    "ticket_add_internal_note",
    "knowledge_semantic_search",
    "knowledge_search_policy",
    "knowledge_search_runbook",
}


async def _seed(session_factory) -> dict:
    async with session_factory() as session:
        user = User(
            company_name="Acme Corp",
            full_name="Alice Admin",
            email=f"{uuid.uuid4()}@acme.test",
            account_status=AccountStatus.LOCKED,
        )
        session.add(user)
        await session.flush()
        invoice = Invoice(
            user_id=user.id,
            amount=Decimal("199.99"),
            payment_status=PaymentStatus.DUPLICATE,
        )
        ticket = SupportTicket(
            customer_id=user.id,
            title="Charged twice",
            description="Duplicate invoice.",
        )
        session.add_all([invoice, ticket])
        await session.commit()
        return {
            "customer_id": str(user.id),
            "invoice_id": str(invoice.id),
            "ticket_id": str(ticket.id),
        }


def _payload(result) -> dict:
    if result.structuredContent is not None:
        payload = result.structuredContent
        return payload.get("result", payload)
    return json.loads(result.content[0].text)


async def _audit_rows(session_factory) -> list[AuditLog]:
    async with session_factory() as session:
        rows = await session.scalars(select(AuditLog))
        return list(rows)


@pytest.fixture
def mcp_server(mcp_session_factory):  # noqa: ARG001 - factory wiring is the point
    return create_mcp_server()


async def test_lists_all_twelve_tools(mcp_server):
    async with create_connected_server_and_client_session(mcp_server) as client:
        result = await client.list_tools()
        assert {tool.name for tool in result.tools} == EXPECTED_TOOLS


async def test_billing_tools_end_to_end(mcp_server, mcp_session_factory):
    ids = await _seed(mcp_session_factory)
    async with create_connected_server_and_client_session(mcp_server) as client:
        invoice = _payload(
            await client.call_tool(
                "billing_get_invoice", {"invoice_id": ids["invoice_id"]}
            )
        )
        assert invoice["payment_status"] == "duplicate"

        refund = _payload(
            await client.call_tool(
                "billing_calculate_refund", {"invoice_id": ids["invoice_id"]}
            )
        )
        assert refund["eligible"] is True
        assert Decimal(str(refund["refund_amount"])) == Decimal("199.99")

    audits = await _audit_rows(mcp_session_factory)
    assert len(audits) == 2
    assert all(a.performed_by == "enterprise-mcp" for a in audits)
    assert all(a.workflow_id is None for a in audits)
    assert all(json.loads(a.action)["status"] == "success" for a in audits)


async def test_account_unlock_and_feature_flag(mcp_server, mcp_session_factory):
    ids = await _seed(mcp_session_factory)
    async with create_connected_server_and_client_session(mcp_server) as client:
        unlock = _payload(
            await client.call_tool(
                "account_unlock_dashboard", {"customer_id": ids["customer_id"]}
            )
        )
        assert unlock["unlocked"] is True

        flag = _payload(
            await client.call_tool(
                "account_update_feature_flag",
                {
                    "customer_id": ids["customer_id"],
                    "flag_name": "beta",
                    "enabled": True,
                },
            )
        )
        assert flag["feature_flags"] == {"beta": True}

        customer = _payload(
            await client.call_tool(
                "account_get_customer", {"customer_id": ids["customer_id"]}
            )
        )
        assert customer["account_status"] == "active"
        assert customer["feature_flags"] == {"beta": True}


async def test_ticket_update_and_note(mcp_server, mcp_session_factory):
    ids = await _seed(mcp_session_factory)
    async with create_connected_server_and_client_session(mcp_server) as client:
        updated = _payload(
            await client.call_tool(
                "ticket_update_ticket",
                {"ticket_id": ids["ticket_id"], "status": "in_progress"},
            )
        )
        assert updated["status"] == "in_progress"

        note = _payload(
            await client.call_tool(
                "ticket_add_internal_note",
                {
                    "ticket_id": ids["ticket_id"],
                    "author": "billing_agent",
                    "note": "Refund eligible.",
                },
            )
        )
        assert note["author"] == "billing_agent"

        invalid = _payload(
            await client.call_tool(
                "ticket_update_ticket",
                {"ticket_id": ids["ticket_id"], "status": "nonsense"},
            )
        )
        assert invalid["code"] == "invalid_input"


async def test_knowledge_tools_report_insufficient_information(
    mcp_server, mcp_session_factory, monkeypatch, fake_retriever_factory
):
    import app.services.knowledge_service as knowledge_service

    retriever = fake_retriever_factory(hits=[])
    monkeypatch.setattr(knowledge_service, "get_retriever", lambda: retriever)

    async with create_connected_server_and_client_session(mcp_server) as client:
        for tool in (
            "knowledge_semantic_search",
            "knowledge_search_policy",
            "knowledge_search_runbook",
        ):
            payload = _payload(await client.call_tool(tool, {"query": "refunds"}))
            assert payload["status"] == "insufficient_information"
            assert payload["results"] == []


async def test_knowledge_search_returns_grounded_results_with_citations(
    mcp_server, mcp_session_factory, monkeypatch, fake_retriever_factory
):
    from app.rag.schemas import RetrievedChunk

    import app.services.knowledge_service as knowledge_service

    retriever = fake_retriever_factory(
        hits=[
            RetrievedChunk(
                text="Duplicate charges are refunded in full.",
                source="refund-policy.md",
                title="Refund Policy",
                doc_type="refund_policy",
                score=0.82,
            )
        ]
    )
    monkeypatch.setattr(knowledge_service, "get_retriever", lambda: retriever)

    async with create_connected_server_and_client_session(mcp_server) as client:
        payload = _payload(
            await client.call_tool(
                "knowledge_semantic_search", {"query": "duplicate charge refund"}
            )
        )
    assert payload["status"] == "ok"
    [citation] = payload["results"]
    assert citation["source"] == "refund-policy.md"
    assert citation["score"] == 0.82

    audits = await _audit_rows(mcp_session_factory)
    assert len(audits) == 1
    assert json.loads(audits[0].action)["status"] == "success"


async def test_not_found_returns_structured_error_and_audits_failure(
    mcp_server, mcp_session_factory
):
    async with create_connected_server_and_client_session(mcp_server) as client:
        payload = _payload(
            await client.call_tool(
                "billing_get_invoice", {"invoice_id": str(uuid.uuid4())}
            )
        )
        assert payload["code"] == "not_found"

        payload = _payload(
            await client.call_tool(
                "billing_get_invoice", {"invoice_id": "not-a-uuid"}
            )
        )
        assert payload["code"] == "invalid_input"

    audits = await _audit_rows(mcp_session_factory)
    assert len(audits) == 2
    assert all(json.loads(a.action)["status"] == "failed" for a in audits)


async def test_workflow_id_recorded_in_audit(mcp_server, mcp_session_factory):
    ids = await _seed(mcp_session_factory)
    # No FK target needed: audit_logs.workflow_id is nullable and unconstrained
    # in SQLite tests; use a ticket-linked workflow row in Postgres.
    async with create_connected_server_and_client_session(mcp_server) as client:
        await client.call_tool(
            "account_get_customer",
            {"customer_id": ids["customer_id"], "workflow_id": str(uuid.uuid4())},
        )

    audits = await _audit_rows(mcp_session_factory)
    assert len(audits) == 1
    assert audits[0].workflow_id is not None


async def test_timeout_returns_structured_error(
    mcp_server, mcp_session_factory, monkeypatch
):
    from app.services.billing_service import BillingService

    async def slow_get_invoice(self, invoice_id):  # noqa: ARG001
        import asyncio

        await asyncio.sleep(5)

    monkeypatch.setattr(BillingService, "get_invoice", slow_get_invoice)
    settings = mcp_runtime.get_settings()
    monkeypatch.setattr(settings, "mcp_tool_timeout_seconds", 0.05)

    async with create_connected_server_and_client_session(mcp_server) as client:
        payload = _payload(
            await client.call_tool(
                "billing_get_invoice", {"invoice_id": str(uuid.uuid4())}
            )
        )
    assert payload["code"] == "timeout"

    audits = await _audit_rows(mcp_session_factory)
    assert len(audits) == 1
    assert json.loads(audits[0].action)["status"] == "failed"
