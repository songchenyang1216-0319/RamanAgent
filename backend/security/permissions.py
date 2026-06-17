from __future__ import annotations

from typing import Iterable


ROLE_PERMISSIONS = {
    "admin": {"*"},
    "project_owner": {"project:*", "file:*", "task:*", "report:*"},
    "project_editor": {"project:view", "file:view", "file:upload", "task:create", "report:create"},
    "project_viewer": {"project:view", "file:view", "task:view", "report:view"},
    "user": {"project:view", "project:create", "file:view", "file:upload", "task:create", "report:create", "tool:execute"},
}


def has_permission(role: str, permission: str, extra_permissions: Iterable[str] | None = None) -> bool:
    allowed = set(ROLE_PERMISSIONS.get(str(role or "user"), ROLE_PERMISSIONS["user"]))
    allowed.update(str(item) for item in (extra_permissions or []))
    if "*" in allowed or permission in allowed:
        return True
    namespace = permission.split(":", 1)[0]
    return f"{namespace}:*" in allowed

