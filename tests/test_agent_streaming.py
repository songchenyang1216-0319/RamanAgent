from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.main import app


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
