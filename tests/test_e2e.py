"""End-to-end workflow integration tests (SRS §45, §49).

Scope
-----
These exercise the whole pipeline as one system:

    POST /tickets -> Redis stream -> WorkflowConsumer -> WorkflowRunner
      -> LangGraph (supervisor -> planner -> domain agents -> policy
         -> aggregator -> risk engine) -> HITL interrupt
      -> POST /approvals/{id} -> resume job -> response -> dispatcher
      -> persisted resolution + audit trail

What is real, and what is not
-----------------------------
Real: the FastAPI app and its routes, ``TicketService``, ``QueueService``, the
Redis stream envelope, ``WorkflowConsumer`` (including consumer-group semantics
and acknowledgement), ``WorkflowRunner``, the compiled LangGraph with every node
and edge, the checkpointer, the MCP tool runtime with its audit writes, and the
real database schema.

Substituted, because they are external services a unit suite cannot require:

- **The LLM.** Groq needs an API key and a network. ``ScriptedLLM`` returns the
  structured outcomes the real agents would produce, so the graph's topology,
  reducers, routing and governance all execute for real.
- **Qdrant.** ``FakeRetriever`` returns fixed chunks, so the RAG contract
  (retrieve-then-generate, citations, insufficient-information) is exercised
  without a vector database.
- **Redis.** ``FakeRedisStream`` implements the Streams subset the consumer
  uses - XADD/XREADGROUP/XACK plus consumer groups and pending-entry tracking -
  so the real consumer code runs unmodified.

These tests therefore prove the *system wiring*: that a ticket submitted over
HTTP reaches the graph, pauses for a human, resumes on approval, and lands as a
persisted resolution with a complete audit trail. They do not prove the Groq
model behaves well, which no offline test can.
"""

import json
import uuid
from datetime import date
from typing import Dict, List, Optional, Tuple

import pytest
import pytest_asyncio

import app.mcp.server.runtime as mcp_runtime
from app.agents.schemas import AgentOutcome, PolicyOutcome, ResponseOutcome
from app.dispatcher.consumer import WorkflowConsumer
from app.dispatcher.runner import WorkflowRunner
from app.graph.nodes.supervisor import SupervisorClassification
from app.graph.workflow import build_workflow_graph
from app.models import (
    AgentExecutionLog,
    AuditLog,
    Invoice,
    Subscription,
    SupportTicket,
    User,
    WorkflowRun,
)
from app.models.enums import (
    PaymentStatus,
    SubscriptionPlan,
    TicketStatus,
    WorkflowStatus,
)
from app.rag.schemas import RetrievedChunk
from app.services.queue_service import KIND_RESUME, KIND_START


# --------------------------------------------------------------------------- #
# Test doubles for the three external services.
# --------------------------------------------------------------------------- #


class FakeRedisStream:
    """In-memory Redis Streams double covering the consumer's usage.

    Implements enough of the real semantics to make the consumer's behaviour
    meaningful: entries are ordered, a consumer group tracks its read position,
    delivered-but-unacked entries stay pending, and XACK clears them. Without
    the pending set, the acknowledgement policy could not be asserted at all.
    """

    def __init__(self) -> None:
        self.entries: List[Tuple[str, Dict]] = []
        self.groups: Dict[str, int] = {}
        self.pending: Dict[str, Dict[str, Dict]] = {}
        self._sequence = 0

    async def xadd(self, stream: str, fields: Dict) -> str:  # noqa: ARG002
        self._sequence += 1
        entry_id = f"{self._sequence}-0"
        self.entries.append((entry_id, dict(fields)))
        return entry_id

    async def xgroup_create(self, stream, group, id="0", mkstream=False):  # noqa: A002, ARG002
        from redis.exceptions import ResponseError

        if group in self.groups:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.groups[group] = 0
        self.pending[group] = {}

    async def xreadgroup(self, group, consumer, streams, count=1, block=None):  # noqa: ARG002
        # The real server errors on an unknown group; the consumer always calls
        # ensure_group() first, so tolerate it being absent by registering it.
        self.groups.setdefault(group, 0)
        self.pending.setdefault(group, {})
        position = self.groups[group]
        if position >= len(self.entries):
            return []
        batch = self.entries[position : position + count]
        self.groups[group] = position + len(batch)
        for entry_id, fields in batch:
            self.pending[group][entry_id] = fields
        return [("stream", batch)]

    async def xack(self, stream, group, entry_id) -> int:  # noqa: ARG002
        return 1 if self.pending.get(group, {}).pop(entry_id, None) else 0

    async def ping(self) -> bool:
        return True

    def pending_count(self, group: str) -> int:
        return len(self.pending.get(group, {}))


class ScriptedLLM:
    """Chat model returning per-schema outcomes, with tool-call scripting.

    One instance serves every reasoning node in a full graph run: each node asks
    for its own output schema, so the schema identifies the caller.
    """

    def __init__(self, outcomes: Dict, tool_call_batches: Optional[List] = None) -> None:
        self.outcomes = outcomes
        self.tool_call_batches = list(tool_call_batches or [])
        self.structured_calls: List = []
        self.bound_tools: List = []

    def bind_tools(self, tools, **kwargs):  # noqa: ARG002
        self.bound_tools.append(list(tools))
        return _BoundScriptedLLM(self)

    def with_structured_output(self, schema, **kwargs):  # noqa: ARG002
        return _StructuredScriptedLLM(self, schema)


class _BoundScriptedLLM:
    def __init__(self, parent: ScriptedLLM) -> None:
        self._parent = parent

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        from langchain_core.messages import AIMessage

        if self._parent.tool_call_batches:
            return AIMessage(
                content="", tool_calls=self._parent.tool_call_batches.pop(0)
            )
        return AIMessage(content="done")


class _StructuredScriptedLLM:
    def __init__(self, parent: ScriptedLLM, schema) -> None:
        self._parent = parent
        self._schema = schema

    async def ainvoke(self, messages, **kwargs):  # noqa: ARG002
        self._parent.structured_calls.append(self._schema)
        try:
            return self._parent.outcomes[self._schema]
        except KeyError as exc:
            raise AssertionError(
                f"no scripted outcome for {self._schema.__name__}"
            ) from exc


class RecordingRetriever:
    """Knowledge retriever double that records what was searched."""

    def __init__(self, hits: Optional[List[RetrievedChunk]] = None) -> None:
        self.hits = list(hits or [])
        self.queries: List[str] = []

    async def search(self, query, *, top_k=None, doc_types=None):  # noqa: ARG002
        self.queries.append(query)
        return list(self.hits)


# --------------------------------------------------------------------------- #
# Scenario fixtures.
# --------------------------------------------------------------------------- #


def duplicate_charge_outcomes(*, approved: bool, risk: str) -> Dict:
    """Outcomes for the canonical SRS §13 duplicate-charge scenario."""
    return {
        SupervisorClassification: SupervisorClassification(
            intent="Duplicate Charge", domains=["billing"], priority="high"
        ),
        AgentOutcome: AgentOutcome(
            summary="Invoice INV-9 is a confirmed duplicate charge.",
            confidence=0.95,
            actions_taken=["looked_up_invoice", "calculated_refund"],
            output_data={"refund_eligible": True, "refund_amount": 5000.0},
        ),
        PolicyOutcome: PolicyOutcome(
            summary=(
                "Refund complies with the duplicate-payment policy."
                if approved
                else "Refund exceeds the auto-approval limit."
            ),
            confidence=0.9,
            actions_taken=["evaluated_policy"],
            output_data={},
            approved=approved,
            risk=risk,
        ),
        ResponseOutcome: ResponseOutcome(
            customer_response=(
                "We confirmed the duplicate charge and issued your refund."
            ),
            internal_note="Duplicate refund processed after human approval.",
            resolution_summary="Duplicate charge refunded.",
            confidence=0.93,
        ),
    }


@pytest_asyncio.fixture
async def customer(session_factory):
    """An enterprise customer with a subscription and a duplicate invoice."""
    async with session_factory() as session:
        user = User(
            company_name="Initech",
            full_name="Paul Carr",
            email=f"paul-{uuid.uuid4().hex[:8]}@initech.test",
        )
        session.add(user)
        await session.flush()
        session.add(
            Subscription(
                user_id=user.id,
                plan=SubscriptionPlan.ENTERPRISE,
                monthly_price=5000,
                renewal_date=date(2026, 12, 1),
            )
        )
        session.add(
            Invoice(
                user_id=user.id,
                amount=5000,
                currency="USD",
                payment_status=PaymentStatus.DUPLICATE,
            )
        )
        await session.commit()
        return user.id


@pytest_asyncio.fixture
async def e2e(session_factory, customer, monkeypatch):
    """Assemble the full pipeline with only external services substituted."""
    from app.database.redis import get_redis
    from app.database.session import get_db
    from app.main import app
    from httpx import ASGITransport, AsyncClient

    redis_client = FakeRedisStream()
    retriever = RecordingRetriever(
        hits=[
            RetrievedChunk(
                text="Duplicate payments are refunded in full within 5 business days.",
                source="refund-policy.md",
                title="Refund Policy",
                doc_type="refund_policy",
                score=0.91,
            )
        ]
    )

    # The MCP tool runtime and the knowledge service reach real infrastructure;
    # point them at the test database and the fake retriever.
    mcp_runtime.set_session_factory(session_factory)
    import app.rag.retriever as retriever_module

    monkeypatch.setattr(retriever_module, "get_retriever", lambda: retriever)

    async def override_db():
        async with session_factory() as session:
            yield session

    async def override_redis():
        yield redis_client

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = override_redis

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield {
            "client": client,
            "redis": redis_client,
            "retriever": retriever,
            "session_factory": session_factory,
            "customer_id": customer,
        }

    app.dependency_overrides.clear()
    mcp_runtime._session_factory = None


def build_pipeline(e2e, outcomes, tool_call_batches=None, mcp_client=None):
    """Wire a consumer over the real graph with a scripted LLM."""
    llm = ScriptedLLM(outcomes, tool_call_batches)
    graph = build_workflow_graph(llm=llm, mcp_client=mcp_client)
    runner = WorkflowRunner(graph, e2e["session_factory"])
    consumer = WorkflowConsumer(
        e2e["redis"], runner, group="e2e-group", consumer_name="e2e-1"
    )
    return llm, consumer


async def submit_ticket(e2e, subject="Charged twice", description="Duplicate charge."):
    """POST a ticket through the real API and return its workflow id."""
    response = await e2e["client"].post(
        "/tickets",
        json={
            "customer_id": str(e2e["customer_id"]),
            "subject": subject,
            "description": description,
        },
    )
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["workflow_id"])


def _tool_payload(result) -> Dict:
    """Unwrap an MCP tool result into its dict payload."""
    if result.structuredContent is not None:
        payload = result.structuredContent
        return payload.get("result", payload)
    return json.loads(result.content[0].text)


async def load_audit_events(session_factory, workflow_id) -> List[Dict]:
    """Every audit row for a workflow, parsed.

    Returned in whatever order the database yields. Audit rows are deliberately
    *not* ordered here: ``timestamp`` cannot separate them (SQLite's
    CURRENT_TIMESTAMP has one-second resolution, and Postgres' ``now()`` is
    transaction-scoped, so rows written in quick succession share a value) and
    ``id`` is a random UUID4. Tests therefore assert which events exist and what
    they contain, and use the workflow's own state transitions - which *are*
    ordered - to assert sequence.
    """
    from sqlalchemy import select

    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(AuditLog).where(AuditLog.workflow_id == workflow_id)
            )
        )
    events = []
    for row in rows:
        try:
            payload = json.loads(row.action)
        except (TypeError, ValueError):
            payload = {"raw": row.action}
        payload["_performed_by"] = row.performed_by
        events.append(payload)
    return events


# --------------------------------------------------------------------------- #
# Tests.
# --------------------------------------------------------------------------- #


class TestHappyPath:
    """Ticket -> queue -> graph -> response -> dispatch, with no human needed."""

    async def test_low_risk_ticket_completes_without_human_approval(self, e2e):
        outcomes = duplicate_charge_outcomes(approved=True, risk="low")
        # A modest refund under the HITL threshold keeps the run automatic.
        outcomes[AgentOutcome] = AgentOutcome(
            summary="Invoice INV-1 is a confirmed duplicate charge.",
            confidence=0.95,
            actions_taken=["looked_up_invoice"],
            output_data={"refund_eligible": True, "refund_amount": 49.0},
        )
        _, consumer = build_pipeline(e2e, outcomes)

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        async with e2e["session_factory"]() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
            ticket = await session.get(SupportTicket, workflow.ticket_id)

        assert workflow.workflow_status is WorkflowStatus.COMPLETED
        assert workflow.current_node == "dispatcher"
        assert ticket.status is TicketStatus.RESOLVED
        assert "refund" in ticket.resolution.lower()

    async def test_the_api_returns_202_before_the_graph_runs(self, e2e):
        """SRS §36: POST /tickets must not block on execution."""
        build_pipeline(e2e, duplicate_charge_outcomes(approved=True, risk="low"))

        workflow_id = await submit_ticket(e2e)

        # The job is queued but nothing has consumed it yet.
        async with e2e["session_factory"]() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
        assert workflow.workflow_status is WorkflowStatus.PENDING
        assert len(e2e["redis"].entries) == 1
        assert e2e["redis"].entries[0][1]["kind"] == KIND_START

    async def test_every_node_is_recorded_in_the_execution_trace(self, e2e):
        outcomes = duplicate_charge_outcomes(approved=True, risk="low")
        outcomes[AgentOutcome] = AgentOutcome(
            summary="Duplicate confirmed.",
            confidence=0.95,
            actions_taken=[],
            output_data={"refund_eligible": True, "refund_amount": 49.0},
        )
        _, consumer = build_pipeline(e2e, outcomes)

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        from sqlalchemy import select

        async with e2e["session_factory"]() as session:
            logs = list(
                await session.scalars(
                    select(AgentExecutionLog)
                    .where(AgentExecutionLog.workflow_id == workflow_id)
                    .order_by(AgentExecutionLog.sequence)
                )
            )
        names = [log.agent_name for log in logs]
        assert names == [
            "supervisor",
            "task_planner",
            "billing_agent",
            "policy_agent",
            "results_aggregator",
            "risk_engine",
            "response_agent",
            "dispatcher",
        ]
        assert [log.sequence for log in logs] == list(range(len(logs)))


class TestHitlPauseAndResume:
    """SRS §38: a risky workflow pauses, a human decides, the graph resumes."""

    async def test_high_risk_workflow_pauses_for_a_human(self, e2e):
        outcomes = duplicate_charge_outcomes(approved=False, risk="high")
        _, consumer = build_pipeline(e2e, outcomes)

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        async with e2e["session_factory"]() as session:
            workflow = await session.get(WorkflowRun, workflow_id)

        assert workflow.workflow_status is WorkflowStatus.WAITING_FOR_HITL
        # The reviewer's packet must be persisted before review is advertised.
        assert workflow.risk_assessment["level"] == "high"
        assert workflow.risk_assessment["requires_hitl"] is True
        assert workflow.risk_assessment["reasons"]

    async def test_no_customer_response_is_written_before_approval(self, e2e):
        """A paused workflow must not have told the customer anything yet."""
        _, consumer = build_pipeline(
            e2e, duplicate_charge_outcomes(approved=False, risk="high")
        )

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        async with e2e["session_factory"]() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
            ticket = await session.get(SupportTicket, workflow.ticket_id)
        assert ticket.resolution is None
        assert ticket.status is not TicketStatus.RESOLVED

    async def test_approval_resumes_and_completes_the_workflow(self, e2e):
        """The full pause -> approve -> resume -> dispatch cycle."""
        outcomes = duplicate_charge_outcomes(approved=False, risk="high")
        _, consumer = build_pipeline(e2e, outcomes)

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        response = await e2e["client"].post(
            f"/approvals/{workflow_id}",
            json={
                "approved": True,
                "reviewer_name": "Support Manager",
                "comments": "Duplicate verified against the invoice.",
            },
        )
        assert response.status_code == 200
        assert response.json()["approval_status"] == "approved"

        # The endpoint only queues; the dispatcher runs the graph (SRS §46).
        assert e2e["redis"].entries[-1][1]["kind"] == KIND_RESUME
        await consumer.process_batch()

        async with e2e["session_factory"]() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
            ticket = await session.get(SupportTicket, workflow.ticket_id)

        assert workflow.workflow_status is WorkflowStatus.COMPLETED
        assert ticket.status is TicketStatus.RESOLVED
        assert ticket.resolution

    async def test_resume_appends_to_the_trace_without_rewriting_history(self, e2e):
        """Execution history is append-only across a resume (SRS §18.6)."""
        from sqlalchemy import select

        _, consumer = build_pipeline(
            e2e, duplicate_charge_outcomes(approved=False, risk="high")
        )

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        async with e2e["session_factory"]() as session:
            before = list(
                await session.scalars(
                    select(AgentExecutionLog.agent_name)
                    .where(AgentExecutionLog.workflow_id == workflow_id)
                    .order_by(AgentExecutionLog.sequence)
                )
            )

        await e2e["client"].post(
            f"/approvals/{workflow_id}",
            json={"approved": True, "reviewer_name": "Manager", "comments": ""},
        )
        await consumer.process_batch()

        async with e2e["session_factory"]() as session:
            after = list(
                await session.scalars(
                    select(AgentExecutionLog)
                    .where(AgentExecutionLog.workflow_id == workflow_id)
                    .order_by(AgentExecutionLog.sequence)
                )
            )

        # The pre-pause prefix is unchanged, and the tail was appended.
        assert [log.agent_name for log in after][: len(before)] == before
        assert len(after) > len(before)
        assert [log.sequence for log in after] == list(range(len(after)))
        assert "human_approval" in [log.agent_name for log in after]

    async def test_rejection_still_completes_the_workflow(self, e2e):
        """A rejected action is still a resolution: the customer is answered."""
        outcomes = duplicate_charge_outcomes(approved=False, risk="high")
        outcomes[ResponseOutcome] = ResponseOutcome(
            customer_response="Your refund request is under further review.",
            internal_note="Rejected by reviewer.",
            resolution_summary="Refund declined pending investigation.",
            confidence=0.8,
        )
        _, consumer = build_pipeline(e2e, outcomes)

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()
        await e2e["client"].post(
            f"/approvals/{workflow_id}",
            json={"approved": False, "reviewer_name": "Manager", "comments": "No."},
        )
        await consumer.process_batch()

        async with e2e["session_factory"]() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
        assert workflow.workflow_status is WorkflowStatus.COMPLETED

        events = await load_audit_events(e2e["session_factory"], workflow_id)
        decisions = [e for e in events if e.get("event") == "hitl_decision"]
        assert decisions[0]["approved"] is False

    async def test_approving_a_running_workflow_is_rejected(self, e2e):
        """SRS §38: only a parked workflow may be approved."""
        outcomes = duplicate_charge_outcomes(approved=True, risk="low")
        outcomes[AgentOutcome] = AgentOutcome(
            summary="Duplicate confirmed.",
            confidence=0.95,
            actions_taken=[],
            output_data={"refund_eligible": True, "refund_amount": 49.0},
        )
        _, consumer = build_pipeline(e2e, outcomes)

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()  # runs to completion, never pauses

        response = await e2e["client"].post(
            f"/approvals/{workflow_id}",
            json={"approved": True, "reviewer_name": "Manager", "comments": ""},
        )
        assert response.status_code == 409


class TestAuditIntegrity:
    """SRS §16.10, §49: every business action leaves an audit trail."""

    async def test_the_full_lifecycle_is_auditable(self, e2e):
        """Every governance-critical action leaves a record.

        Sequence is asserted through the workflow's observable state at each
        step rather than by sorting audit rows: the audit table has no
        monotonic ordering column, and same-second timestamps cannot be
        separated (see ``load_audit_events``).
        """
        _, consumer = build_pipeline(
            e2e, duplicate_charge_outcomes(approved=False, risk="high")
        )

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        # After the pause, the request to review exists and no decision does.
        paused_events = await load_audit_events(e2e["session_factory"], workflow_id)
        paused_recorded = {e.get("event") for e in paused_events}
        assert "hitl_requested" in paused_recorded
        assert "hitl_decision" not in paused_recorded
        assert "workflow_finished" not in paused_recorded

        await e2e["client"].post(
            f"/approvals/{workflow_id}",
            json={
                "approved": True,
                "reviewer_name": "Support Manager",
                "comments": "Verified.",
            },
        )

        # The decision is durable before the resume job is consumed.
        decided_events = await load_audit_events(e2e["session_factory"], workflow_id)
        decided_recorded = {e.get("event") for e in decided_events}
        assert "hitl_decision" in decided_recorded
        assert "workflow_resumed" not in decided_recorded

        await consumer.process_batch()

        final_recorded = {
            e.get("event")
            for e in await load_audit_events(e2e["session_factory"], workflow_id)
        }
        assert "workflow_resumed" in final_recorded
        assert "workflow_finished" in final_recorded

    async def test_the_reviewer_is_identifiable_in_the_audit_trail(self, e2e):
        """An approval that cannot be attributed is not an approval."""
        _, consumer = build_pipeline(
            e2e, duplicate_charge_outcomes(approved=False, risk="high")
        )

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()
        await e2e["client"].post(
            f"/approvals/{workflow_id}",
            json={
                "approved": True,
                "reviewer_name": "Dana Reviewer",
                "comments": "Checked the invoice.",
            },
        )

        events = await load_audit_events(e2e["session_factory"], workflow_id)
        decision = next(e for e in events if e.get("event") == "hitl_decision")
        assert decision["_performed_by"] == "reviewer:Dana Reviewer"
        assert decision["comments"] == "Checked the invoice."

    async def test_hitl_request_records_why_a_human_was_needed(self, e2e):
        _, consumer = build_pipeline(
            e2e, duplicate_charge_outcomes(approved=False, risk="high")
        )

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        events = await load_audit_events(e2e["session_factory"], workflow_id)
        requested = next(e for e in events if e.get("event") == "hitl_requested")
        assert requested["risk_score"] == 0.9
        assert requested["reasons"]

    async def test_mcp_tool_calls_are_audited(self, e2e):
        """SRS §16.10: every enterprise operation is auditable.

        The agent's tool call is routed through the real in-process MCP server,
        so the registered tool, its runtime and its audit write all execute.
        """
        from mcp.shared.memory import create_connected_server_and_client_session

        from app.mcp.server.main import create_mcp_server

        # A real invoice for the agent to look up.
        from sqlalchemy import select

        async with e2e["session_factory"]() as session:
            invoice_id = await session.scalar(select(Invoice.id))

        outcomes = duplicate_charge_outcomes(approved=True, risk="low")
        outcomes[AgentOutcome] = AgentOutcome(
            summary="Duplicate confirmed.",
            confidence=0.95,
            actions_taken=[],
            output_data={"refund_eligible": True, "refund_amount": 49.0},
        )

        async with create_connected_server_and_client_session(
            create_mcp_server()
        ) as mcp_client_session:

            class RoutingMCPClient:
                """EnterpriseMCPClient shape over a live in-process session."""

                def __init__(self):
                    self.calls = []

                async def call_tool(self, name, arguments):
                    self.calls.append((name, arguments))
                    # workflow_id is baked in by build_agent_tools but is not a
                    # parameter of the tool schema itself.
                    args = {k: v for k, v in arguments.items() if k != "workflow_id"}
                    return _tool_payload(
                        await mcp_client_session.call_tool(name, args)
                    )

            client = RoutingMCPClient()
            _, consumer = build_pipeline(
                e2e,
                outcomes,
                tool_call_batches=[
                    [
                        {
                            "name": "billing_get_invoice",
                            "args": {"invoice_id": str(invoice_id)},
                            "id": "call-1",
                            "type": "tool_call",
                        }
                    ]
                ],
                mcp_client=client,
            )

            workflow_id = await submit_ticket(e2e)
            await consumer.process_batch()

        assert client.calls, "the agent never reached the MCP client"
        assert client.calls[0][0] == "billing_get_invoice"

        # The MCP runtime audits every call under its own actor.
        from sqlalchemy import select as sa_select

        async with e2e["session_factory"]() as session:
            rows = list(
                await session.scalars(
                    sa_select(AuditLog).where(
                        AuditLog.performed_by == "enterprise-mcp"
                    )
                )
            )
        assert rows, "no MCP tool call was audited"
        assert json.loads(rows[0].action)["tool"] == "billing_get_invoice"
        assert json.loads(rows[0].action)["status"] == "success"


class TestStateRecovery:
    """SRS §16.9, §49: workflow state is recoverable from its checkpoint."""

    async def test_a_parked_workflow_survives_a_dispatcher_restart(self, e2e):
        """The resume must work from a *new* runner over the same checkpointer.

        This is the restart case: the process that paused the workflow is gone,
        and a fresh dispatcher picks the job up.
        """
        from langgraph.checkpoint.memory import InMemorySaver

        outcomes = duplicate_charge_outcomes(approved=False, risk="high")
        # One saver instance stands in for Postgres-backed checkpoint storage
        # that outlives the process.
        checkpointer = InMemorySaver()

        first_graph = build_workflow_graph(
            llm=ScriptedLLM(outcomes), checkpointer=checkpointer
        )
        first_consumer = WorkflowConsumer(
            e2e["redis"],
            WorkflowRunner(first_graph, e2e["session_factory"]),
            group="restart-group",
            consumer_name="dispatcher-1",
        )

        workflow_id = await submit_ticket(e2e)
        await first_consumer.process_batch()

        async with e2e["session_factory"]() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
        assert workflow.workflow_status is WorkflowStatus.WAITING_FOR_HITL

        # The original dispatcher is gone; a new one rebuilds from the checkpoint.
        second_graph = build_workflow_graph(
            llm=ScriptedLLM(outcomes), checkpointer=checkpointer
        )
        second_consumer = WorkflowConsumer(
            e2e["redis"],
            WorkflowRunner(second_graph, e2e["session_factory"]),
            group="restart-group",
            consumer_name="dispatcher-2",
        )

        await e2e["client"].post(
            f"/approvals/{workflow_id}",
            json={"approved": True, "reviewer_name": "Manager", "comments": ""},
        )
        await second_consumer.process_batch()

        async with e2e["session_factory"]() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
            ticket = await session.get(SupportTicket, workflow.ticket_id)
        assert workflow.workflow_status is WorkflowStatus.COMPLETED
        assert ticket.resolution

    async def test_only_the_remaining_nodes_run_on_resume(self, e2e):
        """A resume continues the workflow; it never restarts it."""
        from sqlalchemy import select

        _, consumer = build_pipeline(
            e2e, duplicate_charge_outcomes(approved=False, risk="high")
        )
        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        await e2e["client"].post(
            f"/approvals/{workflow_id}",
            json={"approved": True, "reviewer_name": "Manager", "comments": ""},
        )
        await consumer.process_batch()

        async with e2e["session_factory"]() as session:
            names = list(
                await session.scalars(
                    select(AgentExecutionLog.agent_name)
                    .where(AgentExecutionLog.workflow_id == workflow_id)
                    .order_by(AgentExecutionLog.sequence)
                )
            )
        # The supervisor ran once, at the start - not again on resume.
        assert names.count("supervisor") == 1
        assert names.count("billing_agent") == 1
        assert names[-1] == "dispatcher"


class TestQueueSemantics:
    """SRS §14, §19: the queue is what decouples the API from execution."""

    async def test_jobs_are_acknowledged_after_processing(self, e2e):
        outcomes = duplicate_charge_outcomes(approved=True, risk="low")
        outcomes[AgentOutcome] = AgentOutcome(
            summary="Duplicate confirmed.",
            confidence=0.95,
            actions_taken=[],
            output_data={"refund_eligible": True, "refund_amount": 49.0},
        )
        _, consumer = build_pipeline(e2e, outcomes)

        await submit_ticket(e2e)
        await consumer.process_batch()

        assert e2e["redis"].pending_count("e2e-group") == 0

    async def test_a_failing_job_is_still_acknowledged(self, e2e):
        """An unacked poison job would redeliver forever."""
        # No scripted outcome for the supervisor's schema: the run fails.
        _, consumer = build_pipeline(e2e, {})

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        assert e2e["redis"].pending_count("e2e-group") == 0
        async with e2e["session_factory"]() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
        # The supervisor stops the workflow rather than planning on a guess.
        assert workflow.workflow_status is WorkflowStatus.FAILED

    async def test_a_failed_workflow_is_audited(self, e2e):
        """SRS §35: a non-recoverable failure still writes its audit row."""
        _, consumer = build_pipeline(e2e, {})

        workflow_id = await submit_ticket(e2e)
        await consumer.process_batch()

        events = await load_audit_events(e2e["session_factory"], workflow_id)
        assert any(e.get("event") == "workflow_finished" for e in events)


class TestRagGrounding:
    """SRS §33: retrieve before generating; never fabricate."""

    async def test_knowledge_search_returns_grounded_citations(self, e2e):
        from app.services.knowledge_service import KnowledgeService

        service = KnowledgeService(retriever=e2e["retriever"])
        result = await service.search_policy("duplicate payment refund")

        assert result["status"] == "ok"
        assert result["results"][0]["source"] == "refund-policy.md"
        assert result["results"][0]["score"] == 0.91
        assert e2e["retriever"].queries == ["duplicate payment refund"]

    async def test_no_relevant_context_reports_insufficient_information(self, e2e):
        """The RAG contract's whole point: say so rather than invent an answer."""
        from app.services.knowledge_service import KnowledgeService

        service = KnowledgeService(retriever=RecordingRetriever(hits=[]))
        result = await service.search_policy("how do I file my taxes")

        assert result["status"] == "insufficient_information"
        assert result["results"] == []
        assert "Do not answer from unsupported knowledge" in result["message"]

    async def test_knowledge_tools_are_reachable_through_mcp(self, e2e):
        """Agents reach knowledge only through the MCP boundary (SRS §16.3).

        Goes through the real registered tool over an in-process MCP session,
        so the tool contract and the audit write both execute for real.
        """
        from mcp.shared.memory import create_connected_server_and_client_session

        from app.mcp.server.main import create_mcp_server

        async with create_connected_server_and_client_session(
            create_mcp_server()
        ) as client:
            result = await client.call_tool(
                "knowledge_search_policy", {"query": "duplicate payment refund"}
            )

        payload = _tool_payload(result)
        assert payload["status"] == "ok"
        assert payload["results"][0]["doc_type"] == "refund_policy"
