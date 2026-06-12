from __future__ import annotations

import logging
import time
from typing import Any

from backend.agent.intent_router import IntentRouter
from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.planner import Planner
from backend.agent.response_builder import ResponseBuilder
from backend.agent.types import AgentDecision, AgentPlan, IntentResult, NormalizedMessage
from backend.schemas.agent_response import AgentResponse
from backend.services.llm_service import LLMService
from backend.skills.executable_runner import ExecutableSkillRunner
from backend.skills.prompt_only_runner import PromptOnlySkillRunner
from backend.tools.document_tool import DocumentTool
from backend.tools.tool_runner import ToolRunner


logger = logging.getLogger(__name__)


class AgentOrchestrator:
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

    def __init__(self) -> None:
        self.message_normalizer = MessageNormalizer()
        self.intent_router = IntentRouter()
        self.planner = Planner()
        self.response_builder = ResponseBuilder()
        self.prompt_only_runner = PromptOnlySkillRunner()
        self.executable_runner = ExecutableSkillRunner()
        self.tool_runner = ToolRunner()
        self.document_tool = DocumentTool()

    def handle_chat(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        normalized: NormalizedMessage | None = None
        intent: IntentResult | None = None
        plan: AgentPlan | None = None
        try:
            normalized = self.message_normalizer.normalize(request_payload)
            logger.info(
                "Agent request received: conversation_id=%s user_id=%s has_file=%s file_type=%s file_name=%s provider=%s model=%s",
                normalized.conversation_id,
                normalized.user_id,
                normalized.has_file,
                normalized.file_type,
                normalized.file_name,
                normalized.provider_id or "",
                normalized.model_id or "",
            )
            if not bool(request_payload.get("explicit_has_file")):
                contextual_response = self._run_legacy_fallback(normalized)
                if str(contextual_response.get("intent") or "").strip() in self.CONTEXTUAL_INTENTS:
                    contextual_response.setdefault("route", "session_context")
                    return contextual_response
            intent = self.intent_router.route(normalized)
            logger.info("Intent routed: intent=%s confidence=%.2f reason=%s", intent.intent, intent.confidence, intent.reason)
            plan = self.planner.make_plan(normalized, intent)
            logger.info(
                "Plan generated: route_type=%s skill_name=%s skill_mode=%s tool_name=%s model_provider=%s model_name=%s",
                plan.route_type,
                plan.skill_name or "",
                plan.skill_mode or "",
                plan.tool_name or "",
                plan.model_provider or "",
                plan.model_name or "",
            )
            result = self._execute_plan(normalized, intent, plan)
            response = self.response_builder.build(result, normalized, intent, plan)
            if normalized.debug:
                response.setdefault("debug", {})
                response["debug"].update(
                    {
                        "normalized_message": {
                            "has_file": normalized.has_file,
                            "file_type": normalized.file_type,
                            "file_name": normalized.file_name,
                            "file_ids": list(normalized.file_ids or []),
                            "knowledge_base_ids": list(normalized.knowledge_base_ids or []),
                            "rag_scope": normalized.rag_scope,
                        },
                        "intent_confidence": intent.confidence,
                        "intent_reason": intent.reason,
                        "plan": plan.to_dict(),
                        "decision": AgentDecision.from_intent_and_plan(intent, plan, normalized.selected_files).to_dict(),
                    }
                )
            else:
                response["debug"] = {}
            logger.info(
                "Agent response built: success=%s route=%s skill_name=%s tool_name=%s error_message=%s elapsed_ms=%d",
                response.get("success"),
                response.get("route"),
                response.get("skill_name"),
                response.get("tool_name"),
                response.get("error_message") or "",
                int((time.perf_counter() - started) * 1000),
            )
            return response
        except Exception as exc:
            logger.exception("AgentOrchestrator failed: %s", exc)
            fallback_normalized = normalized or self.message_normalizer.normalize(request_payload)
            fallback_intent = intent or IntentResult(intent="unknown", confidence=0.0, reason=str(exc), recommended_route="fallback")
            fallback_plan = plan or AgentPlan(route_type="fallback", steps=["exception_fallback"])
            return self.response_builder.build(
                AgentResponse(
                    success=False,
                    reply="",
                    intent=fallback_intent.intent,
                    route="fallback",
                    error_message=str(exc),
                    debug={"exception_type": type(exc).__name__},
                ),
                fallback_normalized,
                fallback_intent,
                fallback_plan,
            )

    def _execute_plan(self, normalized: NormalizedMessage, intent: IntentResult, plan: AgentPlan) -> dict[str, Any] | AgentResponse:
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
