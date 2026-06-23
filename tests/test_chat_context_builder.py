from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend.agent.chat_context_builder import ChatContextBuilder
from backend.agent.chat_request_parser import ParsedChatRequest


class FakeWorkspaceManager:
    def __init__(self, active_files=None):
        self.active_files = list(active_files or [])
        self.saved_uploads = []

    def create_workspace(self, user_id, conversation_id):
        return {"user_id": user_id or "default_user", "conversation_id": conversation_id, "path": "."}

    def update_memory_snapshot(self, user_id, conversation_id, snapshot):
        self.memory_snapshot = snapshot

    def read_workspace_context(self, user_id, conversation_id):
        return {"context_summary": "summary"}

    def read_active_files(self, user_id, conversation_id):
        return list(self.active_files)

    async def save_upload_file(self, user_id, conversation_id, file):
        self.saved_uploads.append(file)
        return {"file_id": "uploaded-1", "filename": "uploaded.txt", "path": "uploaded.txt", "user_id": user_id, "workspace_id": conversation_id}


class FakeFileCatalog:
    def __init__(self, files):
        self.files = {item["file_id"]: item for item in files}

    def get_files_by_ids(self, file_ids, *, user_id, is_admin=False):
        return [item for file_id in file_ids if (item := self.files.get(file_id)) and item.get("user_id") == user_id]


class FakeMemory:
    def remember_note(self, user_id, note):
        self.note = note

    def get_user_memory(self, user_id):
        return {"recent": []}


def _builder(tmp_path, *, active_files=None, files=None):
    return ChatContextBuilder(
        workspace_manager=FakeWorkspaceManager(active_files=active_files),
        file_catalog=FakeFileCatalog(files or []),
        user_memory_manager=FakeMemory(),
        ensure_session_id=lambda value=None: value or "session-1",
        update_session=lambda session_id, key, value: None,
        get_session=lambda session_id: {},
        project_root=tmp_path,
    )


def test_chat_context_builder_dedupes_file_ids_and_builds_payload(tmp_path) -> None:
    builder = _builder(
        tmp_path,
        files=[
            {"file_id": "f1", "filename": "a.txt", "path": "a.txt", "user_id": "user-a"},
            {"file_id": "f2", "filename": "b.txt", "path": "b.txt", "user_id": "user-a"},
        ],
    )

    context = asyncio.run(
        builder.build(
            ParsedChatRequest(
                message="总结文件",
                conversation_id="conv-1",
                user_id="user-a",
                file_ids=["f1", "f2", "f1"],
                knowledge_base_ids=["kb1", "kb1", "kb2"],
            )
        )
    )

    assert context.file_ids == ["f1", "f2"]
    assert context.knowledge_base_ids == ["kb1", "kb2"]
    assert [item["file_id"] for item in context.selected_files] == ["f1", "f2"]
    assert context.conversation_id == context.session_id == "conv-1"
    assert context.to_orchestrator_payload()["files"] == context.selected_files


def test_chat_context_builder_rejects_cross_user_file(tmp_path) -> None:
    builder = _builder(tmp_path, files=[{"file_id": "f1", "filename": "a.txt", "path": "a.txt", "user_id": "other"}])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(builder.build(ParsedChatRequest(message="总结文件", user_id="user-a", file_ids=["f1"])))

    assert exc_info.value.status_code == 404


def test_chat_context_builder_restores_multiple_active_files(tmp_path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    active_files = [
        {"file_id": "a", "filename": "a.txt", "path": "a.txt", "user_id": "user-a"},
        {"file_id": "b", "filename": "b.txt", "path": "b.txt", "user_id": "user-a"},
    ]
    builder = _builder(tmp_path, active_files=active_files)

    context = asyncio.run(builder.build(ParsedChatRequest(message="总结这些文件", user_id="user-a")))

    assert [item["file_id"] for item in context.selected_files] == ["a", "b"]
    assert context.to_orchestrator_payload()["file_ids"] == ["a", "b"]
