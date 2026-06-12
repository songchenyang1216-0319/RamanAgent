from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.llm_service import LLMService
from backend.services.user_memory_manager import UserMemoryManager
from backend.services.workspace_manager import WorkspaceManager


def test_build_model_context_includes_memory_summary_and_recent_messages():
    user_id = "context-user"
    conversation_id = "context-conv"
    workspace = WorkspaceManager()
    workspace.update_context_summary(user_id, conversation_id, "这是一段会话摘要。")
    workspace.append_message(user_id, conversation_id, "user", "上一轮用户消息")
    UserMemoryManager().remember_note(user_id, "默认使用中文回答")

    context = LLMService(user_id=user_id, conversation_id=conversation_id).build_model_context()
    assert "默认使用中文回答" in str(context.get("user_memory"))
    assert context.get("conversation_summary") == "这是一段会话摘要。"
    assert any(item.get("content") == "上一轮用户消息" for item in context.get("recent_messages") or [])
