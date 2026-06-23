from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.agent import agent_router
from backend.main import app
from backend.schemas.agent_stream import AgentStreamEvent


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if not data_lines:
            continue
        events.append(json.loads("\n".join(data_lines)))
    return events


def _stream_events(message: str, *, debug: bool = False) -> tuple[str, list[dict]]:
    client = TestClient(app)
    with client.stream("POST", "/api/agent/chat/stream", json={"message": message, "debug": debug}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        raw = "".join(response.iter_text())
    return raw, _parse_sse(raw)


def test_old_chat_api_still_usable() -> None:
    client = TestClient(app)
    response = client.post("/api/agent/chat", json={"message": "你好"})
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("conversation_id") or payload.get("session_id")
    assert payload.get("reply") or payload.get("message") or payload.get("error_message")


def test_agent_stream_hello_events() -> None:
    raw, events = _stream_events("你好")
    names = [event.get("event") for event in events]
    assert "event: start" in raw
    assert "start" in names
    assert "status" in names
    assert "planner" in names
    assert "delta" in names
    assert "final" in names
    assert names[-1] == "done"


def test_agent_stream_error_and_done_without_required_file() -> None:
    _raw, events = _stream_events("用深度学习去噪")
    names = [event.get("event") for event in events]
    assert "error" in names
    assert names[-1] == "done"
    assert any("文件" in str(event.get("content") or "") or "上传" in str(event.get("content") or "") for event in events)


def test_agent_stream_debug_payload() -> None:
    _raw, events = _stream_events("先不要预测，只做预处理并画图", debug=True)
    planner_events = [event for event in events if event.get("event") == "planner"]
    assert planner_events
    assert any("rule_intent" in (event.get("data") or {}) or "llm_plan_raw" in (event.get("data") or {}) for event in planner_events)


def test_chat_sync_and_stream_final_contract(monkeypatch) -> None:
    contract_fields = [
        "intent",
        "route",
        "skill_name",
        "tool_name",
        "citations",
        "artifacts",
        "error_code",
        "conversation_id",
        "task_id",
    ]

    def build_response(payload: dict) -> dict:
        conversation_id = str(payload.get("conversation_id") or payload.get("session_id") or "contract-conv")
        return {
            "success": True,
            "reply": "契约回复",
            "intent": "general_chat",
            "route": "chat",
            "skill_name": "",
            "tool_name": "",
            "citations": [{"source": "contract-doc", "snippet": "引用片段"}],
            "artifacts": [{"type": "text", "path": "outputs/reports/contract.md"}],
            "error_code": None,
            "conversation_id": conversation_id,
            "session_id": conversation_id,
            "task_id": "task-contract",
        }

    def fake_handle_chat(payload: dict) -> dict:
        return build_response(payload)

    async def fake_handle_chat_stream(payload: dict):
        conversation_id = str(payload.get("conversation_id") or payload.get("session_id") or "contract-conv")
        yield AgentStreamEvent(event="start", conversation_id=conversation_id, session_id=conversation_id, content="start")
        yield AgentStreamEvent(
            event="final",
            conversation_id=conversation_id,
            session_id=conversation_id,
            content="契约回复",
            data={"response": build_response(payload)},
        )
        yield AgentStreamEvent(event="done", conversation_id=conversation_id, session_id=conversation_id, content="done")

    monkeypatch.setattr(agent_router.orchestrator, "handle_chat", fake_handle_chat)
    monkeypatch.setattr(agent_router.orchestrator, "handle_chat_stream", fake_handle_chat_stream)

    client = TestClient(app)
    request_payload = {"message": "合同测试", "conversation_id": "contract-conv"}

    sync_response = client.post("/api/agent/chat", json=request_payload)
    assert sync_response.status_code == 200
    sync_payload = sync_response.json()

    with client.stream("POST", "/api/agent/chat/stream", json=request_payload) as response:
        assert response.status_code == 200
        stream_events = _parse_sse("".join(response.iter_text()))
    final_events = [event for event in stream_events if event.get("event") == "final"]
    assert final_events
    stream_payload = final_events[-1]["data"]["response"]

    for field in contract_fields:
        assert stream_payload.get(field) == sync_payload.get(field), field
