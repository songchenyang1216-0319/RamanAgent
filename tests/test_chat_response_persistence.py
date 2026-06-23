from __future__ import annotations

from pathlib import Path

from backend.agent.chat_context import ChatExecutionContext
from backend.agent.chat_response_persistence import ChatResponsePersistence


class FakeWorkspaceManager:
    def __init__(self):
        self.messages = []
        self.summary = ""
        self.active_files = []

    def append_message(self, user_id, conversation_id, role, content, metadata=None):
        entry = {"message_id": f"m{len(self.messages)}", "role": role, "content": content, "metadata": metadata or {}}
        self.messages.append(entry)
        return entry

    def read_context_summary(self, user_id, conversation_id):
        return self.summary

    def update_context_summary(self, user_id, conversation_id, summary):
        self.summary = summary

    def read_active_files(self, user_id, conversation_id):
        return list(self.active_files)


class FakeTaskTraceManager:
    def create_task(self, **kwargs):
        return {"task_id": "task-1", **kwargs}

    def add_step(self, task_id, name, detail=None):
        return {"step_id": f"{task_id}-{name}"}

    def finish_step(self, step_id, **kwargs):
        return None

    def update_task(self, *args, **kwargs):
        return None

    def get_task_trace(self, task_id):
        return {"steps": []}

    def record_skill_run(self, **kwargs):
        return kwargs


def _persistence(workspace, session_messages, session_updates):
    return ChatResponsePersistence(
        workspace_manager=workspace,
        append_message=lambda session_id, role, content: session_messages.append((session_id, role, content)),
        update_session=lambda session_id, key, value: session_updates.append((session_id, key, value)),
        build_session_analysis_payload=lambda payload, session_id: {"session_id": session_id, "reply": payload.get("reply")},
        apply_task_state_from_response=lambda session_id, payload: session_updates.append((session_id, "task_state", payload.get("task_id"))),
        llm_model_info=lambda **kwargs: {"provider": "mock", "model": "mock-model"},
        task_trace_manager=FakeTaskTraceManager(),
        project_root=Path("."),
    )


def test_chat_response_persistence_user_turn_is_idempotent() -> None:
    workspace = FakeWorkspaceManager()
    session_messages = []
    session_updates = []
    persistence = _persistence(workspace, session_messages, session_updates)
    context = ChatExecutionContext(
        message="你好",
        effective_message="你好",
        user_id="user-a",
        conversation_id="conv-1",
        session_id="conv-1",
        workspace_context={"context_summary": "old"},
    )

    persistence.persist_user_turn(context)
    persistence.persist_user_turn(context)

    assert [item["role"] for item in workspace.messages] == ["user"]
    assert session_messages == [("conv-1", "user", "你好")]
    assert context.user_message_id == "m0"


def test_chat_response_persistence_final_response_is_idempotent() -> None:
    workspace = FakeWorkspaceManager()
    session_messages = []
    session_updates = []
    persistence = _persistence(workspace, session_messages, session_updates)
    context = ChatExecutionContext(
        message="你好",
        effective_message="你好",
        user_id="user-a",
        conversation_id="conv-1",
        session_id="conv-1",
    )

    first = persistence.persist_final_response(context, {"success": True, "reply": "你好呀", "intent": "general_chat"})
    second = persistence.persist_final_response(context, {"success": True, "reply": "重复", "intent": "general_chat"})

    assert first == second
    assert [item["role"] for item in workspace.messages] == ["assistant"]
    assert session_messages == [("conv-1", "assistant", "你好呀")]
    assert first["conversation_id"] == "conv-1"
    assert first["model_info"] == {"provider": "mock", "model": "mock-model"}
