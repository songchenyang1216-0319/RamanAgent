from __future__ import annotations

from fastapi.testclient import TestClient
from uuid import uuid4

from backend.api import chat_api
from backend.agent.session_store import clear_sessions, get_session
from backend.main import app


def test_chat_api_json_chat_uses_shared_pipeline(monkeypatch) -> None:
    clear_sessions()

    def fake_handle_chat(payload):
        return {
            "success": True,
            "reply": "普通聊天回复",
            "intent": "general_chat",
            "route": "chat",
            "conversation_id": payload["conversation_id"],
            "session_id": payload["session_id"],
        }

    monkeypatch.setattr(chat_api.orchestrator, "handle_chat", fake_handle_chat)

    client = TestClient(app)
    conversation_id = f"chat-api-{uuid4().hex}"
    response = client.post("/api/agent/chat", json={"message": "你好", "conversation_id": conversation_id, "provider_id": "mock", "model_id": "mock-model"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == "普通聊天回复"
    assert payload["conversation_id"] == conversation_id
    assert payload["session_id"] == conversation_id
    session = get_session(conversation_id)
    assert session is not None
    assert [message["role"] for message in session["messages"][-2:]] == ["user", "assistant"]


def test_no_duplicate_routes_registered() -> None:
    seen = {}
    duplicates = []
    for route in app.routes:
        for method in getattr(route, "methods", None) or []:
            if method in {"HEAD", "OPTIONS"}:
                continue
            key = (method, getattr(route, "path", ""))
            if key in seen:
                duplicates.append(key)
            seen[key] = getattr(route, "name", "")
    assert ("POST", "/api/agent/chat") in seen
    assert ("POST", "/api/agent/chat/stream") in seen
    assert not duplicates
