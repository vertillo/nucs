"""Tests for the public /api/health endpoint."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok(app_env):
    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"


def test_health_does_not_require_auth(app_env):
    with TestClient(create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
