from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.session_store import append_message
from backend.main import app


def test_conversation_crud_and_message_search():
    client = TestClient(app)
    created = client.post("/api/conversations", json={"title": "测试会话", "user_id": "conv-api-user"}).json()
    assert created["success"] is True
    conversation_id = created["conversation"]["conversation_id"]

    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "重命名会话"}).json()
    assert renamed["conversation"]["title"] == "重命名会话"

    append_message(conversation_id, "user", "这里有一条需要搜索的消息")
    search = client.post(f"/api/conversations/{conversation_id}/messages/search", json={"query": "搜索"}).json()
    assert search["success"] is True
    assert search["messages"]

    removed = client.delete(f"/api/conversations/{conversation_id}").json()
    assert removed["success"] is True
    assert removed["is_deleted"] is True
