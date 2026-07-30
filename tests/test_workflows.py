"""Tests for the workflow status endpoint (SRS §36)."""

import uuid

from app.models import User


async def test_workflow_status_pending_after_submission(client, session_factory):
    user = User(
        id=uuid.uuid4(),
        company_name="Globex",
        full_name="Bob Example",
        email=f"bob-{uuid.uuid4().hex[:8]}@globex.test",
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()

    created = await client.post(
        "/tickets",
        json={
            "customer_id": str(user.id),
            "subject": "API auth failing",
            "description": "401 on every request.",
        },
    )
    workflow_id = created.json()["workflow_id"]

    response = await client.get(f"/workflows/{workflow_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == workflow_id
    assert body["workflow_status"] == "pending"
    assert body["completed_agents"] == []
    assert body["requires_hitl"] is False
    assert body["current_node"] is None


async def test_missing_workflow_returns_404(client):
    response = await client.get(f"/workflows/{uuid.uuid4()}")
    assert response.status_code == 404
