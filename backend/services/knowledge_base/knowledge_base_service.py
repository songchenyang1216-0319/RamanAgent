from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.db.database import get_db_connection, init_agent_memory_db

from .knowledge_base_permissions import KnowledgeBasePermissionService


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class KnowledgeBaseService:
    def __init__(self) -> None:
        self.permissions = KnowledgeBasePermissionService()

    def create_knowledge_base(self, user_id: str, name: str, description: str = "", visibility: str = "private") -> dict[str, Any]:
        init_agent_memory_db()
        kb_id = f"kb_{uuid4().hex[:12]}"
        now = now_iso()
        visibility = visibility if visibility in {"private", "workspace", "public"} else "private"
        connection = get_db_connection()
        try:
            connection.execute(
                """
                INSERT INTO knowledge_bases (
                    knowledge_base_id, owner_user_id, name, description, visibility,
                    enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (kb_id, user_id, name.strip() or "未命名知识库", description or "", visibility, now, now),
            )
            connection.commit()
        finally:
            connection.close()
        self.permissions.add_permission(kb_id, user_id, "owner")
        return self.get_knowledge_base(user_id, kb_id, is_admin=True)

    def list_knowledge_bases(self, user_id: str, *, is_admin: bool = False, include_disabled: bool = True) -> list[dict[str, Any]]:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            rows = connection.execute("SELECT * FROM knowledge_bases WHERE deleted_at IS NULL ORDER BY updated_at DESC").fetchall()
            result = []
            for row in rows:
                item = dict(row)
                if not include_disabled and not bool(item.get("enabled")):
                    continue
                if self.permissions.can_read(item, user_id, is_admin=is_admin):
                    item["enabled"] = bool(item.get("enabled"))
                    result.append(item)
            return result
        finally:
            connection.close()

    def get_knowledge_base(self, user_id: str, knowledge_base_id: str, *, is_admin: bool = False) -> dict[str, Any]:
        item = self._get_raw(knowledge_base_id)
        if item is None or not self.permissions.can_read(item, user_id, is_admin=is_admin):
            raise PermissionError("无权访问该知识库或知识库不存在。")
        item["enabled"] = bool(item.get("enabled"))
        return item

    def update_knowledge_base(self, user_id: str, knowledge_base_id: str, *, name: str | None = None, description: str | None = None, visibility: str | None = None, is_admin: bool = False) -> dict[str, Any]:
        item = self._get_raw(knowledge_base_id)
        if item is None or not self.permissions.can_write(item, user_id, is_admin=is_admin):
            raise PermissionError("无权修改该知识库。")
        patch = {}
        if name is not None:
            patch["name"] = name.strip() or item["name"]
        if description is not None:
            patch["description"] = description
        if visibility is not None:
            patch["visibility"] = visibility if visibility in {"private", "workspace", "public"} else "private"
        if not patch:
            return self.get_knowledge_base(user_id, knowledge_base_id, is_admin=is_admin)
        patch["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in patch)
        values = list(patch.values()) + [knowledge_base_id]
        connection = get_db_connection()
        try:
            connection.execute(f"UPDATE knowledge_bases SET {assignments} WHERE knowledge_base_id = ?", values)
            connection.commit()
        finally:
            connection.close()
        return self.get_knowledge_base(user_id, knowledge_base_id, is_admin=is_admin)

    def delete_knowledge_base(self, user_id: str, knowledge_base_id: str, *, is_admin: bool = False) -> dict[str, Any]:
        item = self._get_raw(knowledge_base_id)
        if item is None or not self.permissions.can_admin(item, user_id, is_admin=is_admin):
            raise PermissionError("无权删除该知识库。")
        now = now_iso()
        connection = get_db_connection()
        try:
            connection.execute("UPDATE knowledge_bases SET deleted_at = ?, enabled = 0, updated_at = ? WHERE knowledge_base_id = ?", (now, now, knowledge_base_id))
            connection.commit()
        finally:
            connection.close()
        try:
            from backend.services.rag import VectorStore

            VectorStore().delete_by_knowledge_base(knowledge_base_id)
        except Exception:
            pass
        item["deleted_at"] = now
        item["enabled"] = False
        return item

    def enable_knowledge_base(self, user_id: str, knowledge_base_id: str, *, enabled: bool, is_admin: bool = False) -> dict[str, Any]:
        item = self._get_raw(knowledge_base_id)
        if item is None or not self.permissions.can_write(item, user_id, is_admin=is_admin):
            raise PermissionError("无权修改该知识库。")
        connection = get_db_connection()
        try:
            connection.execute("UPDATE knowledge_bases SET enabled = ?, updated_at = ? WHERE knowledge_base_id = ?", (1 if enabled else 0, now_iso(), knowledge_base_id))
            connection.commit()
        finally:
            connection.close()
        return self.get_knowledge_base(user_id, knowledge_base_id, is_admin=is_admin)

    def bind_to_conversation(self, user_id: str, conversation_id: str, knowledge_base_id: str, *, enabled: bool = True, is_admin: bool = False) -> dict[str, Any]:
        kb = self.get_knowledge_base(user_id, knowledge_base_id, is_admin=is_admin)
        now = now_iso()
        connection = get_db_connection()
        try:
            connection.execute(
                "DELETE FROM conversation_knowledge_bases WHERE user_id = ? AND conversation_id = ? AND knowledge_base_id = ?",
                (user_id, conversation_id, knowledge_base_id),
            )
            connection.execute(
                "INSERT INTO conversation_knowledge_bases (conversation_id, user_id, knowledge_base_id, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, user_id, knowledge_base_id, 1 if enabled else 0, now, now),
            )
            connection.commit()
        finally:
            connection.close()
        return {"success": True, "knowledge_base": kb, "conversation_id": conversation_id, "enabled": enabled}

    def unbind_from_conversation(self, user_id: str, conversation_id: str, knowledge_base_id: str, *, is_admin: bool = False) -> dict[str, Any]:
        kb = self.get_knowledge_base(user_id, knowledge_base_id, is_admin=is_admin)
        connection = get_db_connection()
        try:
            connection.execute(
                "DELETE FROM conversation_knowledge_bases WHERE user_id = ? AND conversation_id = ? AND knowledge_base_id = ?",
                (user_id, conversation_id, knowledge_base_id),
            )
            connection.commit()
        finally:
            connection.close()
        return {"success": True, "knowledge_base": kb, "conversation_id": conversation_id, "enabled": False}

    def list_conversation_knowledge_bases(self, user_id: str, conversation_id: str, *, is_admin: bool = False, enabled_only: bool = True) -> list[dict[str, Any]]:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            rows = connection.execute(
                "SELECT knowledge_base_id, enabled FROM conversation_knowledge_bases WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            ).fetchall()
        finally:
            connection.close()
        result = []
        for row in rows:
            if enabled_only and not bool(row["enabled"]):
                continue
            try:
                kb = self.get_knowledge_base(user_id, str(row["knowledge_base_id"]), is_admin=is_admin)
            except PermissionError:
                continue
            if enabled_only and not bool(kb.get("enabled")):
                continue
            result.append(kb)
        return result

    def authorized_enabled_ids(self, user_id: str, *, is_admin: bool = False, conversation_id: str | None = None) -> list[str]:
        if conversation_id:
            return [item["knowledge_base_id"] for item in self.list_conversation_knowledge_bases(user_id, conversation_id, is_admin=is_admin, enabled_only=True)]
        return [item["knowledge_base_id"] for item in self.list_knowledge_bases(user_id, is_admin=is_admin, include_disabled=False)]

    def _get_raw(self, knowledge_base_id: str) -> dict[str, Any] | None:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            row = connection.execute(
                "SELECT * FROM knowledge_bases WHERE knowledge_base_id = ? AND deleted_at IS NULL",
                (knowledge_base_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            connection.close()
