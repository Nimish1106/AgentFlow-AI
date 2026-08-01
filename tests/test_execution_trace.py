"""Tests for the Phase 7 execution trace and persisted risk assessment.

Two invariants matter most here and both are governance-critical:

- ``agent_execution_logs`` is append-only. A resumed workflow returns its whole
  checkpointed trace again, and the runner must append only the new tail rather
  than rewriting history.
- ``workflow_runs.risk_assessment`` holds the Risk Engine's decision as
  structured fields, so the HITL review UI never re-derives governance data.
"""

import uuid
from datetime import date

import pytest_asyncio
from sqlalchemy import select

from app.dispatcher.runner import (
    WorkflowRunner,
    _resumed_prefix_length,
    extract_risk_assessment,
)
from app.graph.constants import AgentName
from app.models import AgentExecutionLog, SupportTicket, User, WorkflowRun
from app.models.enums import SubscriptionPlan, WorkflowStatus


class FakeGraph:
    """Compiled-graph stand-in returning scripted states, one per ainvoke."""

    def __init__(self, results) -> None:
        self._results = results if isinstance(results, list) else [results]
        self.calls: list[tuple] = []

    async def ainvoke(self, graph_input, config=None):
        self.calls.append((graph_input, config))
        return self._results.pop(0) if len(self._results) > 1 else self._results[0]


def node_execution(node: str, **overrides) -> dict:
    """One NodeExecution trace entry."""
    entry = {
        "node": node,
        "status": "success",
        "execution_time_ms": 120.5,
        "tool_calls": [],
        "confidence": None,
        "summary": f"{node} ran",
    }
    entry.update(overrides)
    return entry


#: The six nodes that run before the HITL interrupt.
PRE_HITL_TRACE = [
    node_execution("supervisor"),
    node_execution("task_planner"),
    node_execution(
        AgentName.BILLING.value,
        confidence=0.95,
        tool_calls=["billing_get_invoice", "billing_calculate_refund"],
    ),
    node_execution(AgentName.POLICY.value, confidence=0.5),
    node_execution("results_aggregator"),
    node_execution("risk_engine"),
]

#: The three that run after the reviewer decides.
POST_HITL_TRACE = [
    node_execution("human_approval", execution_time_ms=0.0),
    node_execution(AgentName.RESPONSE.value, confidence=0.9),
    node_execution("dispatcher"),
]

RISK_CONTEXT = {
    "risk": {
        "risk_level": "high",
        "risk_score": 0.9,
        "requires_hitl": True,
        "reasons": [
            "policy_agent rejected the proposed resolution",
            "refund amount 5000.00 exceeds threshold 1000.00",
        ],
    }
}


def interrupted_state(**overrides) -> dict:
    """A workflow parked at the HITL interrupt, with its partial trace."""
    state = {
        "__interrupt__": [{"value": {"risk_level": "high"}}],
        "current_node": "risk_engine",
        "risk_score": 0.9,
        "requires_hitl": True,
        "shared_context": dict(RISK_CONTEXT),
        "agent_results": [],
        "node_executions": list(PRE_HITL_TRACE),
    }
    state.update(overrides)
    return state


def resumed_state(**overrides) -> dict:
    """The same workflow after resume: the whole trace, pre- and post-pause.

    This is what the checkpointer really returns - ``node_executions`` carries
    ``operator.add``, so the pre-pause entries come back alongside the new ones.
    """
    state = {
        "workflow_status": "completed",
        "current_node": "dispatcher",
        "final_response": "Your duplicate charge has been refunded.",
        "risk_score": 0.9,
        "approval_status": "approved",
        "errors": [],
        "shared_context": dict(RISK_CONTEXT),
        "agent_results": [],
        "node_executions": [*PRE_HITL_TRACE, *POST_HITL_TRACE],
    }
    state.update(overrides)
    return state


@pytest_asyncio.fixture
async def seeded(session_factory):
    """A customer, ticket and pending workflow run."""
    from app.models import Subscription

    async with session_factory() as session:
        customer = User(
            company_name="Initech",
            full_name="Paul Example",
            email=f"paul-{uuid.uuid4().hex[:8]}@initech.test",
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
            description="I was charged twice for 5000 USD.",
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


async def load_trace(session_factory, workflow_id) -> list[AgentExecutionLog]:
    """Read a workflow's trace rows in recorded order."""
    async with session_factory() as session:
        return list(
            await session.scalars(
                select(AgentExecutionLog)
                .where(AgentExecutionLog.workflow_id == workflow_id)
                .order_by(AgentExecutionLog.sequence)
            )
        )


class TestTracePersistence:
    async def test_records_one_row_per_node_with_real_timings(
        self, session_factory, seeded
    ):
        """Every node appears, not just the reasoning agents."""
        await WorkflowRunner(FakeGraph(resumed_state()), session_factory).run(
            seeded["workflow_id"]
        )

        rows = await load_trace(session_factory, seeded["workflow_id"])
        assert [row.agent_name for row in rows] == [
            "supervisor",
            "task_planner",
            AgentName.BILLING.value,
            AgentName.POLICY.value,
            "results_aggregator",
            "risk_engine",
            "human_approval",
            AgentName.RESPONSE.value,
            "dispatcher",
        ]
        assert rows[0].execution_time_ms == 120
        assert rows[2].tool_calls == 2

    async def test_sequence_is_dense_and_ordered(self, session_factory, seeded):
        """The timeline renders in sequence order, so it must be gapless."""
        await WorkflowRunner(FakeGraph(resumed_state()), session_factory).run(
            seeded["workflow_id"]
        )

        rows = await load_trace(session_factory, seeded["workflow_id"])
        assert [row.sequence for row in rows] == list(range(len(rows)))

    async def test_confidence_is_null_for_deterministic_nodes(
        self, session_factory, seeded
    ):
        """Governance nodes do not reason, so they report no confidence."""
        await WorkflowRunner(FakeGraph(resumed_state()), session_factory).run(
            seeded["workflow_id"]
        )

        rows = {
            row.agent_name: row
            for row in await load_trace(session_factory, seeded["workflow_id"])
        }
        assert rows["risk_engine"].confidence is None
        assert rows["results_aggregator"].confidence is None
        assert rows[AgentName.BILLING.value].confidence == 0.95

    async def test_hitl_pause_persists_the_partial_trace(
        self, session_factory, seeded
    ):
        """A parked workflow still shows how far it got."""
        await WorkflowRunner(
            FakeGraph(interrupted_state()), session_factory
        ).run(seeded["workflow_id"])

        rows = await load_trace(session_factory, seeded["workflow_id"])
        assert [row.agent_name for row in rows] == [
            entry["node"] for entry in PRE_HITL_TRACE
        ]

    async def test_resume_appends_without_duplicating_the_pre_pause_trace(
        self, session_factory, seeded
    ):
        """The core append-with-offset case.

        ``node_executions`` is checkpointed, so the resumed run returns the
        pre-pause entries again. Only the new tail may be written, and history
        must survive intact - no DELETE, no doubled rows.
        """
        graph = FakeGraph([interrupted_state(), resumed_state()])
        runner = WorkflowRunner(graph, session_factory)

        await runner.run(seeded["workflow_id"])
        await runner.resume(
            seeded["workflow_id"],
            {"approved": True, "reviewer_name": "Support Manager", "comments": ""},
        )

        rows = await load_trace(session_factory, seeded["workflow_id"])
        names = [row.agent_name for row in rows]
        assert names == [
            *(entry["node"] for entry in PRE_HITL_TRACE),
            *(entry["node"] for entry in POST_HITL_TRACE),
        ]
        # Each node appears exactly once despite being returned twice.
        assert len(names) == len(PRE_HITL_TRACE) + len(POST_HITL_TRACE)
        assert [row.sequence for row in rows] == list(range(len(rows)))

    async def test_history_is_never_deleted(self, session_factory, seeded):
        """Execution history is append-only (audit-adjacent, SRS §18.6).

        A pre-existing row from an earlier attempt must still be there after a
        later run persists its own trace.
        """
        async with session_factory() as session:
            session.add(
                AgentExecutionLog(
                    workflow_id=seeded["workflow_id"],
                    agent_name="earlier_attempt",
                    execution_time_ms=42,
                    status="failed",
                    tool_calls=0,
                    sequence=0,
                )
            )
            await session.commit()

        await WorkflowRunner(FakeGraph(resumed_state()), session_factory).run(
            seeded["workflow_id"]
        )

        rows = await load_trace(session_factory, seeded["workflow_id"])
        assert rows[0].agent_name == "earlier_attempt"
        assert len(rows) == 1 + len(PRE_HITL_TRACE) + len(POST_HITL_TRACE)
        # The new attempt continues the sequence rather than colliding with it.
        assert [row.sequence for row in rows] == list(range(len(rows)))

    async def test_falls_back_to_agent_results_without_a_trace(
        self, session_factory, seeded
    ):
        """An in-flight run whose state predates the trace channel still logs."""
        state = resumed_state(
            node_executions=[],
            agent_results=[
                {
                    "agent_name": AgentName.BILLING.value,
                    "status": "success",
                    "summary": "Duplicate confirmed.",
                    "confidence": 0.95,
                    "actions_taken": [],
                    "tool_calls": ["billing_get_invoice"],
                    "output_data": {},
                }
            ],
        )
        await WorkflowRunner(FakeGraph(state), session_factory).run(
            seeded["workflow_id"]
        )

        rows = await load_trace(session_factory, seeded["workflow_id"])
        assert [row.agent_name for row in rows] == [AgentName.BILLING.value]
        assert rows[0].confidence == 0.95


class TestRiskAssessmentPersistence:
    async def test_pause_persists_the_structured_assessment(
        self, session_factory, seeded
    ):
        """The reviewer's packet must be on the row before review is advertised."""
        await WorkflowRunner(
            FakeGraph(interrupted_state()), session_factory
        ).run(seeded["workflow_id"])

        async with session_factory() as session:
            workflow = await session.get(WorkflowRun, seeded["workflow_id"])

        assert workflow.workflow_status is WorkflowStatus.WAITING_FOR_HITL
        assert workflow.risk_assessment == {
            "score": 0.9,
            "level": "high",
            "requires_hitl": True,
            "reasons": [
                "policy_agent rejected the proposed resolution",
                "refund amount 5000.00 exceeds threshold 1000.00",
            ],
        }

    async def test_completion_persists_the_assessment(self, session_factory, seeded):
        await WorkflowRunner(FakeGraph(resumed_state()), session_factory).run(
            seeded["workflow_id"]
        )

        async with session_factory() as session:
            workflow = await session.get(WorkflowRun, seeded["workflow_id"])
        assert workflow.risk_assessment["level"] == "high"
        assert len(workflow.risk_assessment["reasons"]) == 2

    async def test_hitl_audit_row_reuses_the_structured_reasons(
        self, session_factory, seeded
    ):
        import json

        from app.models import AuditLog

        await WorkflowRunner(
            FakeGraph(interrupted_state()), session_factory
        ).run(seeded["workflow_id"])

        async with session_factory() as session:
            rows = list(
                await session.scalars(
                    select(AuditLog).where(
                        AuditLog.workflow_id == seeded["workflow_id"]
                    )
                )
            )
        requested = [
            json.loads(row.action)
            for row in rows
            if json.loads(row.action)["event"] == "hitl_requested"
        ]
        assert requested[0]["reasons"] == [
            "policy_agent rejected the proposed resolution",
            "refund amount 5000.00 exceeds threshold 1000.00",
        ]


class TestResumedPrefixLength:
    """The overlap calculation that keeps a resumed trace from doubling.

    Getting this wrong silently drops or duplicates nodes in the timeline, so
    the edge cases are worth pinning down directly.
    """

    def test_no_persisted_rows_writes_everything(self):
        assert _resumed_prefix_length([], ["supervisor", "task_planner"]) == 0

    def test_full_replay_after_a_resume_is_skipped(self):
        persisted = ["supervisor", "task_planner", "risk_engine"]
        incoming = [*persisted, "response_agent", "dispatcher"]
        assert _resumed_prefix_length(persisted, incoming) == 3

    def test_earlier_attempt_rows_do_not_shift_the_offset(self):
        """The regression this replaced a row count with.

        A stray row in front must not make the matcher skip a real node - the
        overlap is measured against the *suffix* of what is already stored.
        """
        persisted = ["earlier_attempt", "supervisor", "task_planner"]
        incoming = ["supervisor", "task_planner", "risk_engine"]
        assert _resumed_prefix_length(persisted, incoming) == 2

    def test_unrelated_history_appends_the_whole_trace(self):
        persisted = ["earlier_attempt"]
        incoming = ["supervisor", "task_planner"]
        assert _resumed_prefix_length(persisted, incoming) == 0

    def test_a_repeated_node_name_matches_the_longest_overlap(self):
        """Domain agents can legitimately recur across attempts."""
        persisted = ["supervisor", "billing_agent"]
        incoming = ["supervisor", "billing_agent", "policy_agent"]
        assert _resumed_prefix_length(persisted, incoming) == 2

    def test_identical_trace_writes_nothing_new(self):
        trace = ["supervisor", "task_planner", "dispatcher"]
        assert _resumed_prefix_length(trace, trace) == 3


class TestExtractRiskAssessment:
    def test_maps_graph_field_names_onto_stored_names(self):
        assessment = extract_risk_assessment({"shared_context": dict(RISK_CONTEXT)})
        assert assessment["score"] == 0.9
        assert assessment["level"] == "high"
        assert assessment["requires_hitl"] is True

    def test_returns_none_when_the_risk_engine_never_ran(self):
        """No assessment must stay distinguishable from 'assessed as no risk'."""
        assert extract_risk_assessment({"shared_context": {}}) is None
        assert extract_risk_assessment({}) is None

    def test_ignores_a_malformed_assessment(self):
        assert (
            extract_risk_assessment({"shared_context": {"risk": "high"}}) is None
        )

    def test_falls_back_to_the_state_risk_score(self):
        """The Risk Engine owns risk_score (SRS §28), but stay robust if absent."""
        assessment = extract_risk_assessment(
            {
                "risk_score": 0.5,
                "shared_context": {"risk": {"risk_level": "medium"}},
            }
        )
        assert assessment["score"] == 0.5
        assert assessment["requires_hitl"] is False
