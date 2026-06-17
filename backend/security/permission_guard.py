from __future__ import annotations

from backend.security.permissions import has_permission


def assert_permissions(role: str, permissions: list[str], granted: list[str] | None = None) -> None:
    missing = [permission for permission in permissions if not has_permission(role, permission, granted)]
    if missing:
        raise PermissionError(f"权限不足，缺少：{', '.join(missing)}。")
