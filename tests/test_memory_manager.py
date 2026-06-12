from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.user_memory_manager import UserMemoryManager


def test_memory_manager_can_remember_and_clear_notes():
    manager = UserMemoryManager()
    user_id = "memory-test-user"
    manager.clear_user_memory(user_id)
    manager.remember_note(user_id, "以后默认用中文回答")
    memory = manager.get_user_memory(user_id)
    assert "以后默认用中文回答" in memory.get("profile", {}).get("notes", [])
    manager.clear_user_memory(user_id)
    assert manager.get_user_memory(user_id).get("profile", {}).get("notes", []) == []
