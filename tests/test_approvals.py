"""Tests for the HITL approval endpoint (SRS §26, §36, §38)."""

import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import AuditLog, SupportTicket, User, WorkflowRun
from app.models.enums import WorkflowStatus
from app.services.queue_service import KIND_RESUME


@pytest_asyncio.fixture
async def paused_workflow(session_factory):
    """A workflow parked at the HITL interrupt, ready to be approved."""
    async with session_factory() as session:
        customer = User(
            company_name="Initech",
            full_name="Peter Example",
            email=f"peter-{uuid.uuid4().hex[:8]}@initech.test",
        )
        session.add(customer)
        await session.flush()

        ticket = SupportTicket(
            customer_id=customer.id,
            title="Refund request",
            description="Please refund my duplicate charge of 5000 USD.",
        )
        session.add(ticket)
        await session.flush()

        workflow = WorkflowRun(
            ticket_id=ticket.id,
            workflow_status=WorkflowStatus.WAITING_FOR_HITL,
            current_node="human_approval",
        )
        session.add(workflow)
        await session.commit()
        return workflow.workflow_id


@pytest_asyncio.fixture
async def running_workflow(session_factory):
    """A workflow that never asked for approval."""
    async with session_factory() as session:
        customer = User(
            company_name="Hooli",
            full_name="Gavin Example",
            email=f"gavin-{uuid.uuid4().hex[:8]}@hooli.test",
        )
        session.add(customer)
        await session.flush()
        ticket = SupportTicket(
            customer_id=customer.id, title="Question", description="Hello?"
        )
        session.add(ticket)
        await session.flush()
        workflow = WorkflowRun(
            ticket_id=ticket.id, workflow_status=WorkflowStatus.RUNNING
        )
        session.add(workflow)
        await session.commit()
        return workflow.workflow_id


def approval_payload(**overrides) -> dict:
    payload = {
        "approved": True,
        "reviewer_name": "Support Manager",
        "comments": "Refund approved.",
    }
    payload.update(overrides)
    return payload


class TestApproveWorkflow:
    async def test_approval_returns_the_recorded_decision(
        self, client, paused_workflow
    ):
        response = await client.post(
            f"/approvals/{paused_workflow}", json=approval_payload()
        )

        assert response.status_code == 200
        body = response.json()
        assert body["workflow_id"] == str(paused_workflow)
        assert body["approval_status"] == "approved"
        assert body["workflow_status"] == "running"

    async def test_rejection_is_recorded_as_rejected(self, client, paused_workflow):
        response = await client.post(
            f"/approvals/{paused_workflow}",
            json=approval_payload(approved=False, comments="Needs manager sign-off."),
        )

        assert response.json()["approval_status"] == "rejected"

    async def test_approval_unpauses_the_workflow_run(
        self, client, session_factory, paused_workflow
    ):
        await client.post(f"/approvals/{paused_workflow}", json=approval_payload())

        async with session_factory() as session:
            workflow = await session.get(WorkflowRun, paused_workflow)
        assert workflow.workflow_status is WorkflowStatus.RUNNING

    async def test_approval_enqueues_a_resume_job_with_the_decision(
        self, client, fake_redis, paused_workflow
    ):
        """SRS §38: the endpoint records the decision; the dispatcher resumes."""
        await client.post(f"/approvals/{paused_workflow}", json=approval_payload())

        jobs = [j for entries in fake_redis.streams.values() for j in entries]
        assert len(jobs) == 1
        assert jobs[0]["kind"] == KIND_RESUME
        assert jobs[0]["workflow_id"] == str(paused_workflow)
        decision = json.loads(jobs[0]["decision"])
        assert decision == {
            "approved": True,
            "reviewer_name": "Support Manager",
            "comments": "Refund approved.",
        }

    async def test_approval_writes_an_audit_row(
        self, client, session_factory, paused_workflow
    ):
        """SRS §16.10: every business action is auditable."""
        await client.post(f"/approvals/{paused_workflow}", json=approval_payload())

        async with session_factory() as session:
            row = await session.scalar(
                select(AuditLog).where(AuditLog.workflow_id == paused_workflow)
            )
        assert row.performed_by == "reviewer:Support Manager"
        action = json.loads(row.action)
        assert action["event"] == "hitl_decision"
        assert action["approved"] is True

    async def test_the_endpoint_does_not_run_the_graph(
        self, client, paused_workflow, monkeypatch
    ):
        """SRS §46: FastAPI never calls an LLM or MCP - it only queues."""
        import app.graph.workflow as workflow_module

        def fail(*args, **kwargs):
            raise AssertionError("the API must not build or run the graph")

        monkeypatch.setattr(workflow_module, "build_workflow_graph", fail)

        response = await client.post(
            f"/approvals/{paused_workflow}", json=approval_payload()
        )
        assert response.status_code == 200


class TestApprovalValidation:
    async def test_unknown_workflow_returns_404(self, client):
        response = await client.post(
            f"/approvals/{uuid.uuid4()}", json=approval_payload()
        )
        assert response.status_code == 404

    async def test_workflow_not_awaiting_approval_returns_409(
        self, client, running_workflow
    ):
        response = await client.post(
            f"/approvals/{running_workflow}", json=approval_payload()
        )
        assert response.status_code == 409
        assert "not awaiting approval" in response.json()["detail"]

    async def test_double_approval_is_rejected(self, client, paused_workflow):
        """The second call finds the run already unpaused."""
        first = await client.post(
            f"/approvals/{paused_workflow}", json=approval_payload()
        )
        second = await client.post(
            f"/approvals/{paused_workflow}", json=approval_payload()
        )
        assert first.status_code == 200
        assert second.status_code == 409

    @pytest.mark.parametrize(
        "payload",
        [
            {"reviewer_name": "Manager"},  # missing approved
            {"approved": True},  # missing reviewer_name
            {"approved": True, "reviewer_name": ""},  # empty reviewer_name
            {"approved": "maybe", "reviewer_name": "Manager"},  # wrong type
        ],
    )
    async def test_invalid_payload_returns_422(
        self, client, paused_workflow, payload
    ):
        response = await client.post(f"/approvals/{paused_workflow}", json=payload)
        assert response.status_code == 422

    async def test_comments_are_optional(self, client, paused_workflow):
        response = await client.post(
            f"/approvals/{paused_workflow}",
            json={"approved": True, "reviewer_name": "Manager"},
        )
        assert response.status_code == 200

    async def test_malformed_workflow_id_returns_422(self, client):
        response = await client.post("/approvals/not-a-uuid", json=approval_payload())
        assert response.status_code == 422


class TestQueueFailureIsolation:
    async def test_queue_failure_does_not_unpause_the_workflow(
        self, client, session_factory, paused_workflow, fake_redis, monkeypatch
    ):
        """A lost resume job must not leave the run silently unpaused.

        The status flip is flushed but not committed until the enqueue succeeds,
        so the failed request rolls back and the workflow stays reviewable.
        """

        async def failing_xadd(stream, fields):
            raise RuntimeError("redis unavailable")

        monkeypatch.setattr(fake_redis, "xadd", failing_xadd)

        # ASGITransport re-raises app exceptions; in the deployed app the
        # unhandled-exception handler turns this into a 500.
        with pytest.raises(RuntimeError, match="redis unavailable"):
            await client.post(
                f"/approvals/{paused_workflow}", json=approval_payload()
            )

        async with session_factory() as session:
            workflow = await session.get(WorkflowRun, paused_workflow)
        assert workflow.workflow_status is WorkflowStatus.WAITING_FOR_HITL

    async def test_queue_failure_rolls_back_the_audit_row(
        self, client, session_factory, paused_workflow, fake_redis, monkeypatch
    ):
        """An approval that never reached the queue must not look approved."""

        async def failing_xadd(stream, fields):
            raise RuntimeError("redis unavailable")

        monkeypatch.setattr(fake_redis, "xadd", failing_xadd)

        with pytest.raises(RuntimeError):
            await client.post(
                f"/approvals/{paused_workflow}", json=approval_payload()
            )

        async with session_factory() as session:
            row = await session.scalar(
                select(AuditLog).where(AuditLog.workflow_id == paused_workflow)
            )
        assert row is None
