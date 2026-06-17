from __future__ import annotations

from backend.agent.planning import PlanValidator, ToolCatalog
from backend.agent.planning.plan_types import LLMPlan
from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState


class ValidateNode(GraphNode):
    name = "validate"
    status_text = "正在校验工具参数。"

    def __init__(self, *, validator: PlanValidator | None = None, tool_catalog: ToolCatalog | None = None) -> None:
        self.tool_catalog = tool_catalog or ToolCatalog()
        self.validator = validator or PlanValidator(catalog=self.tool_catalog)

    def run(self, state: GraphState) -> GraphState:
        if state.observations.get("status") == "handled":
            return state
        normalized = state.normalized_message
        plan = state.plan
        if not normalized or plan is None:
            state.should_fallback = True
            state.fallback_reason = "缺少可校验计划。"
            return state

        if not isinstance(plan, LLMPlan):
            state.validated_plan = plan
            state.debug["validated_plan"] = {"valid": True, "source": "trusted_legacy_plan"}
            return state

        confirmation = self._confirmation_message(plan)
        if confirmation:
            state.requires_confirmation = True
            state.confirmation_message = confirmation
            state.validated_plan = plan
            state.observations["status"] = "need_user_input"
            state.observations["reason"] = "requires_confirmation"
            state.debug["validated_plan"] = {"valid": False, "requires_confirmation": True, "plan": plan.to_dict()}
            return state

        validation = self.validator.validate(plan, normalized)
        state.validation_result = validation
        state.debug["validated_plan"] = validation.to_dict()
        if validation.valid:
            state.validated_plan = validation.plan or plan
            return state
        if validation.should_fallback:
            state.should_fallback = True
            state.fallback_reason = validation.fallback_reason or "增强计划校验失败，回退旧流程。"
            return state
        state.validated_plan = validation.plan or plan
        for error in validation.errors:
            state.add_error(error, node=self.name, recoverable=True)
        state.observations["status"] = "need_user_input"
        state.observations["reason"] = "validation_failed"
        return state

    def _confirmation_message(self, plan: LLMPlan) -> str:
        risky_steps: list[str] = []
        for step in plan.steps:
            tool = self.tool_catalog.get(step.tool_name)
            action = tool.get_action(step.action_name) if tool else None
            if not action:
                continue
            confirmed = bool((step.args or {}).get("confirmed"))
            if (plan.requires_confirmation or action.requires_confirmation or action.danger_level in {"medium", "high"}) and not confirmed:
                risky_steps.append(f"{tool.display_name}/{action.display_name or action.action_name}")
        if not risky_steps:
            return ""
        return "这个操作需要你先确认后才能执行：" + "、".join(risky_steps) + "。请确认是否继续。"

    def end_summary(self, state: GraphState) -> str:
        if state.requires_confirmation:
            return "工具参数校验完成，需要用户确认。"
        if state.should_fallback:
            return "工具参数校验未通过，准备回退旧流程。"
        if state.validation_result and not state.validation_result.valid:
            return "工具参数校验未通过，需要补充信息。"
        return "工具参数校验通过。"
