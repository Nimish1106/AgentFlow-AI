"""Tests for the /health endpoint."""


async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "database": "ok", "redis": "ok"}
