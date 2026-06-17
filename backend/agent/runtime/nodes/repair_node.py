from __future__ import annotations

from backend.agent.planning import PlanExecutor, PlanValidator
from backend.agent.planning.plan_types import LLMPlan
from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState


class RepairNode(GraphNode):
    name = "repair"
    status_text = "正在修复错误。"

    def __init__(self, *, validator: PlanValidator | None = None, executor: PlanExecutor | None = None) -> None:
        self.validator = validator or PlanValidator()
        self.executor = executor or PlanExecutor()

    def run(self, state: GraphState) -> GraphState:
        if state.observations.get("status") != "recoverable_error" or state.repair_attempts >= 1:
            return state
        repair_type = state.observations.get("repair_type")
        state.repair_attempts += 1
        if repair_type == "sg_window_length":
            return self._repair_sg_window(state)
        if repair_type == "rag_no_knowledge_base":
            state.observations.update(
                {
                    "status": "need_user_input",
                    "repair_message": "当前没有可用知识库。请先创建知识库、上传资料，并在当前会话中启用它。",
                }
            )
            return state
        if repair_type == "deep_learning_model_missing":
            state.observations.update(
                {
                    "status": "need_user_input",
                    "repair_message": "深度学习模型当前不可用。可以先使用 SG/ALS/Min-Max 等传统预处理流程，或先训练并注册对应模型。",
                }
            )
            return state
        return state

    def _repair_sg_window(self, state: GraphState) -> GraphState:
        plan = state.validated_plan if isinstance(state.validated_plan, LLMPlan) else state.plan
        normalized = state.normalized_message
        if not isinstance(plan, LLMPlan) or normalized is None:
            return state
        repaired = False
        for step in plan.steps:
            if step.tool_name != "raman_pipeline" or step.action_name != "run_custom_pipeline":
                continue
            for raw_step in list((step.args or {}).get("steps") or []):
                if not isinstance(raw_step, dict) or raw_step.get("algorithm_id") != "savitzky_golay":
                    continue
                params = dict(raw_step.get("params") or {})
                window = int(params.get("window_length", 11))
                if window % 2 == 0:
                    params["window_length"] = window + 1
                    raw_step["params"] = params
                    repaired = True
        if not repaired:
            return state
        validation = self.validator.validate(plan, normalized)
        state.validation_result = validation
        state.debug["repair"] = {"type": "sg_window_length", "valid_after_repair": validation.valid}
        if validation.valid:
            state.validated_plan = validation.plan or plan
            state.execution_results = self.executor.execute(state.validated_plan, normalized)
            payload = state.execution_results.to_dict() if hasattr(state.execution_results, "to_dict") else dict(state.execution_results or {})
            state.observations.update({"status": "success" if payload.get("success") else "fatal_error", "repair_type": "sg_window_length"})
        else:
            state.observations.update({"status": "need_user_input", "repair_message": "SG window_length 已尝试修复，但计划仍未通过校验。"})
        return state

    def end_summary(self, state: GraphState) -> str:
        if state.repair_attempts <= 0:
            return "没有需要自动修复的问题。"
        if state.observations.get("status") == "success":
            return "自动修复完成，已重新执行。"
        return "自动修复完成，需要用户继续处理。"

    def trace_data(self, state: GraphState) -> dict:
        return {"repair_attempts": state.repair_attempts, **dict(state.observations or {})}
