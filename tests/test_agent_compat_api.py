from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_legacy_session_api_still_works_with_deprecation_headers() -> None:
    client = TestClient(app)

    response = client.post("/api/agent/session/new")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["session_id"]
    assert response.headers["Deprecation"] == "true"
    assert "rel=\"successor-version\"" in response.headers["Link"]

    memory = client.get(f"/api/agent/session/{payload['session_id']}")
    assert memory.status_code == 200
    assert memory.json()["success"] is True
    assert memory.headers["Deprecation"] == "true"


def test_new_model_api_has_no_legacy_deprecation_header() -> None:
    client = TestClient(app)

    response = client.get("/api/models/current")

    assert response.status_code == 200
    assert "Deprecation" not in response.headers
