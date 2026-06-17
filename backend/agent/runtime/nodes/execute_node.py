from __future__ import annotations

import logging
from typing import Any

from backend.agent.planning import PlanExecutor
from backend.agent.planning.plan_types import LLMPlan
from backend.agent.response_builder import ResponseBuilder
from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState
from backend.agent.types import AgentPlan, IntentResult, NormalizedMessage
from backend.schemas.agent_response import AgentResponse
from backend.services.llm_service import LLMService
from backend.skills.executable_runner import ExecutableSkillRunner
from backend.skills.prompt_only_runner import PromptOnlySkillRunner
from backend.tools.tool_runner import ToolRunner


logger = logging.getLogger(__name__)


class LegacyPlanExecutor:
    """Small adapter that preserves the old Orchestrator execution behavior."""

    def __init__(self) -> None:
        self.prompt_only_runner = PromptOnlySkillRunner()
        self.executable_runner = ExecutableSkillRunner()
        self.tool_runner = ToolRunner()

    def execute(self, normalized: NormalizedMessage, intent: IntentResult, plan: AgentPlan) -> dict[str, Any] | AgentResponse:
        if plan.route_type == "rag":
            return self._run_rag(normalized, intent, plan)

        if plan.route_type == "skill":
            if plan.skill_mode == "prompt_only":
                return self.prompt_only_runner.run(plan.skill_name or "", normalized)
            return self.executable_runner.run(
                plan.skill_name or "",
                normalized,
                action_name=plan.action_name,
                table_query_plan=(plan.debug or {}).get("table_query_plan"),
            )

        if plan.route_type == "tool":
            if plan.tool_name == "document_tool":
                doc_result = self.tool_runner.run("document_tool", normalized)
                if not doc_result.success:
                    return doc_result
                context = {
                    "document_excerpt": doc_result.data.get("document_excerpt"),
                    "relevant_chunks": doc_result.data.get("relevant_chunks") or [],
                }
                llm_result = LLMService(
                    provider_id=normalized.provider_id,
                    model_id=normalized.model_id,
                    user_id=normalized.user_id,
                    conversation_id=normalized.conversation_id,
                ).generate_general_reply(normalized.message, system_context=context)
                return AgentResponse(
                    success=bool(llm_result.get("reply")),
                    reply=str(llm_result.get("reply") or "").strip(),
                    intent=intent.intent,
                    route="tool",
                    tool_used=True,
                    tool_name="document_tool",
                    model_provider=str((llm_result.get("model_info") or {}).get("provider") or normalized.provider_id or "") or None,
                    model_name=str((llm_result.get("model_info") or {}).get("model") or normalized.model_id or "") or None,
                    data=doc_result.data,
                    model_info=dict(llm_result.get("model_info") or {}),
                    llm_model_info=dict(llm_result.get("model_info") or {}),
                    error_message=None if llm_result.get("reply") else llm_result.get("error_message"),
                )
            return self.tool_runner.run(plan.tool_name or "", normalized)

        if plan.route_type == "model":
            if intent.intent == "general_chat":
                legacy_response = self._run_legacy_fallback(normalized)
                legacy_response["route"] = "model"
                return legacy_response
            if intent.intent == "raman_analysis" and any(keyword in normalized.message for keyword in ("质量", "峰", "这个光谱", "这个谱图")):
                return self._run_legacy_fallback(normalized)
            llm_result = LLMService(
                provider_id=normalized.provider_id,
                model_id=normalized.model_id,
                user_id=normalized.user_id,
                conversation_id=normalized.conversation_id,
            ).generate_general_reply(normalized.message)
            return AgentResponse(
                success=bool(llm_result.get("reply")),
                reply=str(llm_result.get("reply") or "").strip(),
                intent=intent.intent,
                route="model",
                model_provider=str((llm_result.get("model_info") or {}).get("provider") or normalized.provider_id or "") or None,
                model_name=str((llm_result.get("model_info") or {}).get("model") or normalized.model_id or "") or None,
                model_info=dict(llm_result.get("model_info") or {}),
                llm_model_info=dict(llm_result.get("model_info") or {}),
                error_message=None if llm_result.get("reply") else llm_result.get("error_message"),
            )

        if plan.route_type == "hybrid" and normalized.has_file and normalized.file_path:
            from backend.agent import agent_router as legacy_router

            return legacy_router._analyze_uploaded_file_with_skills(
                save_path=legacy_router.Path(normalized.file_path),
                message=normalized.message,
                session_id=normalized.session_id,
                metadata=normalized.metadata,
                debug=normalized.debug,
            )

        return self._run_legacy_fallback(normalized)

    def _run_rag(self, normalized: NormalizedMessage, intent: IntentResult, plan: AgentPlan) -> AgentResponse:
        from backend.services.knowledge_base import KnowledgeBaseService
        from backend.services.rag import RAGService

        rag_scope = plan.rag_scope or normalized.rag_scope or "conversation"
        if rag_scope not in {"conversation", "knowledge_base", "mixed"}:
            rag_scope = "conversation"
        file_ids = list(normalized.file_ids or [])
        if not file_ids and normalized.files:
            file_ids = [str(item.get("file_id") or "").strip() for item in normalized.files if str(item.get("file_id") or "").strip()]
        knowledge_base_ids = list(plan.knowledge_base_ids or normalized.knowledge_base_ids or [])
        if rag_scope in {"knowledge_base", "mixed"} and not knowledge_base_ids:
            try:
                kb_service = KnowledgeBaseService()
                knowledge_base_ids = kb_service.authorized_enabled_ids(normalized.user_id, conversation_id=normalized.conversation_id)
                if not knowledge_base_ids:
                    knowledge_base_ids = kb_service.authorized_enabled_ids(normalized.user_id)
            except Exception as exc:
                logger.warning("Failed to resolve knowledge bases for RAG: %s", exc)
                knowledge_base_ids = []
        if rag_scope in {"knowledge_base", "mixed"} and not knowledge_base_ids:
            return AgentResponse(
                success=False,
                reply="当前没有可用或已绑定的知识库。请先创建知识库、上传资料，并在当前会话中启用它。",
                intent=intent.intent,
                route="rag",
                error_message="NO_KNOWLEDGE_BASE_AVAILABLE",
                conversation_id=normalized.conversation_id,
                session_id=normalized.session_id,
                data={"rag_scope": rag_scope, "knowledge_base_ids": []},
                source="rag",
            )
        answer = RAGService().answer_with_rag(
            normalized.message,
            normalized.user_id,
            normalized.conversation_id,
            file_ids=file_ids,
            knowledge_base_ids=knowledge_base_ids,
            rag_scope=rag_scope,
        )
        payload = answer.to_dict()
        model_info = dict(payload.get("model_info") or {})
        return AgentResponse(
            success=bool(payload.get("success")),
            reply=str(payload.get("answer") or payload.get("reply") or ""),
            intent=intent.intent,
            route="rag",
            model_provider=str(model_info.get("provider") or normalized.provider_id or "") or None,
            model_name=str(model_info.get("model") or normalized.model_id or "") or None,
            model_info=model_info,
            llm_model_info=model_info,
            error_message=payload.get("error_message"),
            conversation_id=normalized.conversation_id,
            session_id=normalized.session_id,
            data={
                "rag_scope": rag_scope,
                "retrieval_mode": payload.get("retrieval_mode"),
                "rerank": payload.get("rerank") or (payload.get("rag") or {}).get("rerank") or {},
                "citations": payload.get("citations") or [],
                "retrieved_chunks": payload.get("retrieved_chunks") or [],
                "source_breakdown": payload.get("source_breakdown") or {},
                "rag": payload.get("rag") or {},
                "file_ids": file_ids,
                "knowledge_base_ids": knowledge_base_ids,
            },
            source="rag",
        )

    def _run_legacy_fallback(self, normalized: NormalizedMessage) -> dict[str, Any]:
        from backend.agent.agent_service import RamanAgentService

        service = RamanAgentService()
        return service.chat(
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


class ExecuteNode(GraphNode):
    name = "execute"
    status_text = "正在执行工具。"

    def __init__(self, *, plan_executor: PlanExecutor | None = None, legacy_executor: LegacyPlanExecutor | None = None) -> None:
        self.plan_executor = plan_executor or PlanExecutor()
        self.legacy_executor = legacy_executor or LegacyPlanExecutor()
        self.response_builder = ResponseBuilder()

    def run(self, state: GraphState) -> GraphState:
        if state.observations.get("status") == "handled":
            return state
        if state.requires_confirmation or state.should_fallback:
            return state
        if state.observations.get("status") == "need_user_input":
            return state
        normalized = state.normalized_message
        intent = state.intent
        plan = state.validated_plan or state.plan
        if not normalized or not intent or plan is None:
            state.should_fallback = True
            state.fallback_reason = "执行阶段缺少 normalized_message、intent 或 plan。"
            return state
        if isinstance(plan, LLMPlan):
            state.execution_results = self.plan_executor.execute(plan, normalized)
            return state
        state.execution_results = self.legacy_executor.execute(normalized, intent, plan)
        return state

    def end_summary(self, state: GraphState) -> str:
        if state.requires_confirmation:
            return "执行已暂停，等待用户确认。"
        if state.observations.get("status") == "need_user_input":
            return "执行已暂停，等待用户补充信息。"
        if state.should_fallback:
            return "执行阶段准备回退旧流程。"
        result = state.execution_results
        success = bool(getattr(result, "success", None) if not isinstance(result, dict) else result.get("success"))
        return "工具执行完成。" if success else "工具执行失败或未返回成功状态。"

    def trace_data(self, state: GraphState) -> dict:
        plan = state.validated_plan or state.plan
        if isinstance(plan, LLMPlan):
            return {"plan_type": plan.plan_type, "steps": [step.to_dict() for step in plan.steps]}
        if hasattr(plan, "to_dict"):
            return plan.to_dict()
        return {}
