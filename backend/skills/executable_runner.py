from __future__ import annotations

from typing import Any

from backend.schemas.agent_response import AgentResponse
from backend.skills.skill_registry import SkillRegistry


class ExecutableSkillRunner:
    def __init__(self) -> None:
        self.registry = SkillRegistry()

    def run(self, skill_name: str, normalized_message, action_name: str | None = None, **kwargs: Any) -> AgentResponse:
        result = self.registry.execute(
            skill_name,
            action_name=action_name or "run_uploaded_skill",
            file_path=normalized_message.file_path,
            session_id=normalized_message.session_id,
            message=normalized_message.message,
            original_message=normalized_message.message,
            metadata=normalized_message.metadata,
            table_query_plan=kwargs.get("table_query_plan"),
            task_type=kwargs.get("task_type"),
        )
        raw = dict(result.data or {})
        reply = str(
            raw.get("reply_text")
            or raw.get("analysis_markdown")
            or raw.get("markdown")
            or raw.get("summary")
            or result.summary
            or ""
        ).strip()
        need_clarification = bool(raw.get("need_clarification"))
        success = bool((result.success and (reply or raw)) or need_clarification)
        error_message = None if success else ("；".join(result.errors) or result.summary or "Skill 执行失败。")
        if not success and error_message:
            if skill_name == "data-analysis-skill" and "当前已禁用" in error_message:
                reply = "当前识别为普通表格数据，但 data-analysis-skill 未启用。你可以在 Skill 管理中启用表格数据分析 Skill。"
            elif skill_name == "data-analysis-skill" and action_name and "子能力" in error_message:
                reply = f"当前表格已识别到需要调用 `{action_name}`，但这个子能力目前被禁用了。你可以先在 Skill 管理页面重新启用它。"
            elif skill_name == "image-router-skill" and action_name and "子能力" in error_message:
                reply = f"image-router-skill 的子能力 `{action_name}` 当前被禁用。你可以在 Skill 管理页面重新启用它。"
            elif skill_name == "image-router-skill" and "当前已禁用" in error_message:
                reply = "image-router-skill 当前被禁用。你可以在 Skill 管理页面重新启用它。"
            elif not reply:
                reply = error_message
        return AgentResponse(
            success=success,
            reply=reply,
            skill_used=True,
            skill_name=skill_name,
            skill_mode=str(raw.get("skill_mode") or "executable"),
            action_name=result.action_name or action_name,
            data=raw,
            debug={"runner": "executable_runner", "need_clarification": need_clarification},
            error_message=error_message,
            source="skill_execution",
        )
