from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_service_metadata() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["data"]["service"] == "wps-ai-adapter"
    assert body["data"]["status"] == "ok"
