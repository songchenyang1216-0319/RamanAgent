"""Agent 系统能力大 Skill。"""

from __future__ import annotations

from typing import Any

from backend.agent.session_store import update_session
from backend.services.history_service import list_analysis_history

from .base import BaseSkill, SkillResult
from .model_health_check_skill import ModelHealthCheckSkill


class AgentSystemSkill(BaseSkill):
    """聚合系统查询、模型检查和技能列表能力。"""

    name = "agent_system_skill"
    display_name = "Agent 系统能力"
    description = "负责 RamanAgent 自身状态查询，包括当前模型、模型健康检查、最近实验、上传帮助、会话信息、Skill 列表等。"
    category = "系统检查"
    requires_file = False
    supported_file_types: list[str] = []
    usage = "可以直接询问当前模型、检查模型、查看最近实验，或查询当前 Agent 已安装的能力。"

    def __init__(self, skill_list_provider=None) -> None:
        self._model_skill = ModelHealthCheckSkill()
        self._skill_list_provider = skill_list_provider
        self.actions = [
            {
                "name": "current_model",
                "display_name": "当前模型",
                "description": "返回当前模型版本和基本信息。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "model_health_check",
                "display_name": "模型健康检查",
                "description": "检查模型文件和预测器加载状态。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "upload_help",
                "display_name": "上传帮助",
                "description": "说明如何上传 CSV 光谱文件。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "recent_experiments",
                "display_name": "最近实验",
                "description": "列出最近实验记录。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "clear_session",
                "display_name": "清空会话",
                "description": "清空当前会话中的最近分析上下文。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "list_skills",
                "display_name": "列出技能",
                "description": "返回当前 Agent 对外展示的大 Skill 列表。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
        ]

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "current_model")

        if action_name == "current_model":
            result = self._model_skill.run(check_loadable=False)
            return SkillResult(
                success=result.success,
                skill_name=self.name,
                action_name=action_name,
                summary=result.summary,
                data=dict(result.data or {}),
                errors=list(result.errors),
            )

        if action_name == "model_health_check":
            result = self._model_skill.run(check_loadable=True)
            return SkillResult(
                success=result.success,
                skill_name=self.name,
                action_name=action_name,
                summary=result.summary,
                data=dict(result.data or {}),
                errors=list(result.errors),
            )

        if action_name == "upload_help":
            return SkillResult(
                success=True,
                skill_name=self.name,
                action_name=action_name,
                summary="上传帮助已准备好。",
                data={
                    "message": "点击聊天输入框左侧的 + 选择 CSV 文件，然后可以直接发送，或补充一段说明文字后发送。CSV 建议至少包含两列：第一列波数，第二列强度。"
                },
            )

        if action_name == "recent_experiments":
            history = list_analysis_history(limit=int(kwargs.get("limit") or 5), offset=0)
            return SkillResult(
                success=True,
                skill_name=self.name,
                action_name=action_name,
                summary=f"最近实验已查询，共返回 {len(history.get('items', []) or [])} 条记录。",
                data=history,
            )

        if action_name == "clear_session":
            session_id = str(kwargs.get("session_id") or "").strip()
            if not session_id:
                return SkillResult(
                    success=False,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="清空会话需要 session_id。",
                    errors=["缺少 session_id 参数。"],
                )
            update_session(session_id, "last_analysis", None)
            update_session(session_id, "last_file", None)
            update_session(session_id, "last_report", None)
            return SkillResult(
                success=True,
                skill_name=self.name,
                action_name=action_name,
                summary="当前会话的分析上下文已清空。",
                data={"session_id": session_id},
            )

        if action_name == "list_skills":
            if self._skill_list_provider is None:
                return SkillResult(
                    success=False,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="当前没有可用的 Skill 列表提供器。",
                    errors=["skill_list_provider 未配置。"],
                )
            return SkillResult(
                success=True,
                skill_name=self.name,
                action_name=action_name,
                summary="当前大 Skill 列表已获取。",
                data=self._skill_list_provider(),
            )

        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary="当前 action 未实现。",
            errors=[f"未识别的 action: {action_name}"],
        )
