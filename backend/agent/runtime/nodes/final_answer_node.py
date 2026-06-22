from __future__ import annotations

from backend.agent.planning.plan_types import LLMPlan
from backend.agent.response_builder import ResponseBuilder
from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState
from backend.agent.streaming import split_text_for_stream
from backend.agent.types import AgentPlan, IntentResult
from backend.schemas.agent_response import AgentResponse


class FinalAnswerNode(GraphNode):
    name = "final_answer"
    status_text = "正在生成最终回答。"

    def __init__(self, response_builder: ResponseBuilder | None = None) -> None:
        self.response_builder = response_builder or ResponseBuilder()

    def run(self, state: GraphState) -> GraphState:
        normalized = state.normalized_message
        if not normalized:
            response = AgentResponse(
                success=False,
                reply="请求处理失败：消息标准化未完成。",
                intent="unknown",
                route="graph_runtime",
                error_message="请求处理失败：消息标准化未完成。",
                source="graph_runtime",
            ).to_dict()
            response["debug"] = state.public_debug()
            state.final_response = response
            return state

        intent, plan = self._response_context(state)
        result = state.execution_results
        if result is None:
            result = self._fallback_result_from_state(state, intent, plan)
        response = self.response_builder.build(result, normalized, intent, plan)
        response["source"] = response.get("source") or "graph_runtime"
        response["debug"] = state.public_debug()
        if not state.debug_enabled:
            response["debug"] = {}
        state.final_response = response
        reply = str(response.get("reply") or response.get("error_message") or "")
        state.stream_events = [{"event": "delta", "content": chunk, "data": {"route": response.get("route")}} for chunk in split_text_for_stream(reply)]
        return state

    def _response_context(self, state: GraphState) -> tuple[IntentResult, AgentPlan]:
        normalized = state.normalized_message
        base_intent = state.intent or IntentResult(intent="unknown", confidence=0.0, reason="", recommended_route="fallback")
        plan = state.validated_plan or state.plan
        if isinstance(plan, LLMPlan):
            first = plan.steps[0] if plan.steps else None
            intent = IntentResult(
                intent=plan.intent,
                confidence=plan.confidence,
                reason=plan.reason,
                recommended_route=plan.plan_type,
                requires_file=plan.requires_file,
                requires_tool=True,
            )
            agent_plan = AgentPlan(
                route_type=plan.plan_type,
                tool_name=first.tool_name if first else None,
                action_name=first.action_name if first else None,
                steps=[step.step_id for step in plan.steps],
                debug={"enhanced_planning": state.validation_result.to_dict() if state.validation_result else {}},
            )
            return intent, agent_plan
        if isinstance(plan, AgentPlan):
            return base_intent, plan
        return base_intent, AgentPlan(route_type="fallback", steps=["graph_runtime_final"])

    def _fallback_result_from_state(self, state: GraphState, intent: IntentResult, plan: AgentPlan) -> AgentResponse:
        status = state.observations.get("status")
        if status == "need_user_input":
            message = self._need_user_input_message(state)
            legacy_intent, legacy_category = self._legacy_missing_file_labels(intent.intent, message)
            return AgentResponse(
                success=True,
                reply=message,
                intent=legacy_intent or intent.intent,
                route=legacy_category or plan.route_type,
                conversation_id=state.conversation_id,
                session_id=state.session_id,
                category=legacy_category or intent.intent,
                data={"requires_user_input": True, "observations": dict(state.observations or {})},
                source="graph_runtime",
            )
        error_text = "；".join(item.get("message", "") for item in state.errors if item.get("message")) or state.fallback_reason or "Graph Runtime 未生成有效结果。"
        return AgentResponse(
            success=False,
            reply=error_text,
            intent=intent.intent,
            route=plan.route_type,
            error_message=error_text,
            conversation_id=state.conversation_id,
            session_id=state.session_id,
            data={"observations": dict(state.observations or {})},
            source="graph_runtime",
        )

    def _need_user_input_message(self, state: GraphState) -> str:
        explicit = state.confirmation_message or state.observations.get("repair_message")
        if explicit:
            return str(explicit)
        errors = "；".join(item.get("message", "") for item in state.errors if item.get("message"))
        normalized = state.normalized_message
        message = str(getattr(normalized, "message", "") or "")
        if "需要 CSV" in errors or "需要先上传文件" in errors or any(marker in message for marker in ("光谱", "谱图", "拉曼", "Raman", "深度学习", "去噪", "峰", "质量")):
            return "这个请求需要先上传 CSV 文件。请点击输入框左侧的 + 选择 Raman CSV 后再发送。"
        return errors or "我需要你补充必要信息后才能继续执行。"

    def _legacy_missing_file_labels(self, intent: str, message: str) -> tuple[str | None, str | None]:
        if "需要先上传 CSV 文件" not in str(message or ""):
            return None, None
        if "quality" in intent:
            return "analyze_spectrum_quality", "tool"
        if "peak" in intent:
            return "detect_peaks", "tool"
        if "raman" in intent or "methanol" in intent:
            return intent, "tool"
        return None, None

    def end_summary(self, state: GraphState) -> str:
        if state.final_response and state.final_response.get("success"):
            return "最终回答已生成。"
        return "最终错误响应已生成。"
