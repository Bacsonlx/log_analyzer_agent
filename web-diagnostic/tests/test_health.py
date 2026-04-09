from fastapi.testclient import TestClient

from server import app


def test_health_returns_ok_without_claude():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["claude_enabled"] is False
