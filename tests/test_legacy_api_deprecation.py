from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_legacy_llm_api_has_deprecation_successor_headers() -> None:
    client = TestClient(app)

    response = client.get("/api/llm/models/current")

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert "Sunset" in response.headers
    assert response.headers["Link"] == '</api/models/current>; rel="successor-version"'


def test_legacy_agent_model_api_has_deprecation_successor_headers() -> None:
    client = TestClient(app)

    response = client.get("/api/agent/models")

    assert response.status_code == 200
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Link"] == '</api/models/providers>; rel="successor-version"'
