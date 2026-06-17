from __future__ import annotations

from backend.skills.registry import execute_skill, list_skills
from backend.tool_runtime.tool_context import ToolContext
from backend.tool_runtime.tool_result import ToolResult


class SkillToolAdapter:
    TOOL_TO_SKILL = {
        "web_search": "web-search",
        "document_tool": "document-reader",
        "report_tool": "report-generator",
    }

    def execute(self, tool_name: str, action_name: str, args: dict, context: ToolContext) -> ToolResult:
        if tool_name == "skill_tool" and action_name == "list_skills":
            data = list_skills(include_actions=True)
            return ToolResult(True, tool_name, action_name, summary=f"当前共有 {data.get('total', 0)} 个 Skill。", data=data)
        skill_name = str(args.get("skill_name") or self.TOOL_TO_SKILL.get(tool_name) or tool_name)
        file_path = str(args.get("file_path") or "")
        if not file_path and context.active_files:
            file_path = str(context.active_files[0].get("path") or context.active_files[0].get("file_path") or "")
        result = execute_skill(
            skill_name,
            action_name=action_name,
            file_path=file_path,
            message=str(args.get("message") or context.metadata.get("message") or ""),
            query=str(args.get("query") or context.metadata.get("message") or ""),
            metadata=dict(context.metadata or {}),
            user_id=context.user_id,
            conversation_id=context.conversation_id,
        )
        return ToolResult(
            success=result.success,
            tool_name=tool_name,
            action_name=action_name,
            status="success" if result.success else "failed",
            summary=result.summary,
            data=dict(result.data or {}),
            artifacts=list(result.plots or []),
            error_code="" if result.success else "SKILL_EXECUTION_FAILED",
            error_message="；".join(result.errors),
        )
