from __future__ import annotations

import logging
import time
import asyncio
from typing import Any

from backend.agent.intent_router import IntentRouter
from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.planner import Planner
from backend.agent.planning import LLMPlanner, PlanExecutor, PlanValidator, ToolCatalog
from backend.agent.streaming import StreamEventBuilder, compact_response_for_stream, split_text_for_stream
from backend.agent.response_builder import ResponseBuilder
from backend.agent.types import AgentDecision, AgentPlan, IntentResult, NormalizedMessage
from backend.schemas.agent_stream import AgentStreamEvent
from backend.schemas.agent_response import AgentResponse
from backend.services.llm_service import LLMService
from backend.skills.executable_runner import ExecutableSkillRunner
from backend.skills.prompt_only_runner import PromptOnlySkillRunner
from backend.tools.document_tool import DocumentTool
from backend.tools.tool_runner import ToolRunner


logger = logging.getLogger(__name__)


SIMULATED_STREAM_ROUTES = {"skill", "tool", "rag", "hybrid", "session_context"}
SIMULATED_STREAM_DELTA_DELAY_SECONDS = 0.018


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
        self.tool_catalog = ToolCatalog()
        self.llm_planner = LLMPlanner()
        self.plan_validator = PlanValidator(catalog=self.tool_catalog)
        self.plan_executor = PlanExecutor()

    def handle_chat(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        normalized: NormalizedMessage | None = None
        intent: IntentResult | None = None
        plan: AgentPlan | None = None
        planning_debug: dict[str, Any] = {}
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
            planning_debug["rule_intent"] = intent.to_dict()
            planning_debug.setdefault("llm_plan_raw", "")
            planning_debug.setdefault("validated_plan", None)
            planning_debug.setdefault("fallback_reason", "")
            if not self._should_use_legacy_rule(normalized, intent):
                planning_response, planning_debug = self._try_enhanced_planning(normalized, intent, started, planning_debug)
                if planning_response is not None:
                    return planning_response
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
            self._attach_debug_payload(response, normalized, intent, plan, planning_debug)
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

    async def handle_chat_stream(self, request_payload: dict[str, Any]):
        """流式聊天入口，输出 AgentStreamEvent。

        只暴露用户可见的阶段、工具状态和最终回答，不输出隐藏推理过程。
        """
        started = time.perf_counter()
        builder = StreamEventBuilder(
            conversation_id=str(request_payload.get("conversation_id") or request_payload.get("session_id") or "") or None,
            session_id=str(request_payload.get("session_id") or request_payload.get("conversation_id") or "") or None,
        )
        normalized: NormalizedMessage | None = None
        final_sent = False

        async def emit(event: AgentStreamEvent):
            await self._pace_stream_event(event)
            return event

        try:
            yield await emit(builder.event("start", content="已收到消息，开始处理。"))
            yield await emit(builder.event("status", content="正在整理消息、文件和会话上下文。"))
            normalized = self.message_normalizer.normalize(request_payload)
            builder.conversation_id = normalized.conversation_id
            builder.session_id = normalized.session_id
            yield await emit(
                builder.event(
                    "status",
                    content="正在判断任务类型。",
                    data={
                        "has_file": normalized.has_file,
                        "file_name": normalized.file_name,
                        "file_type": normalized.file_type,
                    },
                )
            )

            if not bool(request_payload.get("explicit_has_file")):
                contextual_response = self._run_legacy_fallback(normalized)
                if str(contextual_response.get("intent") or "").strip() in self.CONTEXTUAL_INTENTS:
                    contextual_response.setdefault("route", "session_context")
                    for stream_event in self._stream_response_events(
                        builder,
                        normalized,
                        contextual_response,
                        route_hint="session_context",
                        started=started,
                    ):
                        yield await emit(stream_event)
                    final_sent = True
                    return

            intent = self.intent_router.route(normalized)
            planning_debug: dict[str, Any] = {
                "rule_intent": intent.to_dict(),
                "llm_plan_raw": "",
                "validated_plan": None,
                "fallback_reason": "",
            }
            yield await emit(
                builder.event(
                    "planner",
                    content=f"规则路由识别为 {intent.intent}，置信度 {intent.confidence:.2f}。",
                    data={"rule_intent": intent.to_dict()} if normalized.debug else {"intent": intent.intent, "confidence": intent.confidence},
                )
            )

            if not self._should_use_legacy_rule(normalized, intent):
                handled = False
                try:
                    yield await emit(builder.event("status", content="正在调用增强 Planner 生成工具计划。"))
                    planner_output = self.llm_planner.plan(normalized, self.tool_catalog)
                    planning_debug["llm_plan_raw"] = planner_output.raw
                    yield await emit(
                        builder.event(
                            "planner",
                            content=f"增强 Planner 生成了 {planner_output.plan.plan_type} 计划。",
                            data={"llm_plan_raw": planner_output.raw, "plan": planner_output.plan.to_dict()} if normalized.debug else {"plan_type": planner_output.plan.plan_type},
                        )
                    )
                    validation = self.plan_validator.validate(planner_output.plan, normalized)
                    planning_debug["validated_plan"] = validation.to_dict()
                    yield await emit(
                        builder.event(
                            "planner",
                            content="工具计划校验通过。" if validation.valid else "工具计划校验未通过。",
                            data=validation.to_dict() if normalized.debug else {"valid": validation.valid, "warnings": list(validation.warnings or [])},
                        )
                    )
                    if not validation.valid:
                        if validation.should_fallback:
                            planning_debug["fallback_reason"] = validation.fallback_reason or "增强规划校验失败，回退旧流程。"
                            yield await emit(builder.event("status", content="增强 Planner 不适合本次请求，正在回退旧流程。"))
                        else:
                            enhanced_intent = IntentResult(
                                intent=planner_output.plan.intent,
                                confidence=planner_output.plan.confidence,
                                reason=planner_output.plan.reason,
                                recommended_route=planner_output.plan.plan_type,
                                requires_file=planner_output.plan.requires_file,
                            )
                            enhanced_plan = AgentPlan(
                                route_type=planner_output.plan.plan_type,
                                steps=[step.step_id for step in planner_output.plan.steps],
                                debug={"enhanced_planning": validation.to_dict()},
                            )
                            result = AgentResponse(
                                success=False,
                                reply="；".join(validation.errors) or "增强规划参数校验失败。",
                                intent=enhanced_intent.intent,
                                route=enhanced_plan.route_type,
                                error_message="；".join(validation.errors) or "增强规划参数校验失败。",
                                debug=planning_debug,
                                conversation_id=normalized.conversation_id,
                                session_id=normalized.session_id,
                                source="enhanced_planning",
                            )
                            response = self.response_builder.build(result, normalized, enhanced_intent, enhanced_plan)
                            self._attach_debug_payload(response, normalized, enhanced_intent, enhanced_plan, planning_debug)
                            yield await emit(builder.event("error", content=response.get("error_message") or response.get("reply") or "计划校验失败。"))
                            for stream_event in self._stream_response_events(builder, normalized, response, route_hint=enhanced_plan.route_type, started=started):
                                yield await emit(stream_event)
                            final_sent = True
                            return
                    else:
                        validated_plan = validation.plan or planner_output.plan
                        for step in validated_plan.steps:
                            yield await emit(
                                builder.event(
                                    "tool_start",
                                    content=f"准备执行 {step.tool_name}.{step.action_name}。",
                                    data=step.to_dict(),
                                )
                            )
                            for progress in self._planned_step_progress(step):
                                yield await emit(builder.event("tool_progress", content=progress.get("content", "步骤准备中。"), data=progress.get("data") or {}))
                        result = self.plan_executor.execute(validated_plan, normalized)
                        enhanced_intent = IntentResult(
                            intent=validated_plan.intent,
                            confidence=validated_plan.confidence,
                            reason=validated_plan.reason,
                            recommended_route=validated_plan.plan_type,
                            requires_file=validated_plan.requires_file,
                            requires_tool=True,
                        )
                        enhanced_plan = AgentPlan(
                            route_type=validated_plan.plan_type,
                            tool_name=validated_plan.steps[0].tool_name if validated_plan.steps else None,
                            action_name=validated_plan.steps[0].action_name if validated_plan.steps else None,
                            steps=[step.step_id for step in validated_plan.steps],
                            debug={"enhanced_planning": validation.to_dict()},
                        )
                        response = self.response_builder.build(result, normalized, enhanced_intent, enhanced_plan)
                        self._attach_debug_payload(response, normalized, enhanced_intent, enhanced_plan, planning_debug)
                        for progress in self._result_progress_events(response):
                            yield await emit(builder.event(progress["event"], content=progress.get("content", ""), data=progress.get("data") or {}))
                        yield await emit(
                            builder.event(
                                "tool_result",
                                content="增强计划执行完成。" if response.get("success") else "增强计划执行失败。",
                                data={"success": bool(response.get("success")), "route": response.get("route"), "tool_name": response.get("tool_name")},
                            )
                        )
                        if not response.get("success"):
                            yield await emit(builder.event("error", content=response.get("error_message") or response.get("reply") or "执行失败。"))
                        for stream_event in self._stream_response_events(builder, normalized, response, route_hint=enhanced_plan.route_type, started=started):
                            yield await emit(stream_event)
                        final_sent = True
                        handled = True
                        return
                except Exception as exc:
                    logger.warning("Enhanced streaming planning failed, fallback to legacy planner: %s", exc, exc_info=True)
                    planning_debug["fallback_reason"] = f"增强规划异常，回退旧流程：{exc}"
                    yield await emit(builder.event("status", content="增强 Planner 失败，正在回退旧流程。", data={"fallback_reason": planning_debug["fallback_reason"]} if normalized.debug else {}))
                if handled:
                    return

            plan = self.planner.make_plan(normalized, intent)
            yield await emit(
                builder.event(
                    "planner",
                    content=f"旧 Planner 选择 {plan.route_type} 路径。",
                    data=plan.to_dict() if normalized.debug else {"route_type": plan.route_type, "skill_name": plan.skill_name, "tool_name": plan.tool_name},
                )
            )
            if plan.route_type == "model" and intent.intent == "general_chat":
                yield await emit(builder.event("status", content="正在调用大模型生成流式回复。"))
                reply_chunks: list[str] = []
                llm_final: dict[str, Any] = {}
                llm_service = LLMService(
                    provider_id=normalized.provider_id,
                    model_id=normalized.model_id,
                    user_id=normalized.user_id,
                    conversation_id=normalized.conversation_id,
                )
                for item in llm_service.generate_general_reply_stream(normalized.message):
                    if item.get("event") == "delta":
                        chunk = str(item.get("content") or "")
                        if chunk:
                            reply_chunks.append(chunk)
                            yield await emit(builder.event("delta", content=chunk, data={"route": "model"}))
                    elif item.get("event") == "final":
                        llm_final = dict(item.get("result") or {})
                reply = str(llm_final.get("reply") or "".join(reply_chunks)).strip()
                result = AgentResponse(
                    success=bool(reply),
                    reply=reply,
                    intent=intent.intent,
                    route="model",
                    model_provider=str((llm_final.get("model_info") or {}).get("provider") or normalized.provider_id or "") or None,
                    model_name=str((llm_final.get("model_info") or {}).get("model") or normalized.model_id or "") or None,
                    model_info=dict(llm_final.get("model_info") or {}),
                    llm_model_info=dict(llm_final.get("model_info") or {}),
                    error_message=None if reply else llm_final.get("error_message") or "大模型未返回有效内容。",
                    data={"stream_mode": llm_final.get("stream_mode") or "unknown"},
                )
                response = self.response_builder.build(result, normalized, intent, plan)
                self._attach_debug_payload(response, normalized, intent, plan, planning_debug)
                if not response.get("success"):
                    yield await emit(builder.event("error", content=response.get("error_message") or "模型生成失败。"))
                for stream_event in self._stream_response_events(builder, normalized, response, route_hint=plan.route_type, started=started, emit_delta=False):
                    yield await emit(stream_event)
                final_sent = True
                return
            if plan.route_type in {"skill", "tool", "rag", "hybrid"}:
                yield await emit(
                    builder.event(
                        "tool_start",
                        content=self._legacy_tool_start_text(plan),
                        data={"route_type": plan.route_type, "skill_name": plan.skill_name, "tool_name": plan.tool_name, "action_name": plan.action_name},
                    )
                )
            result = self._execute_plan(normalized, intent, plan)
            response = self.response_builder.build(result, normalized, intent, plan)
            self._attach_debug_payload(response, normalized, intent, plan, planning_debug)
            for progress in self._result_progress_events(response):
                yield await emit(builder.event(progress["event"], content=progress.get("content", ""), data=progress.get("data") or {}))
            if plan.route_type in {"skill", "tool", "rag", "hybrid"}:
                yield await emit(
                    builder.event(
                        "tool_result",
                        content="工具执行完成。" if response.get("success") else "工具执行失败。",
                        data={"success": bool(response.get("success")), "route": response.get("route"), "skill_name": response.get("skill_name"), "tool_name": response.get("tool_name")},
                    )
                )
            if not response.get("success"):
                yield await emit(builder.event("error", content=response.get("error_message") or response.get("reply") or "处理失败。"))
            for stream_event in self._stream_response_events(builder, normalized, response, route_hint=plan.route_type, started=started):
                yield await emit(stream_event)
            final_sent = True
        except Exception as exc:
            logger.exception("AgentOrchestrator stream failed: %s", exc)
            error_text = f"流式处理失败：{exc}"
            yield await emit(builder.event("error", content=error_text, data={"error_type": type(exc).__name__}))
            fallback_response = {
                "success": False,
                "reply": error_text,
                "error_message": error_text,
                "conversation_id": builder.conversation_id,
                "session_id": builder.session_id,
                "source": "stream_error",
                "debug": {"exception_type": type(exc).__name__},
            }
            yield await emit(
                builder.event(
                    "final",
                    content=error_text,
                    data={
                        "response": fallback_response,
                        "route": "stream_error",
                        "success": False,
                        "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    },
                )
            )
            yield await emit(builder.event("done", content="流式响应已结束。", data={"elapsed_ms": int((time.perf_counter() - started) * 1000)}))
            final_sent = True
        finally:
            if not final_sent:
                yield await emit(builder.event("done", content="流式响应已结束。", data={"elapsed_ms": int((time.perf_counter() - started) * 1000)}))

    async def _pace_stream_event(self, event: AgentStreamEvent) -> None:
        if event.event != "delta":
            await asyncio.sleep(0)
            return
        route = str((event.data or {}).get("route") or "").strip().lower()
        if route in SIMULATED_STREAM_ROUTES:
            await asyncio.sleep(SIMULATED_STREAM_DELTA_DELAY_SECONDS)
            return
        await asyncio.sleep(0)

    def _stream_response_events(
        self,
        builder: StreamEventBuilder,
        normalized: NormalizedMessage,
        response: dict[str, Any],
        *,
        route_hint: str,
        started: float,
        emit_delta: bool = True,
    ):
        reply = str(response.get("reply") or response.get("llm_explanation") or response.get("error_message") or "").strip()
        if not reply:
            reply = "处理完成。" if response.get("success") else "处理失败。"
        if emit_delta:
            for chunk in split_text_for_stream(reply):
                yield builder.event("delta", content=chunk, data={"route": route_hint})
        final_payload = compact_response_for_stream(response)
        final_payload.setdefault("conversation_id", normalized.conversation_id)
        final_payload.setdefault("session_id", normalized.session_id)
        yield builder.event(
            "final",
            content=reply,
            data={
                "response": final_payload,
                "route": route_hint,
                "success": bool(response.get("success")),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        yield builder.event("done", content="流式响应已结束。", data={"elapsed_ms": int((time.perf_counter() - started) * 1000)})

    def _legacy_tool_start_text(self, plan: AgentPlan) -> str:
        if plan.route_type == "skill":
            return f"正在执行 Skill：{plan.skill_name or 'unknown'}。"
        if plan.route_type == "tool":
            return f"正在执行工具：{plan.tool_name or 'unknown'}。"
        if plan.route_type == "rag":
            return "正在检索会话或知识库资料。"
        if plan.route_type == "hybrid":
            return "正在执行文件分析流程。"
        return "正在执行计划。"

    def _planned_step_progress(self, step: Any) -> list[dict[str, Any]]:
        if step.tool_name != "raman_pipeline":
            return []
        args = dict(step.args or {})
        raw_steps = []
        if step.action_name == "run_custom_pipeline":
            raw_steps = list(args.get("steps") or [])
        elif step.action_name == "run_template_pipeline":
            template_id = str(args.get("template_id") or "")
            raw_steps = [{"algorithm_id": f"template:{template_id}", "params": {}}] if template_id else []
        elif step.action_name == "compare_pipelines":
            raw_steps = [{"algorithm_id": "compare_pipelines", "params": {"count": len(args.get("pipelines") or [])}}]
        return [
            {
                "content": f"Pipeline 步骤准备：{item.get('algorithm_id') or 'unknown'}。",
                "data": {"algorithm_id": item.get("algorithm_id"), "params": item.get("params") or {}},
            }
            for item in raw_steps
            if isinstance(item, dict)
        ]

    def _result_progress_events(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        data = response.get("data") if isinstance(response, dict) else {}
        if not isinstance(data, dict):
            return events
        step_results = []
        for result in data.get("step_results") or []:
            payload = result.get("data") if isinstance(result, dict) else None
            if isinstance(payload, dict):
                step_results.extend(payload.get("step_results") or payload.get("steps") or [])
        if not step_results and isinstance(data.get("step_results"), list):
            step_results = data.get("step_results") or []
        for index, item in enumerate(step_results, start=1):
            if not isinstance(item, dict):
                continue
            algorithm_id = item.get("algorithm_id") or item.get("display_name") or item.get("tool_name") or f"step_{index}"
            status = item.get("status") or ("success" if item.get("success") else "done")
            events.append(
                {
                    "event": "tool_progress",
                    "content": f"步骤 {index}：{algorithm_id}，状态 {status}。",
                    "data": {
                        "index": index,
                        "algorithm_id": algorithm_id,
                        "status": status,
                        "warning": item.get("warning"),
                        "error_message": item.get("error_message"),
                        "metrics": item.get("metrics") or {},
                        "artifacts": item.get("artifacts") or [],
                    },
                }
            )
        return events

    def _should_use_legacy_rule(self, normalized: NormalizedMessage, intent: IntentResult) -> bool:
        """Return True when existing high-confidence rules should bypass LLM planning."""
        if self._looks_like_raman_pipeline_request(normalized.message):
            return False
        if intent.intent in {
            "general_chat",
            "web_search",
            "model_management",
            "skill_management",
            "file_conversion",
            "report_generation",
            "image_understanding",
            "code_analysis",
        } and intent.confidence >= 0.9:
            return True
        if normalized.has_file and intent.intent in {"document_processing", "csv_analysis"} and intent.confidence >= 0.95:
            return True
        if intent.intent in {"conversation_rag", "knowledge_base_rag", "mixed_rag"} and intent.confidence >= 0.9:
            return True
        return False

    def _looks_like_raman_pipeline_request(self, message: str) -> bool:
        text = str(message or "")
        lowered = text.lower()
        markers = (
            "sg",
            "savitzky",
            "als",
            "z-score",
            "zscore",
            "z score",
            "预处理",
            "去基线",
            "归一化",
            "峰位",
            "主要峰",
            "标出来",
            "质量",
            "信噪比",
            "不要预测",
            "先不预测",
            "不同预处理",
            "比较",
            "对比",
            "深度学习",
            "去噪",
            "甲醇预测流程",
        )
        return any(marker in lowered for marker in markers) or any(marker in text for marker in markers)

    def _try_enhanced_planning(
        self,
        normalized: NormalizedMessage,
        rule_intent: IntentResult,
        started: float,
        planning_debug: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        try:
            planner_output = self.llm_planner.plan(normalized, self.tool_catalog)
            planning_debug["llm_plan_raw"] = planner_output.raw
            validation = self.plan_validator.validate(planner_output.plan, normalized)
            planning_debug["validated_plan"] = validation.to_dict()
            if not validation.valid:
                if validation.should_fallback:
                    planning_debug["fallback_reason"] = validation.fallback_reason or "增强规划校验失败，回退旧流程。"
                    return None, planning_debug
                intent = IntentResult(
                    intent=planner_output.plan.intent,
                    confidence=planner_output.plan.confidence,
                    reason=planner_output.plan.reason,
                    recommended_route=planner_output.plan.plan_type,
                    requires_file=planner_output.plan.requires_file,
                )
                plan = AgentPlan(
                    route_type=planner_output.plan.plan_type,
                    steps=[step.step_id for step in planner_output.plan.steps],
                    debug={"enhanced_planning": validation.to_dict()},
                )
                result = AgentResponse(
                    success=False,
                    reply="；".join(validation.errors) or "增强规划参数校验失败。",
                    intent=intent.intent,
                    route=plan.route_type,
                    error_message="；".join(validation.errors) or "增强规划参数校验失败。",
                    debug=planning_debug,
                    conversation_id=normalized.conversation_id,
                    session_id=normalized.session_id,
                    source="enhanced_planning",
                )
                response = self.response_builder.build(result, normalized, intent, plan)
                self._attach_debug_payload(response, normalized, intent, plan, planning_debug)
                return response, planning_debug

            validated_plan = validation.plan or planner_output.plan
            result = self.plan_executor.execute(validated_plan, normalized)
            intent = IntentResult(
                intent=validated_plan.intent,
                confidence=validated_plan.confidence,
                reason=validated_plan.reason,
                recommended_route=validated_plan.plan_type,
                requires_file=validated_plan.requires_file,
                requires_tool=True,
            )
            plan = AgentPlan(
                route_type=validated_plan.plan_type,
                tool_name=validated_plan.steps[0].tool_name if validated_plan.steps else None,
                action_name=validated_plan.steps[0].action_name if validated_plan.steps else None,
                steps=[step.step_id for step in validated_plan.steps],
                debug={"enhanced_planning": validation.to_dict()},
            )
            response = self.response_builder.build(result, normalized, intent, plan)
            self._attach_debug_payload(response, normalized, intent, plan, planning_debug)
            logger.info(
                "Enhanced planning response built: success=%s plan_type=%s intent=%s error=%s elapsed_ms=%d",
                response.get("success"),
                validated_plan.plan_type,
                validated_plan.intent,
                response.get("error_message") or "",
                int((time.perf_counter() - started) * 1000),
            )
            return response, planning_debug
        except Exception as exc:
            logger.warning("Enhanced planning failed, fallback to legacy planner: %s", exc, exc_info=True)
            planning_debug["fallback_reason"] = f"增强规划异常，回退旧流程：{exc}"
            return None, planning_debug

    def _attach_debug_payload(
        self,
        response: dict[str, Any],
        normalized: NormalizedMessage,
        intent: IntentResult,
        plan: AgentPlan,
        planning_debug: dict[str, Any] | None = None,
    ) -> None:
        if normalized.debug:
            response.setdefault("debug", {})
            if planning_debug:
                response["debug"].update(planning_debug)
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
