from __future__ import annotations

import time
from typing import Any

from backend.agent.planning.tool_catalog import ToolCatalog
from backend.agent.planning.tool_schema import ActionSpec, ToolSpec
from backend.tool_runtime.adapters import BuiltinToolAdapter, MCPRuntimeToolAdapter, RAGToolAdapter, RamanToolAdapter, SkillToolAdapter, TaskToolAdapter
from backend.tool_runtime.tool_audit import record_tool_audit
from backend.tool_runtime.tool_confirmation import create_confirmation, get_confirmation, needs_confirmation
from backend.tool_runtime.tool_context import ToolContext
from backend.tool_runtime.tool_errors import ToolRuntimeException, classify_exception
from backend.tool_runtime.tool_permissions import assert_file_scope, assert_tool_permission
from backend.tool_runtime.tool_result import ToolResult
from backend.tool_runtime.tool_retry import run_with_retry
from backend.tool_runtime.tool_timeout import run_with_timeout


class ToolRuntime:
    def __init__(self, catalog: ToolCatalog | None = None) -> None:
        self.catalog = catalog or ToolCatalog()
        self.builtin_adapter = BuiltinToolAdapter()
        self.raman_adapter = RamanToolAdapter()
        self.rag_adapter = RAGToolAdapter()
        self.skill_adapter = SkillToolAdapter()
        self.mcp_adapter = MCPRuntimeToolAdapter()
        self.task_adapter = TaskToolAdapter()

    def execute(self, tool_name: str, action_name: str, args: dict | None, context: ToolContext) -> ToolResult:
        started = time.perf_counter()
        args = dict(args or {})
        audit_id = ""
        try:
            tool = self.catalog.get(tool_name)
            if tool is None:
                raise ToolRuntimeException("TOOL_NOT_FOUND", f"工具不存在：{tool_name}")
            action = tool.get_action(action_name)
            if action is None:
                raise ToolRuntimeException("ACTION_NOT_FOUND", f"工具动作不存在：{tool_name}.{action_name}")
            if not tool.enabled:
                raise ToolRuntimeException("TOOL_NOT_FOUND", f"工具已禁用：{tool_name}")
            if not tool.available:
                code = "MCP_SERVER_UNAVAILABLE" if tool.source == "mcp" else "TOOL_UNAVAILABLE"
                reason = tool.unavailable_reason or "工具当前不可用。"
                raise ToolRuntimeException(code, reason)
            self._validate_arguments(action, args)
            assert_tool_permission(tool, action, context)
            assert_file_scope(args, context)
            self._assert_confirmation_not_rejected(args)
            if needs_confirmation(tool, action, args):
                confirmation = create_confirmation(tool, action, args, context)
                audit_id = record_tool_audit(
                    context=context,
                    action="tool.confirmation_required",
                    resource_id=f"{tool_name}.{action_name}",
                    detail={"confirmation_id": confirmation.confirmation_id, "danger_level": confirmation.danger_level},
                )
                return ToolResult(
                    success=True,
                    tool_name=tool_name,
                    action_name=action_name,
                    status="confirmation_required",
                    summary=confirmation.message,
                    requires_confirmation=True,
                    confirmation_payload=confirmation.to_dict(),
                    error_code="CONFIRMATION_REQUIRED",
                    warning=confirmation.message,
                    elapsed_ms=self._elapsed(started),
                    audit_id=audit_id,
                )

            audit_id = record_tool_audit(
                context=context,
                action="tool.execute.start",
                resource_id=f"{tool_name}.{action_name}",
                detail={"tool_name": tool_name, "action_name": action_name, "source": tool.source, "args": args},
            )

            def call() -> ToolResult:
                return run_with_timeout(lambda: self._dispatch(tool, action, args, context), action.timeout_seconds)

            result = run_with_retry(call, action.retry_policy)
            result.elapsed_ms = self._elapsed(started)
            result.audit_id = audit_id
            record_tool_audit(
                context=context,
                action="tool.execute.finish",
                resource_id=f"{tool_name}.{action_name}",
                detail={"success": result.success, "error_code": result.error_code, "elapsed_ms": result.elapsed_ms, "audit_id": audit_id},
            )
            return result
        except ToolRuntimeException as exc:
            return self._failure(tool_name, action_name, exc.error_code, exc.error_message, started, context, audit_id, exc.exception_type)
        except Exception as exc:
            code, message = classify_exception(exc)
            return self._failure(tool_name, action_name, code, message, started, context, audit_id, type(exc).__name__)

    def _assert_confirmation_not_rejected(self, args: dict[str, Any]) -> None:
        confirmation_id = str(args.get("confirmation_id") or "").strip()
        if not confirmation_id:
            return
        confirmation = get_confirmation(confirmation_id)
        if confirmation and confirmation.get("status") == "rejected":
            raise ToolRuntimeException("CONFIRMATION_REJECTED", "用户已拒绝该高风险操作。")

    def _dispatch(self, tool: ToolSpec, action: ActionSpec, args: dict[str, Any], context: ToolContext) -> ToolResult:
        tool_name = tool.tool_name
        action_name = action.action_name
        if tool_name.startswith("mcp_") or tool.source == "mcp":
            return self.mcp_adapter.execute(tool_name, action_name, args, context)
        if tool_name in {"raman_pipeline", "raman_model"}:
            return self.raman_adapter.execute(tool_name, action_name, args, context)
        if tool_name == "rag":
            return self.rag_adapter.execute(tool_name, action_name, args, context)
        if tool_name in {"web_search", "document_tool", "report_tool", "skill_tool"}:
            return self.skill_adapter.execute(tool_name, action_name, args, context)
        if tool_name == "task_tool":
            return self.task_adapter.execute(tool_name, action_name, args, context)
        return self.builtin_adapter.execute(tool_name, action_name, args, context)

    def _validate_arguments(self, action: ActionSpec, args: dict[str, Any]) -> None:
        schema = dict(action.input_schema or action.arg_schema or {})
        required = list(action.required_args or schema.get("required") or [])
        for arg in required:
            if arg not in args:
                raise ToolRuntimeException("INVALID_ARGUMENTS", f"缺少必填参数：{arg}")
        properties = dict(schema.get("properties") or {})
        for name, spec in properties.items():
            if name not in args or args.get(name) is None:
                continue
            expected = spec.get("type") if isinstance(spec, dict) else None
            if expected and not self._type_matches(args.get(name), expected):
                raise ToolRuntimeException("INVALID_ARGUMENTS", f"参数 {name} 类型不符合 schema：期望 {expected}。")

    def _type_matches(self, value: Any, expected: str | list[str]) -> bool:
        types = expected if isinstance(expected, list) else [expected]
        mapping = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        return any(isinstance(value, mapping.get(item, object)) for item in types)

    def _failure(self, tool_name: str, action_name: str, code: str, message: str, started: float, context: ToolContext, audit_id: str, exception_type: str = "") -> ToolResult:
        try:
            record_tool_audit(
                context=context,
                action="tool.execute.error",
                resource_id=f"{tool_name}.{action_name}",
                detail={"success": False, "error_code": code, "error_message": message, "exception_type": exception_type},
            )
        except Exception:
            pass
        return ToolResult(
            success=False,
            tool_name=tool_name,
            action_name=action_name,
            status="failed",
            error_code=code,
            error_message=message,
            summary=message,
            elapsed_ms=self._elapsed(started),
            audit_id=audit_id,
        )

    def _elapsed(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
