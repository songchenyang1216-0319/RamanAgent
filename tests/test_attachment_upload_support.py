from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.agent_router import _save_uploaded_attachment
from backend.main import app
from fastapi.testclient import TestClient


class DummyUploadFile:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content

    async def read(self) -> bytes:
        return self._content


async def smoke_test_txt_upload() -> None:
    uploaded = DummyUploadFile("sample_note.txt", "hello RamanAgent".encode("utf-8"))
    saved_path = await _save_uploaded_attachment(uploaded)
    assert saved_path.suffix.lower() == ".txt"
    assert saved_path.exists()
    assert saved_path.read_text(encoding="utf-8").startswith("hello RamanAgent")


def smoke_test_txt_chat_route() -> None:
    client = TestClient(app)
    with patch("backend.agent.agent_router.service.chat") as mock_chat:
        mock_chat.return_value = {
            "success": True,
            "reply": "txt file handled",
            "message": "txt file handled",
            "category": "general_chat",
            "intent": "smalltalk",
        }
        response = client.post(
            "/api/agent/chat",
            data={"message": "请分析这个 txt 文件"},
            files={"file": ("sample_note.txt", b"hello RamanAgent", "text/plain")},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["source"] == "llm_response"
    assert payload["reply"] == "txt file handled"


if __name__ == "__main__":
    asyncio.run(smoke_test_txt_upload())
    smoke_test_txt_chat_route()
    print("attachment upload smoke test passed")
