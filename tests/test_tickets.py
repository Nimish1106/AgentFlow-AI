"""Tests for ticket submission and retrieval (SRS §36)."""

import uuid

from app.config.settings import get_settings
from app.models import User


async def _create_customer(session_factory) -> User:
    """Insert a customer directly into the test database."""
    user = User(
        id=uuid.uuid4(),
        company_name="Acme Corp",
        full_name="Alice Example",
        email=f"alice-{uuid.uuid4().hex[:8]}@acme.test",
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
    return user


async def test_create_ticket_returns_202_and_enqueues(
    client, session_factory, fake_redis
):
    customer = await _create_customer(session_factory)

    response = await client.post(
        "/tickets",
        json={
            "customer_id": str(customer.id),
            "subject": "Duplicate payment",
            "description": "I was charged twice.",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "accepted"
    workflow_id = body["workflow_id"]

    stream = get_settings().workflow_stream
    assert len(fake_redis.streams[stream]) == 1
    assert fake_redis.streams[stream][0]["workflow_id"] == workflow_id


async def test_create_ticket_unknown_customer_returns_404(client, fake_redis):
    response = await client.post(
        "/tickets",
        json={
            "customer_id": str(uuid.uuid4()),
            "subject": "Anything",
            "description": "No such customer.",
        },
    )
    assert response.status_code == 404
    assert fake_redis.streams == {}


async def test_create_ticket_rejects_invalid_payload(client):
    response = await client.post(
        "/tickets", json={"customer_id": "not-a-uuid", "subject": "", "description": ""}
    )
    assert response.status_code == 422


async def test_get_ticket_returns_details_with_workflow(client, session_factory):
    customer = await _create_customer(session_factory)
    created = await client.post(
        "/tickets",
        json={
            "customer_id": str(customer.id),
            "subject": "Dashboard locked",
            "description": "Cannot log in.",
        },
    )
    workflow_id = created.json()["workflow_id"]

    workflow = await client.get(f"/workflows/{workflow_id}")
    assert workflow.status_code == 200
    ticket_response = await client.get(
        f"/tickets/{await _ticket_id_for_workflow(session_factory, workflow_id)}"
    )
    assert ticket_response.status_code == 200
    body = ticket_response.json()
    assert body["title"] == "Dashboard locked"
    assert body["priority"] == "medium"
    assert body["status"] == "open"
    assert body["workflow_id"] == workflow_id
    assert body["workflow_status"] == "pending"


async def test_get_missing_ticket_returns_404(client):
    response = await client.get(f"/tickets/{uuid.uuid4()}")
    assert response.status_code == 404


async def _ticket_id_for_workflow(session_factory, workflow_id: str) -> str:
    """Look up the ticket id behind a workflow."""
    from app.models import WorkflowRun

    async with session_factory() as session:
        workflow = await session.get(WorkflowRun, uuid.UUID(workflow_id))
        return str(workflow.ticket_id)
