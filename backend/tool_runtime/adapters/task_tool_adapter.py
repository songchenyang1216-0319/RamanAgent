from __future__ import annotations

from backend.tasks import get_task_manager
from backend.tool_runtime.tool_context import ToolContext
from backend.tool_runtime.tool_result import ToolResult


class TaskToolAdapter:
    def execute(self, tool_name: str, action_name: str, args: dict, context: ToolContext) -> ToolResult:
        manager = get_task_manager()
        task_id = str(args.get("task_id") or context.task_id or "")
        if action_name == "get_task" and task_id:
            data = manager.get_task(task_id) or {}
            return ToolResult(bool(data), tool_name, action_name, summary="任务详情已获取。" if data else "任务不存在。", data=data, artifacts=list(data.get("artifacts") or []), error_code="" if data else "TASK_CANCELLED", error_message="" if data else "任务不存在。")
        return ToolResult(False, tool_name, action_name, status="failed", error_code="ACTION_NOT_FOUND", error_message=f"任务工具不支持动作：{action_name}")
