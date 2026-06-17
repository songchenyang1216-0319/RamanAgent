from __future__ import annotations

from typing import Iterable

from backend.agent.planning.tool_schema import ActionSpec, ToolSpec
from backend.security.permissions import has_permission
from backend.tool_runtime.tool_context import ToolContext
from backend.tool_runtime.tool_errors import ToolRuntimeException


def assert_tool_permission(tool: ToolSpec, action: ActionSpec, context: ToolContext) -> None:
    required = list(tool.permissions or []) + list(action.permissions or [])
    if not required:
        return
    available = set(context.permissions or [])
    role = str(context.metadata.get("role") or "user")
    missing = [permission for permission in required if permission not in available and not has_permission(role, permission, available)]
    if missing:
        raise ToolRuntimeException("PERMISSION_DENIED", f"权限不足，缺少：{', '.join(missing)}。")


def assert_file_scope(args: dict, context: ToolContext, *, allow_file_path: bool = True) -> None:
    requested_ids = []
    for key in ("file_id", "file_ids"):
        value = args.get(key)
        if isinstance(value, str):
            requested_ids.append(value)
        elif isinstance(value, Iterable):
            requested_ids.extend(str(item) for item in value if str(item).strip())
    if requested_ids:
        allowed = set(context.file_ids or [])
        for item in context.active_files or []:
            file_id = str(item.get("file_id") or "").strip()
            if file_id:
                allowed.add(file_id)
        if not allowed or any(item not in allowed for item in requested_ids):
            raise ToolRuntimeException("PERMISSION_DENIED", "工具尝试访问未授权文件。")
    if not allow_file_path and args.get("file_path"):
        raise ToolRuntimeException("PERMISSION_DENIED", "该工具不允许直接访问 file_path。")
