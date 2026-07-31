"""Tests for the queue dispatcher: WorkflowRunner persistence + Redis consumer."""

import json
import uuid
from datetime import date

import pytest
import pytest_asyncio
from langgraph.types import Command

from app.dispatcher.consumer import WorkflowConsumer
from app.dispatcher.runner import AUDIT_ACTOR, WorkflowRunner
from app.graph.constants import AgentName
from app.models import AgentExecutionLog, AuditLog, SupportTicket, User, WorkflowRun
from app.models.enums import (
    SubscriptionPlan,
    TicketStatus,
    WorkflowStatus,
)
from app.services.exceptions import WorkflowNotFoundError
from app.services.queue_service import KIND_RESUME, KIND_START


class FakeGraph:
    """Compiled-graph stand-in recording invocations and returning a scripted state.

    ``result`` may be a single dict or a list consumed one per ``ainvoke`` so a
    test can script pause-then-resume.
    """

    def __init__(self, result, raises: Exception | None = None) -> None:
        self._results = result if isinstance(result, list) else [result]
        self.raises = raises
        self.calls: list[tuple] = []

    async def ainvoke(self, graph_input, config=None):
        self.calls.append((graph_input, config))
        if self.raises is not None:
            raise self.raises
        return self._results.pop(0) if len(self._results) > 1 else self._results[0]


def final_state(**overrides) -> dict:
    """A completed workflow's final GraphState."""
    state = {
        "workflow_status": "completed",
        "current_node": "dispatcher",
        "final_response": "Your duplicate charge has been refunded.",
        "risk_score": 0.2,
        "approval_status": None,
        "errors": [],
        "shared_context": {},
        "agent_results": [
            {
                "agent_name": AgentName.BILLING.value,
                "status": "success",
                "summary": "Duplicate confirmed.",
                "confidence": 0.95,
                "actions_taken": [],
                "tool_calls": ["billing_get_invoice", "billing_calculate_refund"],
                "output_data": {},
            },
            {
                "agent_name": AgentName.POLICY.value,
                "status": "success",
                "summary": "Approved.",
                "confidence": 0.98,
                "actions_taken": [],
                "tool_calls": [],
                "output_data": {"approved": True},
            },
        ],
    }
    state.update(overrides)
    return state


def interrupted_state(**overrides) -> dict:
    """A workflow parked at the HITL interrupt."""
    state = {
        "__interrupt__": [{"value": {"risk_level": "high"}}],
        "current_node": "risk_engine",
        "risk_score": 0.9,
        "requires_hitl": True,
        "shared_context": {"risk": {"reasons": ["refund 5000 exceeds threshold"]}},
        "agent_results": [],
    }
    state.update(overrides)
    return state


@pytest_asyncio.fixture
async def seeded(session_factory):
    """A customer, ticket and pending workflow run to execute."""
    from app.models import Subscription

    async with session_factory() as session:
        customer = User(
            company_name="Acme Corp",
            full_name="Alice Example",
            email="alice@acme.test",
        )
        session.add(customer)
        await session.flush()

        session.add(
            Subscription(
                user_id=customer.id,
                plan=SubscriptionPlan.ENTERPRISE,
                monthly_price=499,
                renewal_date=date(2026, 12, 1),
            )
        )
        ticket = SupportTicket(
            customer_id=customer.id,
            title="Duplicate payment",
            description="I was charged twice.",
        )
        session.add(ticket)
        await session.flush()

        workflow = WorkflowRun(ticket_id=ticket.id)
        session.add(workflow)
        await session.commit()

        return {
            "customer_id": customer.id,
            "ticket_id": ticket.id,
            "workflow_id": workflow.workflow_id,
        }


async def load_workflow(session_factory, workflow_id) -> WorkflowRun:
    async with session_factory() as session:
        return await session.get(WorkflowRun, workflow_id)


async def load_ticket(session_factory, ticket_id) -> SupportTicket:
    async with session_factory() as session:
        return await session.get(SupportTicket, ticket_id)


async def load_audit_actions(session_factory, workflow_id) -> list[dict]:
    from sqlalchemy import select

    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.workflow_id == workflow_id)
                .order_by(AuditLog.timestamp)
            )
        )
    return [json.loads(row.action) for row in rows]


class TestRunnerInitialState:
    async def test_builds_state_from_the_ticket_and_customer(
        self, session_factory, seeded
    ):
        graph = FakeGraph(final_state())
        runner = WorkflowRunner(graph, session_factory)

        await runner.run(seeded["workflow_id"])

        state, config = graph.calls[0]
        assert state["ticket_id"] == str(seeded["ticket_id"])
        assert state["customer_id"] == str(seeded["customer_id"])
        assert "Duplicate payment" in state["issue_text"]
        assert "charged twice" in state["issue_text"]

    async def test_uses_the_subscription_plan_as_the_customer_tier(
        self, session_factory, seeded
    ):
        graph = FakeGraph(final_state())
        await WorkflowRunner(graph, session_factory).run(seeded["workflow_id"])

        state, _ = graph.calls[0]
        assert state["customer_tier"] == SubscriptionPlan.ENTERPRISE.value

    async def test_customer_without_a_subscription_defaults_to_basic(
        self, session_factory
    ):
        async with session_factory() as session:
            customer = User(
                company_name="NoSub Ltd",
                full_name="Bob Example",
                email="bob@nosub.test",
            )
            session.add(customer)
            await session.flush()
            ticket = SupportTicket(
                customer_id=customer.id, title="Question", description="Hello?"
            )
            session.add(ticket)
            await session.flush()
            workflow = WorkflowRun(ticket_id=ticket.id)
            session.add(workflow)
            await session.commit()
            workflow_id = workflow.workflow_id

        graph = FakeGraph(final_state())
        await WorkflowRunner(graph, session_factory).run(workflow_id)

        state, _ = graph.calls[0]
        assert state["customer_tier"] == "basic"

    async def test_uses_workflow_id_as_the_thread_id(self, session_factory, seeded):
        """SRS §38: the workflow_id IS the LangGraph thread_id."""
        graph = FakeGraph(final_state())
        await WorkflowRunner(graph, session_factory).run(seeded["workflow_id"])

        _, config = graph.calls[0]
        assert config["configurable"]["thread_id"] == str(seeded["workflow_id"])

    async def test_unknown_workflow_raises(self, session_factory):
        runner = WorkflowRunner(FakeGraph(final_state()), session_factory)
        with pytest.raises(WorkflowNotFoundError):
            await runner.run(uuid.uuid4())


class TestRunnerCompletion:
    async def test_marks_the_workflow_completed(self, session_factory, seeded):
        await WorkflowRunner(FakeGraph(final_state()), session_factory).run(
            seeded["workflow_id"]
        )

        workflow = await load_workflow(session_factory, seeded["workflow_id"])
        assert workflow.workflow_status is WorkflowStatus.COMPLETED
        assert workflow.completed_at is not None
        assert workflow.current_node == "dispatcher"

    async def test_writes_the_resolution_onto_the_ticket(
        self, session_factory, seeded
    ):
        """SRS §36: GET /tickets/{id} returns ticket details and resolution."""
        await WorkflowRunner(FakeGraph(final_state()), session_factory).run(
            seeded["workflow_id"]
        )

        ticket = await load_ticket(session_factory, seeded["ticket_id"])
        assert ticket.status is TicketStatus.RESOLVED
        assert ticket.resolution == "Your duplicate charge has been refunded."

    async def test_logs_one_execution_row_per_agent(self, session_factory, seeded):
        from sqlalchemy import select

        await WorkflowRunner(FakeGraph(final_state()), session_factory).run(
            seeded["workflow_id"]
        )

        async with session_factory() as session:
            logs = list(
                await session.scalars(
                    select(AgentExecutionLog).where(
                        AgentExecutionLog.workflow_id == seeded["workflow_id"]
                    )
                )
            )
        by_name = {log.agent_name: log for log in logs}
        assert set(by_name) == {AgentName.BILLING.value, AgentName.POLICY.value}
        assert by_name[AgentName.BILLING.value].tool_calls == 2
        assert by_name[AgentName.BILLING.value].status == "completed"

    async def test_records_a_workflow_finished_audit_row(
        self, session_factory, seeded
    ):
        await WorkflowRunner(FakeGraph(final_state()), session_factory).run(
            seeded["workflow_id"]
        )

        actions = await load_audit_actions(session_factory, seeded["workflow_id"])
        finished = [a for a in actions if a["event"] == "workflow_finished"]
        assert finished[0]["workflow_status"] == "completed"

    async def test_records_resolved_conflicts_in_the_audit_log(
        self, session_factory, seeded
    ):
        """SRS §40: conflicts resolved in policy's favour are auditable."""
        state = final_state(
            shared_context={
                "aggregation": {"conflicts": ["billing_agent vs policy_agent"]}
            }
        )
        await WorkflowRunner(FakeGraph(state), session_factory).run(
            seeded["workflow_id"]
        )

        actions = await load_audit_actions(session_factory, seeded["workflow_id"])
        conflicts = [a for a in actions if a["event"] == "conflict_resolved"]
        assert conflicts[0]["detail"] == "billing_agent vs policy_agent"

    async def test_failed_agents_are_logged_as_failed(self, session_factory, seeded):
        from sqlalchemy import select

        state = final_state(
            agent_results=[
                {
                    "agent_name": AgentName.BILLING.value,
                    "status": "failed",
                    "summary": "MCP unavailable.",
                    "confidence": 0.0,
                    "actions_taken": [],
                    "tool_calls": [],
                    "output_data": {},
                }
            ]
        )
        await WorkflowRunner(FakeGraph(state), session_factory).run(
            seeded["workflow_id"]
        )

        async with session_factory() as session:
            log = await session.scalar(
                select(AgentExecutionLog).where(
                    AgentExecutionLog.workflow_id == seeded["workflow_id"]
                )
            )
        assert log.status == "failed"


class TestRunnerFailure:
    async def test_failed_workflow_status_is_persisted(self, session_factory, seeded):
        state = final_state(workflow_status="failed", final_response=None)
        await WorkflowRunner(FakeGraph(state), session_factory).run(
            seeded["workflow_id"]
        )

        workflow = await load_workflow(session_factory, seeded["workflow_id"])
        assert workflow.workflow_status is WorkflowStatus.FAILED

    async def test_failed_workflow_leaves_the_ticket_unresolved(
        self, session_factory, seeded
    ):
        state = final_state(workflow_status="failed", final_response=None)
        await WorkflowRunner(FakeGraph(state), session_factory).run(
            seeded["workflow_id"]
        )

        ticket = await load_ticket(session_factory, seeded["ticket_id"])
        assert ticket.status is TicketStatus.OPEN
        assert ticket.resolution is None

    async def test_graph_crash_is_recorded_and_reraised(
        self, session_factory, seeded
    ):
        """SRS §35: a non-recoverable failure stops the workflow and audits it."""
        runner = WorkflowRunner(
            FakeGraph(final_state(), raises=RuntimeError("groq unavailable")),
            session_factory,
        )
        with pytest.raises(RuntimeError, match="groq unavailable"):
            await runner.run(seeded["workflow_id"])

        workflow = await load_workflow(session_factory, seeded["workflow_id"])
        assert workflow.workflow_status is WorkflowStatus.FAILED
        actions = await load_audit_actions(session_factory, seeded["workflow_id"])
        assert any(a["event"] == "workflow_failed" for a in actions)


class TestRunnerHitl:
    async def test_interrupt_parks_the_workflow_for_review(
        self, session_factory, seeded
    ):
        """SRS §38 steps 2-4: checkpoint, mark waiting_for_hitl, pause."""
        await WorkflowRunner(FakeGraph(interrupted_state()), session_factory).run(
            seeded["workflow_id"]
        )

        workflow = await load_workflow(session_factory, seeded["workflow_id"])
        assert workflow.workflow_status is WorkflowStatus.WAITING_FOR_HITL
        assert workflow.completed_at is None

    async def test_interrupt_audits_the_approval_request(
        self, session_factory, seeded
    ):
        await WorkflowRunner(FakeGraph(interrupted_state()), session_factory).run(
            seeded["workflow_id"]
        )

        actions = await load_audit_actions(session_factory, seeded["workflow_id"])
        requested = [a for a in actions if a["event"] == "hitl_requested"]
        assert requested[0]["reasons"] == ["refund 5000 exceeds threshold"]

    async def test_interrupt_leaves_the_ticket_unresolved(
        self, session_factory, seeded
    ):
        await WorkflowRunner(FakeGraph(interrupted_state()), session_factory).run(
            seeded["workflow_id"]
        )

        ticket = await load_ticket(session_factory, seeded["ticket_id"])
        assert ticket.resolution is None

    async def test_resume_passes_the_decision_as_a_command(
        self, session_factory, seeded
    ):
        graph = FakeGraph(final_state())
        decision = {
            "approved": True,
            "reviewer_name": "Support Manager",
            "comments": "ok",
        }

        await WorkflowRunner(graph, session_factory).resume(
            seeded["workflow_id"], decision
        )

        graph_input, config = graph.calls[0]
        assert isinstance(graph_input, Command)
        assert graph_input.resume == decision
        assert config["configurable"]["thread_id"] == str(seeded["workflow_id"])

    async def test_resume_completes_and_resolves_the_ticket(
        self, session_factory, seeded
    ):
        await WorkflowRunner(FakeGraph(final_state()), session_factory).resume(
            seeded["workflow_id"], {"approved": True, "reviewer_name": "Manager"}
        )

        workflow = await load_workflow(session_factory, seeded["workflow_id"])
        ticket = await load_ticket(session_factory, seeded["ticket_id"])
        assert workflow.workflow_status is WorkflowStatus.COMPLETED
        assert ticket.status is TicketStatus.RESOLVED

    async def test_resume_is_audited(self, session_factory, seeded):
        await WorkflowRunner(FakeGraph(final_state()), session_factory).resume(
            seeded["workflow_id"], {"approved": False, "reviewer_name": "Manager"}
        )

        actions = await load_audit_actions(session_factory, seeded["workflow_id"])
        resumed = [a for a in actions if a["event"] == "workflow_resumed"]
        assert resumed[0]["approved"] is False

    async def test_pause_then_resume_runs_the_graph_twice_on_one_thread(
        self, session_factory, seeded
    ):
        graph = FakeGraph([interrupted_state(), final_state()])
        runner = WorkflowRunner(graph, session_factory)

        await runner.run(seeded["workflow_id"])
        await runner.resume(
            seeded["workflow_id"], {"approved": True, "reviewer_name": "Manager"}
        )

        thread_ids = {c[1]["configurable"]["thread_id"] for c in graph.calls}
        assert thread_ids == {str(seeded["workflow_id"])}
        workflow = await load_workflow(session_factory, seeded["workflow_id"])
        assert workflow.workflow_status is WorkflowStatus.COMPLETED


class FakeStreamRedis:
    """Redis stand-in implementing just the consumer-group calls used here."""

    def __init__(self, entries: list[tuple[str, dict]] | None = None) -> None:
        self.entries = list(entries or [])
        self.groups: list[tuple] = []
        self.acked: list[str] = []
        self.group_create_error: Exception | None = None

    async def xgroup_create(self, stream, group, id="0", mkstream=False):
        if self.group_create_error is not None:
            raise self.group_create_error
        self.groups.append((stream, group, id, mkstream))

    async def xreadgroup(self, group, consumer, streams, count=1, block=None):
        if not self.entries:
            return []
        batch = self.entries[:count]
        self.entries = self.entries[count:]
        return [(list(streams)[0], batch)]

    async def xack(self, stream, group, entry_id):
        self.acked.append(entry_id)


class RecordingRunner:
    """WorkflowRunner stand-in recording run/resume calls."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.runs: list[uuid.UUID] = []
        self.resumes: list[tuple[uuid.UUID, dict]] = []
        self.raises = raises

    async def run(self, workflow_id):
        self.runs.append(workflow_id)
        if self.raises is not None:
            raise self.raises

    async def resume(self, workflow_id, decision):
        self.resumes.append((workflow_id, decision))
        if self.raises is not None:
            raise self.raises


class TestConsumer:
    def build(self, entries, runner=None):
        client = FakeStreamRedis(entries)
        runner = runner or RecordingRunner()
        return client, runner, WorkflowConsumer(client, runner)

    async def test_creates_the_consumer_group_with_mkstream(self):
        """The dispatcher may boot before the first ticket exists."""
        client, _, consumer = self.build([])
        await consumer.ensure_group()
        assert client.groups[0][3] is True

    async def test_tolerates_an_existing_group(self):
        from redis.exceptions import ResponseError

        client, _, consumer = self.build([])
        client.group_create_error = ResponseError("BUSYGROUP already exists")
        await consumer.ensure_group()  # must not raise

    async def test_propagates_unexpected_group_errors(self):
        from redis.exceptions import ResponseError

        client, _, consumer = self.build([])
        client.group_create_error = ResponseError("NOPERM")
        with pytest.raises(ResponseError):
            await consumer.ensure_group()

    async def test_runs_a_start_job(self):
        workflow_id = uuid.uuid4()
        client, runner, consumer = self.build(
            [("1-0", {"kind": KIND_START, "workflow_id": str(workflow_id)})]
        )

        assert await consumer.process_batch() == 1
        assert runner.runs == [workflow_id]
        assert client.acked == ["1-0"]

    async def test_job_without_a_kind_defaults_to_start(self):
        workflow_id = uuid.uuid4()
        _, runner, consumer = self.build(
            [("1-0", {"workflow_id": str(workflow_id)})]
        )
        await consumer.process_batch()
        assert runner.runs == [workflow_id]

    async def test_resumes_with_the_reviewer_decision(self):
        workflow_id = uuid.uuid4()
        _, runner, consumer = self.build(
            [
                (
                    "1-0",
                    {
                        "kind": KIND_RESUME,
                        "workflow_id": str(workflow_id),
                        "decision": json.dumps(
                            {
                                "approved": True,
                                "reviewer_name": "Manager",
                                "comments": "ok",
                            }
                        ),
                    },
                )
            ]
        )

        await consumer.process_batch()

        assert runner.resumes[0][0] == workflow_id
        assert runner.resumes[0][1]["approved"] is True

    async def test_resume_without_a_decision_is_skipped_and_acked(self):
        """An unreadable verdict must never be resumed as an approval."""
        workflow_id = uuid.uuid4()
        client, runner, consumer = self.build(
            [("1-0", {"kind": KIND_RESUME, "workflow_id": str(workflow_id)})]
        )

        await consumer.process_batch()

        assert runner.resumes == []
        assert client.acked == ["1-0"]

    async def test_unusable_workflow_id_is_acked_not_retried_forever(self):
        client, runner, consumer = self.build([("1-0", {"workflow_id": "not-a-uuid"})])

        await consumer.process_batch()

        assert runner.runs == []
        assert client.acked == ["1-0"]

    async def test_failed_job_is_still_acknowledged(self):
        """The outcome is already persisted as failed; redelivery adds nothing."""
        workflow_id = uuid.uuid4()
        client, runner, consumer = self.build(
            [("1-0", {"workflow_id": str(workflow_id)})],
            runner=RecordingRunner(raises=RuntimeError("boom")),
        )

        await consumer.process_batch()

        assert client.acked == ["1-0"]

    async def test_empty_stream_processes_nothing(self):
        _, runner, consumer = self.build([])
        assert await consumer.process_batch() == 0
        assert runner.runs == []

    async def test_run_forever_stops_when_asked(self):
        workflow_id = uuid.uuid4()
        client = FakeStreamRedis([("1-0", {"workflow_id": str(workflow_id)})])
        runner = RecordingRunner()
        consumer = WorkflowConsumer(client, runner)

        original = consumer.process_batch

        async def process_then_stop(count=1):
            processed = await original(count)
            if not processed:
                consumer.stop()
            return processed

        consumer.process_batch = process_then_stop
        await consumer.run_forever()

        assert runner.runs == [workflow_id]
