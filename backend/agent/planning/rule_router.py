from __future__ import annotations

import json

from backend.agent.types import NormalizedMessage

from .plan_types import LLMPlan, PlannerOutput
from .tool_catalog import ToolCatalog


class HighConfidenceRuleRouter:
    """Routes only low-risk, high-certainty requests.

    Most of these intentionally return a fallback plan so the mature legacy
    IntentRouter/Planner keeps answering system-info queries while the enhanced
    LLM planner focuses on complex tool composition.
    """

    def route(self, normalized: NormalizedMessage, catalog: ToolCatalog) -> PlannerOutput | None:
        text = str(normalized.message or "").strip()
        lowered = text.lower()
        if not text:
            return self._fallback("help", "空消息或帮助入口交由旧路由回答。")
        if any(marker in text for marker in ("当前大模型", "当前模型", "正在用什么模型")):
            return self._tool_plan("model_status", "model_tool", "get_current_model", "用户明确询问当前模型。")
        if any(marker in text for marker in ("模型列表", "可用模型")):
            return self._tool_plan("model_list", "model_tool", "list_models", "用户明确询问可用模型列表。")
        if any(marker in text for marker in ("Skill 列表", "技能列表", "已安装 Skill", "已安装技能")):
            return self._tool_plan("skill_list", "skill_tool", "list_skills", "用户明确询问已安装 Skill。")
        if any(marker in text for marker in ("登录状态", "帮助")):
            return self._fallback("system_info", "高确定系统查询交由旧路由/系统工具处理。")
        if any(marker in lowered for marker in ("file info", "metadata")) or any(marker in text for marker in ("文件信息", "文件名", "文件格式")):
            if normalized.has_file:
                payload = {
                    "plan_type": "tool",
                    "intent": "file_info",
                    "confidence": 0.96,
                    "requires_file": True,
                    "requires_confirmation": False,
                    "reason": "用户明确询问当前文件元数据。",
                    "steps": [{"step_id": "step_001", "tool_name": "file_tool", "action_name": "file_info", "args": {}}],
                }
                return PlannerOutput(plan=LLMPlan.from_dict(payload), raw=json.dumps(payload, ensure_ascii=False), source="high_confidence_rule")
        return None

    def _tool_plan(self, intent: str, tool_name: str, action_name: str, reason: str) -> PlannerOutput:
        payload = {
            "plan_type": "tool",
            "intent": intent,
            "confidence": 0.96,
            "requires_file": False,
            "requires_confirmation": False,
            "reason": reason,
            "steps": [{"step_id": "step_001", "tool_name": tool_name, "action_name": action_name, "args": {}}],
        }
        return PlannerOutput(plan=LLMPlan.from_dict(payload), raw=json.dumps(payload, ensure_ascii=False), source="high_confidence_rule")

    def _fallback(self, intent: str, reason: str) -> PlannerOutput:
        payload = {
            "plan_type": "fallback",
            "intent": intent,
            "confidence": 0.96,
            "requires_file": False,
            "requires_confirmation": False,
            "reason": reason,
            "steps": [],
        }
        return PlannerOutput(plan=LLMPlan.from_dict(payload), raw=json.dumps(payload, ensure_ascii=False), source="high_confidence_rule")
