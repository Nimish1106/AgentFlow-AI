"""Tests for the Phase 7 operations dashboard read endpoints.

These endpoints extend the SRS §36 surface so the React console can list, trace
and count (SRS §5). They are strictly read-only: nothing here may run a graph,
call an LLM, or reach MCP.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import select

from app.graph.constants import AgentName
from app.models import (
    AgentExecutionLog,
    Invoice,
    Subscription,
    SupportTicket,
    User,
    WorkflowRun,
)
from app.models.enums import (
    PaymentStatus,
    SubscriptionPlan,
    TicketPriority,
    TicketStatus,
    WorkflowStatus,
)

RISK_ASSESSMENT = {
    "score": 0.9,
    "level": "high",
    "requires_hitl": True,
    "reasons": [
        "policy_agent rejected the proposed resolution",
        "refund amount 5000.00 exceeds threshold 1000.00",
    ],
}


@pytest_asyncio.fixture
async def dashboard_data(session_factory):
    """A customer with a subscription, invoices, and three workflows.

    Covers one paused, one completed and one failed run so the list filters and
    metrics have something meaningful to distinguish.
    """
    async with session_factory() as session:
        customer = User(
            company_name="Initech",
            full_name="Paul Carr",
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
        session.add(
            Invoice(
                user_id=customer.id,
                amount=49,
                currency="USD",
                payment_status=PaymentStatus.DUPLICATE,
            )
        )

        started = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
        tickets: dict[str, SupportTicket] = {}
        workflows: dict[str, WorkflowRun] = {}

        specs = [
            ("paused", TicketStatus.IN_PROGRESS, WorkflowStatus.WAITING_FOR_HITL),
            ("done", TicketStatus.RESOLVED, WorkflowStatus.COMPLETED),
            ("broken", TicketStatus.OPEN, WorkflowStatus.FAILED),
        ]
        for index, (key, ticket_status, workflow_status) in enumerate(specs):
            ticket = SupportTicket(
                customer_id=customer.id,
                title=f"{key} ticket",
                description=f"Description for {key}.",
                priority=TicketPriority.HIGH,
                status=ticket_status,
            )
            session.add(ticket)
            await session.flush()
            workflow = WorkflowRun(
                ticket_id=ticket.id,
                workflow_status=workflow_status,
                current_node="risk_engine",
                started_at=started + timedelta(minutes=index),
                risk_assessment=dict(RISK_ASSESSMENT),
            )
            if workflow_status is WorkflowStatus.COMPLETED:
                workflow.completed_at = started + timedelta(
                    minutes=index, seconds=30
                )
            session.add(workflow)
            await session.flush()
            tickets[key] = ticket
            workflows[key] = workflow

        # A trace for the paused workflow: reasoning nodes carry a confidence,
        # deterministic governance nodes do not.
        trace = [
            ("supervisor", 100, None, 0),
            ("task_planner", 5, None, 0),
            (AgentName.BILLING.value, 2400, 0.95, 2),
            (AgentName.POLICY.value, 1800, 0.5, 0),
            ("results_aggregator", 2, None, 0),
            ("risk_engine", 1, None, 0),
        ]
        for sequence, (node, ms, confidence, tool_calls) in enumerate(trace):
            session.add(
                AgentExecutionLog(
                    workflow_id=workflows["paused"].workflow_id,
                    agent_name=node,
                    execution_time_ms=ms,
                    status="completed",
                    tool_calls=tool_calls,
                    confidence=confidence,
                    summary=f"{node} summary",
                    sequence=sequence,
                )
            )
        # The completed run's total drives avg_execution_time_ms.
        session.add(
            AgentExecutionLog(
                workflow_id=workflows["done"].workflow_id,
                agent_name="supervisor",
                execution_time_ms=1000,
                status="completed",
                tool_calls=0,
                sequence=0,
            )
        )
        await session.commit()

        return {
            "customer_id": customer.id,
            "tickets": {k: v.id for k, v in tickets.items()},
            "workflows": {k: v.workflow_id for k, v in workflows.items()},
        }


class TestListTickets:
    async def test_lists_tickets_with_customer_and_workflow_context(
        self, client, dashboard_data
    ):
        response = await client.get("/tickets")
        assert response.status_code == 200
        body = response.json()

        assert body["total"] == 3
        assert len(body["items"]) == 3
        row = next(r for r in body["items"] if r["title"] == "paused ticket")
        assert row["customer_name"] == "Paul Carr"
        assert row["company_name"] == "Initech"
        assert row["customer_tier"] == "enterprise"
        assert row["priority"] == "high"
        assert row["workflow_status"] == "waiting_for_hitl"
        assert row["requires_hitl"] is True

    async def test_filters_by_status(self, client, dashboard_data):
        response = await client.get("/tickets", params={"status": "resolved"})
        body = response.json()

        assert body["total"] == 1
        assert body["items"][0]["title"] == "done ticket"

    async def test_rejects_an_unknown_status(self, client, dashboard_data):
        response = await client.get("/tickets", params={"status": "nonsense"})
        assert response.status_code == 422

    async def test_paginates(self, client, dashboard_data):
        response = await client.get("/tickets", params={"limit": 2, "offset": 0})
        body = response.json()
        assert len(body["items"]) == 2
        # total reflects the whole collection, not the page.
        assert body["total"] == 3

    async def test_caps_the_page_size(self, client, dashboard_data):
        """A mistyped limit must not let one request scan the table."""
        response = await client.get("/tickets", params={"limit": 10_000})
        assert response.status_code == 422

    async def test_a_ticket_without_a_workflow_still_lists(
        self, client, session_factory
    ):
        async with session_factory() as session:
            customer = User(
                company_name="NoSub Ltd",
                full_name="Bob Example",
                email=f"bob-{uuid.uuid4().hex[:8]}@nosub.test",
            )
            session.add(customer)
            await session.flush()
            session.add(
                SupportTicket(
                    customer_id=customer.id,
                    title="Unqueued",
                    description="No workflow yet.",
                )
            )
            await session.commit()

        body = (await client.get("/tickets")).json()
        row = body["items"][0]
        assert row["workflow_id"] is None
        assert row["workflow_status"] is None
        assert row["requires_hitl"] is False
        # No subscription: the tier falls back rather than 500ing.
        assert row["customer_tier"] == "basic"


class TestListWorkflows:
    async def test_lists_workflows_newest_first(self, client, dashboard_data):
        response = await client.get("/workflows")
        assert response.status_code == 200
        body = response.json()

        assert body["total"] == 3
        titles = [row["ticket_title"] for row in body["items"]]
        assert titles == ["broken ticket", "done ticket", "paused ticket"]

    async def test_reports_duration_for_finished_runs_only(
        self, client, dashboard_data
    ):
        body = (await client.get("/workflows")).json()
        rows = {row["ticket_title"]: row for row in body["items"]}

        assert rows["done ticket"]["duration_ms"] == 30_000
        assert rows["paused ticket"]["duration_ms"] is None

    async def test_filters_by_status(self, client, dashboard_data):
        body = (
            await client.get("/workflows", params={"status": "waiting_for_hitl"})
        ).json()

        assert body["total"] == 1
        assert body["items"][0]["requires_hitl"] is True


class TestWorkflowTrace:
    async def test_returns_the_ordered_execution_trace(
        self, client, dashboard_data
    ):
        workflow_id = dashboard_data["workflows"]["paused"]
        response = await client.get(f"/workflows/{workflow_id}/trace")
        assert response.status_code == 200
        body = response.json()

        assert [step["agent_name"] for step in body["steps"]] == [
            "supervisor",
            "task_planner",
            AgentName.BILLING.value,
            AgentName.POLICY.value,
            "results_aggregator",
            "risk_engine",
        ]
        assert [step["sequence"] for step in body["steps"]] == [0, 1, 2, 3, 4, 5]

    async def test_exposes_timings_tool_calls_and_confidence(
        self, client, dashboard_data
    ):
        workflow_id = dashboard_data["workflows"]["paused"]
        body = (await client.get(f"/workflows/{workflow_id}/trace")).json()
        steps = {step["agent_name"]: step for step in body["steps"]}

        assert steps[AgentName.BILLING.value]["execution_time_ms"] == 2400
        assert steps[AgentName.BILLING.value]["tool_calls"] == 2
        assert steps[AgentName.BILLING.value]["confidence"] == 0.95
        # Deterministic nodes report no confidence.
        assert steps["risk_engine"]["confidence"] is None

    async def test_reads_the_risk_score_from_the_persisted_assessment(
        self, client, dashboard_data
    ):
        """Governance data comes from the column, never parsed from prose."""
        workflow_id = dashboard_data["workflows"]["paused"]
        body = (await client.get(f"/workflows/{workflow_id}/trace")).json()

        assert body["risk_score"] == 0.9
        assert body["requires_hitl"] is True

    async def test_unknown_workflow_returns_404(self, client):
        response = await client.get(f"/workflows/{uuid.uuid4()}/trace")
        assert response.status_code == 404

    async def test_a_workflow_without_a_trace_returns_empty_steps(
        self, client, dashboard_data
    ):
        workflow_id = dashboard_data["workflows"]["broken"]
        body = (await client.get(f"/workflows/{workflow_id}/trace")).json()
        assert body["steps"] == []


class TestApprovalDetail:
    async def test_returns_the_full_review_packet(self, client, dashboard_data):
        workflow_id = dashboard_data["workflows"]["paused"]
        response = await client.get(f"/workflows/{workflow_id}/approval")
        assert response.status_code == 200
        body = response.json()

        assert body["ticket_title"] == "paused ticket"
        assert body["customer_name"] == "Paul Carr"
        assert body["customer_tier"] == "enterprise"
        assert body["workflow_status"] == "waiting_for_hitl"

    async def test_risk_fields_come_from_the_persisted_assessment(
        self, client, dashboard_data
    ):
        """The whole point of migration 0004: structured, not re-derived."""
        workflow_id = dashboard_data["workflows"]["paused"]
        body = (await client.get(f"/workflows/{workflow_id}/approval")).json()

        assert body["risk_score"] == 0.9
        assert body["risk_level"] == "high"
        assert body["reasons"] == RISK_ASSESSMENT["reasons"]

    async def test_includes_billing_context_for_the_reviewer(
        self, client, dashboard_data
    ):
        workflow_id = dashboard_data["workflows"]["paused"]
        body = (await client.get(f"/workflows/{workflow_id}/approval")).json()

        assert body["subscription"]["plan"] == "enterprise"
        assert body["subscription"]["monthly_price"] == 499.0
        assert body["invoices"][0]["amount"] == 49.0
        assert body["invoices"][0]["payment_status"] == "duplicate"

    async def test_lists_only_reasoning_nodes_as_agent_summaries(
        self, client, dashboard_data
    ):
        """A reviewer reads agent judgements, not deterministic plumbing."""
        workflow_id = dashboard_data["workflows"]["paused"]
        body = (await client.get(f"/workflows/{workflow_id}/approval")).json()

        assert [s["agent_name"] for s in body["agent_summaries"]] == [
            AgentName.BILLING.value,
            AgentName.POLICY.value,
        ]

    async def test_a_workflow_without_an_assessment_reports_nulls(
        self, client, session_factory
    ):
        """No assessment must stay distinguishable from 'assessed as no risk'."""
        async with session_factory() as session:
            customer = User(
                company_name="Fresh Co",
                full_name="Ada Example",
                email=f"ada-{uuid.uuid4().hex[:8]}@fresh.test",
            )
            session.add(customer)
            await session.flush()
            ticket = SupportTicket(
                customer_id=customer.id, title="New", description="Just filed."
            )
            session.add(ticket)
            await session.flush()
            workflow = WorkflowRun(ticket_id=ticket.id)
            session.add(workflow)
            await session.commit()
            workflow_id = workflow.workflow_id

        body = (await client.get(f"/workflows/{workflow_id}/approval")).json()
        assert body["risk_score"] is None
        assert body["risk_level"] is None
        assert body["reasons"] == []

    async def test_unknown_workflow_returns_404(self, client):
        response = await client.get(f"/workflows/{uuid.uuid4()}/approval")
        assert response.status_code == 404


class TestMetrics:
    async def test_counts_workflows_by_state(self, client, dashboard_data):
        response = await client.get("/metrics")
        assert response.status_code == 200
        body = response.json()

        assert body["pending_hitl_approvals"] == 1
        assert body["completed_workflows"] == 1
        assert body["failed_workflows"] == 1
        # paused/completed/failed are none of them "active".
        assert body["active_workflows"] == 0

    async def test_counts_pending_and_running_as_active(
        self, client, session_factory
    ):
        async with session_factory() as session:
            customer = User(
                company_name="Busy Co",
                full_name="Eve Example",
                email=f"eve-{uuid.uuid4().hex[:8]}@busy.test",
            )
            session.add(customer)
            await session.flush()
            for status in (WorkflowStatus.PENDING, WorkflowStatus.RUNNING):
                ticket = SupportTicket(
                    customer_id=customer.id,
                    title=f"{status.value} ticket",
                    description="...",
                )
                session.add(ticket)
                await session.flush()
                session.add(
                    WorkflowRun(ticket_id=ticket.id, workflow_status=status)
                )
            await session.commit()

        body = (await client.get("/metrics")).json()
        assert body["active_workflows"] == 2

    async def test_averages_total_execution_time_of_completed_runs(
        self, client, dashboard_data
    ):
        """Averages whole runs, not individual nodes."""
        body = (await client.get("/metrics")).json()
        assert body["avg_execution_time_ms"] == 1000

    async def test_counts_open_tickets(self, client, dashboard_data):
        body = (await client.get("/metrics")).json()
        # open + in_progress; the resolved one does not count.
        assert body["open_tickets"] == 2

    async def test_empty_system_reports_zeroes_not_errors(self, client):
        body = (await client.get("/metrics")).json()
        assert body == {
            "active_workflows": 0,
            "pending_hitl_approvals": 0,
            "avg_execution_time_ms": None,
            "completed_workflows": 0,
            "failed_workflows": 0,
            "open_tickets": 0,
        }


class TestNoRowFanOut:
    """One ticket must always be one row.

    Both the tier and the latest-workflow lookups join tables that can hold
    several rows per ticket. A plain join fans the ticket out into duplicates
    and desynchronises it from ``total``, which the dashboard paginates on.
    """

    async def test_two_subscriptions_do_not_duplicate_a_ticket(
        self, client, session_factory
    ):
        """A customer with an upgrade history holds more than one subscription."""
        async with session_factory() as session:
            customer = User(
                company_name="Upgrade Corp",
                full_name="Sam Example",
                email=f"sam-{uuid.uuid4().hex[:8]}@upgrade.test",
            )
            session.add(customer)
            await session.flush()
            for plan in (SubscriptionPlan.BASIC, SubscriptionPlan.ENTERPRISE):
                session.add(
                    Subscription(
                        user_id=customer.id,
                        plan=plan,
                        monthly_price=49,
                        renewal_date=date(2027, 1, 1),
                    )
                )
            session.add(
                SupportTicket(
                    customer_id=customer.id, title="Only once", description="x"
                )
            )
            await session.commit()

        body = (await client.get("/tickets")).json()
        assert len(body["items"]) == 1
        assert body["total"] == 1

    async def test_a_retried_ticket_does_not_duplicate(
        self, client, session_factory
    ):
        """Two runs written in one transaction share ``now()`` exactly.

        Postgres' ``now()`` is transaction-scoped, so a MAX(started_at) join
        matches both rows and emits the ticket twice.
        """
        async with session_factory() as session:
            customer = User(
                company_name="Retry Ltd",
                full_name="Rae Example",
                email=f"rae-{uuid.uuid4().hex[:8]}@retry.test",
            )
            session.add(customer)
            await session.flush()
            ticket = SupportTicket(
                customer_id=customer.id, title="Retried", description="x"
            )
            session.add(ticket)
            await session.flush()
            session.add(WorkflowRun(ticket_id=ticket.id))
            session.add(WorkflowRun(ticket_id=ticket.id))
            await session.commit()

        body = (await client.get("/tickets")).json()
        assert len(body["items"]) == 1
        assert body["total"] == 1
        assert body["items"][0]["workflow_id"] is not None

    async def test_the_page_never_exceeds_its_limit(self, client, session_factory):
        """Fan-out would silently overflow a page and break pagination."""
        async with session_factory() as session:
            customer = User(
                company_name="Busy Corp",
                full_name="Bea Example",
                email=f"bea-{uuid.uuid4().hex[:8]}@busy.test",
            )
            session.add(customer)
            await session.flush()
            for plan in (SubscriptionPlan.BASIC, SubscriptionPlan.PREMIUM):
                session.add(
                    Subscription(
                        user_id=customer.id,
                        plan=plan,
                        monthly_price=49,
                        renewal_date=date(2027, 1, 1),
                    )
                )
            for index in range(4):
                session.add(
                    SupportTicket(
                        customer_id=customer.id,
                        title=f"Ticket {index}",
                        description="x",
                    )
                )
            await session.commit()

        body = (await client.get("/tickets", params={"limit": 2})).json()
        assert len(body["items"]) == 2
        assert body["total"] == 4


class TestReadOnly:
    async def test_dashboard_endpoints_never_run_the_graph(
        self, client, dashboard_data, monkeypatch
    ):
        """SRS §46: FastAPI never invokes an LLM, MCP, or the workflow graph."""
        import app.graph.workflow as workflow_module

        def explode(*args, **kwargs):
            raise AssertionError("the dashboard must not build or run the graph")

        monkeypatch.setattr(workflow_module, "build_workflow_graph", explode)

        workflow_id = dashboard_data["workflows"]["paused"]
        for path in (
            "/tickets",
            "/workflows",
            "/metrics",
            f"/workflows/{workflow_id}/trace",
            f"/workflows/{workflow_id}/approval",
        ):
            assert (await client.get(path)).status_code == 200

    async def test_reads_do_not_mutate_workflow_state(
        self, client, session_factory, dashboard_data
    ):
        workflow_id = dashboard_data["workflows"]["paused"]

        await client.get(f"/workflows/{workflow_id}/approval")
        await client.get(f"/workflows/{workflow_id}/trace")

        async with session_factory() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
            trace_count = len(
                list(
                    await session.scalars(
                        select(AgentExecutionLog).where(
                            AgentExecutionLog.workflow_id == workflow_id
                        )
                    )
                )
            )
        assert workflow.workflow_status is WorkflowStatus.WAITING_FOR_HITL
        assert trace_count == 6
