from __future__ import annotations

from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState


class ObserveNode(GraphNode):
    name = "observe"
    status_text = "正在观察结果。"

    def run(self, state: GraphState) -> GraphState:
        if state.requires_confirmation:
            state.observations.update({"status": "need_user_input", "reason": "requires_confirmation"})
            return state
        if state.should_fallback:
            state.observations.update({"status": "fallback", "reason": state.fallback_reason})
            return state
        if state.observations.get("status") == "need_user_input":
            return state
        result = state.execution_results
        if result is None:
            state.observations.update({"status": "fatal_error", "reason": "no_execution_result"})
            state.add_error("执行阶段没有返回结果。", node=self.name)
            return state
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
        if payload.get("success"):
            state.observations.update({"status": "success", "reason": "execution_succeeded"})
            return state
        error_text = str(payload.get("error_message") or payload.get("reply") or "")
        recoverable = self._recoverable_kind(error_text)
        if recoverable:
            state.observations.update({"status": "recoverable_error", "repair_type": recoverable, "reason": error_text})
            state.add_error(error_text, node=self.name, recoverable=True)
            return state
        state.observations.update({"status": "fatal_error", "reason": error_text or "execution_failed"})
        state.add_error(error_text or "执行失败。", node=self.name)
        return state

    def _recoverable_kind(self, error_text: str) -> str:
        text = str(error_text or "")
        if "SG window_length" in text or "window_length 必须是奇数" in text:
            return "sg_window_length"
        if "NO_KNOWLEDGE_BASE_AVAILABLE" in text or "没有可用或已绑定的知识库" in text:
            return "rag_no_knowledge_base"
        if "深度学习模型文件缺失" in text or "深度学习模型文件未配置" in text or "占位算法" in text:
            return "deep_learning_model_missing"
        return ""

    def end_summary(self, state: GraphState) -> str:
        status = state.observations.get("status") or "unknown"
        mapping = {
            "success": "结果观察完成，执行成功。",
            "recoverable_error": "结果观察完成，发现可恢复问题。",
            "fatal_error": "结果观察完成，发现不可恢复错误。",
            "need_user_input": "结果观察完成，需要用户输入。",
            "fallback": "结果观察完成，准备回退旧流程。",
        }
        return mapping.get(status, "结果观察完成。")

    def trace_data(self, state: GraphState) -> dict:
        return dict(state.observations or {})
