from __future__ import annotations

from backend.agent.message_normalizer import MessageNormalizer
from backend.services.llm_registry_service import LLMRegistryService
from backend.tools.tool_runner import ToolRunner
from backend.tool_runtime.tool_context import ToolContext
from backend.tool_runtime.tool_result import ToolResult


class BuiltinToolAdapter:
    def execute(self, tool_name: str, action_name: str, args: dict, context: ToolContext) -> ToolResult:
        if tool_name == "file_tool":
            normalized = self._normalized(args, context)
            result = ToolRunner().run("file_info_tool", normalized)
            return ToolResult.from_agent_response(result, tool_name=tool_name, action_name=action_name)
        if tool_name == "model_tool":
            service = LLMRegistryService()
            if action_name == "get_current_model":
                data = service.get_current_model()
                return ToolResult(True, tool_name, action_name, summary="模型信息已获取。", data=data)
            if action_name == "list_models":
                data = service.list_models()
                return ToolResult(True, tool_name, action_name, summary="模型列表已获取。", data=data)
        return ToolResult(False, tool_name, action_name, status="failed", error_code="ACTION_NOT_FOUND", error_message=f"内置工具不支持动作：{tool_name}.{action_name}")

    def _normalized(self, args: dict, context: ToolContext):
        active_file = (context.active_files or [{}])[0] if context.active_files else {}
        return MessageNormalizer().normalize(
            {
                "message": str(args.get("message") or ""),
                "file_path": args.get("file_path") or active_file.get("path") or active_file.get("file_path"),
                "file_name": active_file.get("filename"),
                "conversation_id": context.conversation_id,
                "session_id": context.session_id or context.conversation_id,
                "user_id": context.user_id,
                "debug": context.debug,
                "files": context.active_files,
                "file_ids": context.file_ids,
                "explicit_has_file": bool(args.get("file_path") or context.active_files),
            }
        )
