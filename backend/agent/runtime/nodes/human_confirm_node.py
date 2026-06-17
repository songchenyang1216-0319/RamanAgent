from __future__ import annotations

from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState
from backend.schemas.agent_response import AgentResponse


class HumanConfirmNode(GraphNode):
    name = "human_confirm"
    status_text = "正在检查是否需要人工确认。"

    def run(self, state: GraphState) -> GraphState:
        if not state.requires_confirmation:
            return state
        state.execution_results = AgentResponse(
            success=True,
            reply=state.confirmation_message or "这个操作需要确认后才能继续。请确认是否执行。",
            intent=getattr(state.intent, "intent", "confirmation"),
            route="human_confirm",
            conversation_id=state.conversation_id,
            session_id=state.session_id,
            data={"requires_confirmation": True, "confirmation_message": state.confirmation_message},
            source="graph_runtime",
        )
        state.observations.update({"status": "need_user_input", "reason": "requires_confirmation"})
        return state

    def end_summary(self, state: GraphState) -> str:
        if state.requires_confirmation:
            return "已生成用户确认问题。"
        return "不需要人工确认。"
