from __future__ import annotations

import json

from starlette.requests import Request

from backend.agent.chat_request_parser import ChatRequestParser


def _json_request(payload: dict) -> Request:
    body = json.dumps(payload).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/api/agent/chat", "headers": [(b"content-type", b"application/json")]}, receive)


def test_chat_request_parser_json_dedupes_ids() -> None:
    parser = ChatRequestParser(default_user_id="default_user")

    parsed = __import__("asyncio").run(
        parser.parse(
            _json_request(
                {
                    "message": "你好",
                    "conversation_id": "conv-1",
                    "user_id": "user-a",
                    "provider_id": "mock-provider",
                    "model_id": "mock-model",
                    "file_ids": ["f1", "f2", "f1", ""],
                    "knowledge_base_ids": '["kb1","kb2","kb1"]',
                    "rag_scope": "mixed",
                    "debug": True,
                }
            )
        )
    )

    assert parsed.message == "你好"
    assert parsed.conversation_id == "conv-1"
    assert parsed.user_id == "user-a"
    assert parsed.provider_id == "mock-provider"
    assert parsed.model_id == "mock-model"
    assert parsed.file_ids == ["f1", "f2"]
    assert parsed.knowledge_base_ids == ["kb1", "kb2"]
    assert parsed.rag_scope == "mixed"
    assert parsed.debug is True
