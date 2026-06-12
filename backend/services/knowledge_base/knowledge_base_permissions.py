from __future__ import annotations

from datetime import datetime

from backend.db.database import get_db_connection, init_agent_memory_db


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class KnowledgeBasePermissionService:
    OWNER_ROLES = {"owner", "admin"}
    WRITE_ROLES = {"owner", "admin", "editor"}
    READ_ROLES = {"owner", "admin", "editor", "viewer"}

    def add_permission(self, knowledge_base_id: str, user_id: str, role: str) -> None:
        init_agent_memory_db()
        now = now_iso()
        connection = get_db_connection()
        try:
            connection.execute(
                "DELETE FROM knowledge_base_permissions WHERE knowledge_base_id = ? AND user_id = ?",
                (knowledge_base_id, user_id),
            )
            connection.execute(
                "INSERT INTO knowledge_base_permissions (knowledge_base_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (knowledge_base_id, user_id, role, now, now),
            )
            connection.commit()
        finally:
            connection.close()

    def get_role(self, knowledge_base_id: str, user_id: str) -> str | None:
        init_agent_memory_db()
        connection = get_db_connection()
        try:
            row = connection.execute(
                "SELECT role FROM knowledge_base_permissions WHERE knowledge_base_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1",
                (knowledge_base_id, user_id),
            ).fetchone()
            return str(row["role"]) if row else None
        finally:
            connection.close()

    def can_read(self, kb: dict, user_id: str, *, is_admin: bool = False) -> bool:
        if is_admin or str(kb.get("owner_user_id") or "") == str(user_id):
            return True
        if str(kb.get("visibility") or "private") == "public":
            return True
        return (self.get_role(str(kb.get("knowledge_base_id")), user_id) or "") in self.READ_ROLES

    def can_write(self, kb: dict, user_id: str, *, is_admin: bool = False) -> bool:
        if is_admin or str(kb.get("owner_user_id") or "") == str(user_id):
            return True
        return (self.get_role(str(kb.get("knowledge_base_id")), user_id) or "") in self.WRITE_ROLES

    def can_admin(self, kb: dict, user_id: str, *, is_admin: bool = False) -> bool:
        if is_admin or str(kb.get("owner_user_id") or "") == str(user_id):
            return True
        return (self.get_role(str(kb.get("knowledge_base_id")), user_id) or "") in self.OWNER_ROLES
