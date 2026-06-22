from __future__ import annotations

from backend.agent.types import AgentPlan, IntentResult
from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState


CONTEXTUAL_INTENTS = {
    "context_missing_analysis",
    "task_state_status",
    "last_prediction",
    "last_analysis_explanation",
    "last_analysis_followup",
    "explain_result",
    "generate_report",
    "find_similar_history",
}


class ContextNode(GraphNode):
    name = "context"
    status_text = "正在整理上下文。"

    def run(self, state: GraphState) -> GraphState:
        normalized = state.normalized_message
        if not normalized:
            state.add_error("尚未完成消息标准化。", node=self.name, recoverable=True)
            return state

        context: dict = {"warnings": []}
        try:
            from backend.services.workspace_manager import WorkspaceManager

            manager = WorkspaceManager()
            workspace_context = manager.read_workspace_context(normalized.user_id, normalized.conversation_id) if normalized.conversation_id else {}
            context["workspace"] = workspace_context or {}
            context["active_files"] = list((workspace_context or {}).get("active_files") or [])
            context["task_state"] = dict((workspace_context or {}).get("task_state") or {})
        except Exception as exc:
            context["warnings"].append(f"workspace context unavailable: {exc}")

        try:
            from backend.services.user_memory_manager import UserMemoryManager

            context["memory"] = UserMemoryManager().get_user_memory(normalized.user_id)
        except Exception as exc:
            context["warnings"].append(f"user memory unavailable: {exc}")

        try:
            from backend.tasks import get_task_manager

            task_manager = get_task_manager()
            context["recent_tasks"] = task_manager.list_tasks(user_id=normalized.user_id, workspace_id=normalized.workspace_id, limit=5)
        except Exception as exc:
            context["warnings"].append(f"task state unavailable: {exc}")

        state.debug["context"] = context
        for warning in context.get("warnings") or []:
            state.add_error(warning, node=self.name, error_type="warning", recoverable=True)
        self._try_legacy_contextual_shortcut(state)
        return state

    def _is_table_followup_query(self, message: str) -> bool:
        text = str(message or "").strip()
        return text.startswith("按") or any(marker in text for marker in ("分组", "每个城市", "每个省", "各城市", "各省", "按城市", "按省份"))

    def _try_legacy_contextual_shortcut(self, state: GraphState) -> None:
        normalized = state.normalized_message
        if not normalized or bool(state.request_payload.get("explicit_has_file")):
            return
        if normalized.has_file and normalized.file_type == "table" and self._is_table_followup_query(normalized.message):
            return
        try:
            from backend.agent.agent_service import RamanAgentService

            response = RamanAgentService().chat(
                normalized.message,
                debug=normalized.debug,
                session_id=normalized.session_id,
                extra_params={
                    "provider_id": normalized.provider_id,
                    "model_id": normalized.model_id,
                    "user_id": normalized.user_id,
                    "conversation_id": normalized.conversation_id,
                    "session_id": normalized.session_id,
                },
            )
        except Exception as exc:
            state.add_error(f"legacy contextual fallback unavailable: {exc}", node=self.name, error_type="warning", recoverable=True)
            return
        response_intent = str(response.get("intent") or "").strip()
        if response_intent not in CONTEXTUAL_INTENTS:
            return
        response.setdefault("route", "session_context")
        state.execution_results = response
        state.intent = IntentResult(
            intent=response_intent,
            confidence=1.0,
            reason="旧会话上下文 fallback 命中。",
            recommended_route="session_context",
            requires_llm=True,
        )
        state.plan = AgentPlan(route_type="session_context", steps=["legacy_contextual_fallback"])
        state.validated_plan = state.plan
        state.observations["status"] = "handled"
        state.observations["reason"] = "legacy_contextual_fallback"

    def end_summary(self, state: GraphState) -> str:
        warnings = (state.debug.get("context") or {}).get("warnings") or []
        if warnings:
            return "上下文整理完成，部分上下文暂不可用。"
        return "上下文整理完成。"
