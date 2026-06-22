from __future__ import annotations

import logging
import time
from typing import Any, Iterable

from backend.agent.runtime.graph_errors import GraphFallbackRequested
from backend.agent.runtime.graph_state import GraphState
from backend.agent.runtime.nodes import (
    ContextNode,
    ExecuteNode,
    FinalAnswerNode,
    HumanConfirmNode,
    IntentNode,
    NormalizeNode,
    ObserveNode,
    PlannerNode,
    RepairNode,
    ValidateNode,
)
from backend.agent.streaming import StreamEventBuilder, compact_response_for_stream, split_text_for_stream
from backend.schemas.agent_response import AgentResponse
from backend.schemas.agent_stream import AgentStreamEvent


logger = logging.getLogger(__name__)


class GraphRunner:
    """Stateful graph runtime for Agent orchestration.

    The runner is intentionally thin: nodes reuse existing router/planner/
    validator/executor components, while this class owns state transitions,
    public trace events and final error closure.
    """

    def __init__(self, *, raise_on_error: bool = False) -> None:
        self.raise_on_error = raise_on_error
        self.nodes = [
            NormalizeNode(),
            ContextNode(),
            IntentNode(),
            PlannerNode(),
            ValidateNode(),
            ExecuteNode(),
            ObserveNode(),
            RepairNode(),
            HumanConfirmNode(),
            FinalAnswerNode(),
        ]

    def run(self, request_payload: dict[str, Any]) -> dict[str, Any]:
        state = GraphState(request_payload=dict(request_payload or {}))
        try:
            state = self._run_nodes(state)
            return state.final_response or self._error_response(state, "Graph Runtime 未生成最终响应。")
        except GraphFallbackRequested:
            if self.raise_on_error:
                raise
            return self._error_response(state, state.fallback_reason or "Graph Runtime 请求回退旧编排。")
        except Exception as exc:
            logger.exception("GraphRunner failed: %s", exc)
            if self.raise_on_error:
                raise
            return self._error_response(state, f"Graph Runtime 执行失败：{exc}", error_type=type(exc).__name__)

    def run_stream(self, request_payload: dict[str, Any]) -> Iterable[AgentStreamEvent]:
        state = GraphState(request_payload=dict(request_payload or {}))
        builder = StreamEventBuilder(
            conversation_id=str(request_payload.get("conversation_id") or request_payload.get("session_id") or "") or None,
            session_id=str(request_payload.get("session_id") or request_payload.get("conversation_id") or "") or None,
        )
        started = time.perf_counter()
        try:
            yield builder.event("start", content="已收到消息，开始处理。", data={"runtime": "graph"})
            for node in self.nodes:
                pre_event = self._node_pre_event(builder, node.name, node.status_text, state)
                if pre_event:
                    yield pre_event
                if node.name == "execute":
                    tool_start = self._tool_start_event(builder, state)
                    if tool_start:
                        yield tool_start
                state = node(state)
                builder.conversation_id = state.conversation_id or builder.conversation_id
                builder.session_id = state.session_id or builder.session_id
                post_events = list(self._node_post_events(builder, node.name, state))
                for event in post_events:
                    yield event
                if state.should_fallback:
                    raise GraphFallbackRequested(state.fallback_reason or "Graph Runtime 请求回退旧编排。")

            response = state.final_response or self._error_response(state, "Graph Runtime 未生成最终响应。")
            reply = str(response.get("reply") or response.get("error_message") or "")
            for chunk in split_text_for_stream(reply):
                yield builder.event("delta", content=chunk, data={"route": response.get("route") or "graph"})
            final_payload = compact_response_for_stream(response)
            yield builder.event(
                "final",
                content=reply,
                data={
                    "response": final_payload,
                    "route": response.get("route") or "graph",
                    "success": bool(response.get("success")),
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                },
            )
            yield builder.event("done", content="流式响应已结束。", data={"elapsed_ms": int((time.perf_counter() - started) * 1000)})
        except GraphFallbackRequested:
            if self.raise_on_error:
                raise
            response = self._error_response(state, state.fallback_reason or "Graph Runtime 请求回退旧编排。")
            yield from self._error_stream(builder, response, started)
        except Exception as exc:
            logger.exception("GraphRunner stream failed: %s", exc)
            if self.raise_on_error:
                raise
            response = self._error_response(state, f"Graph Runtime 流式执行失败：{exc}", error_type=type(exc).__name__)
            yield from self._error_stream(builder, response, started)

    def _run_nodes(self, state: GraphState) -> GraphState:
        for node in self.nodes:
            state = node(state)
            if state.should_fallback:
                raise GraphFallbackRequested(state.fallback_reason or "Graph Runtime 请求回退旧编排。")
        return state

    def _node_pre_event(self, builder: StreamEventBuilder, node_name: str, content: str, state: GraphState) -> AgentStreamEvent | None:
        if node_name == "final_answer":
            return builder.event("status", content=content, data={"node": node_name})
        event = "planner" if node_name == "planner" else "status"
        if node_name == "execute":
            event = "tool_progress"
        return builder.event(event, content=content, data={"node": node_name})

    def _node_post_events(self, builder: StreamEventBuilder, node_name: str, state: GraphState) -> Iterable[AgentStreamEvent]:
        if node_name == "intent" and state.intent:
            yield builder.event(
                "planner",
                content=f"规则路由识别为 {state.intent.intent}，置信度 {state.intent.confidence:.2f}。",
                data={"rule_intent": state.intent.to_dict()} if state.debug_enabled else {"intent": state.intent.intent, "confidence": state.intent.confidence},
            )
            return
        if node_name == "planner":
            plan = state.plan
            plan_type = getattr(plan, "plan_type", None) or getattr(plan, "route_type", None) or "fallback"
            payload = plan.to_dict() if state.debug_enabled and hasattr(plan, "to_dict") else {"plan_type": plan_type}
            yield builder.event("planner", content=f"Graph Runtime 生成了 {plan_type} 计划。", data=payload)
            return
        if node_name == "validate":
            if state.requires_confirmation:
                yield builder.event("planner", content="计划需要用户确认后才能执行。", data={"requires_confirmation": True})
            elif state.validation_result:
                yield builder.event(
                    "planner",
                    content="工具计划校验通过。" if state.validation_result.valid else "工具计划校验未通过。",
                    data=state.validation_result.to_dict() if state.debug_enabled else {"valid": state.validation_result.valid, "warnings": list(state.validation_result.warnings or [])},
                )
            return
        if node_name == "execute":
            for progress in self._result_progress_events(state.final_response or self._coerce_result_for_progress(state.execution_results)):
                yield builder.event(progress["event"], content=progress.get("content", ""), data=progress.get("data") or {})
            if state.execution_results is not None:
                payload = self._coerce_result_for_progress(state.execution_results)
                yield builder.event(
                    "tool_result",
                    content="工具执行完成。" if payload.get("success") else "工具执行失败。",
                    data={"success": bool(payload.get("success")), "route": payload.get("route"), "tool_name": payload.get("tool_name")},
                )
            return
        if node_name == "observe":
            status = state.observations.get("status")
            if status == "recoverable_error":
                yield builder.event("status", content="发现可恢复问题，准备尝试修复。", data=dict(state.observations or {}))
            elif status == "need_user_input":
                yield builder.event("status", content="需要补充信息后才能继续。", data=dict(state.observations or {}))
                if state.errors:
                    error_text = "；".join(item.get("message", "") for item in state.errors if item.get("message")) or "需要补充信息后才能继续。"
                    yield builder.event("error", content=error_text, data={"node": node_name, "reason": state.observations.get("reason")})
            return
        if node_name == "repair" and state.repair_attempts:
            yield builder.event("tool_progress", content="已完成一次自动修复尝试。", data=dict(state.observations or {}))

    def _tool_start_event(self, builder: StreamEventBuilder, state: GraphState) -> AgentStreamEvent | None:
        if state.requires_confirmation or state.observations.get("status") == "need_user_input":
            return None
        plan = state.validated_plan or state.plan
        route = getattr(plan, "plan_type", None) or getattr(plan, "route_type", None) or ""
        if route not in {"skill", "tool", "rag", "hybrid", "raman_pipeline"}:
            return None
        first = None
        steps = getattr(plan, "steps", None) or []
        if steps:
            first = steps[0]
        tool_name = getattr(first, "tool_name", None) or getattr(plan, "tool_name", None)
        action_name = getattr(first, "action_name", None) or getattr(plan, "action_name", None)
        return builder.event(
            "tool_start",
            content=f"准备执行 {tool_name or route}{'.' + action_name if action_name else ''}。",
            data={"route": route, "tool_name": tool_name, "action_name": action_name},
        )

    def _coerce_result_for_progress(self, result: Any) -> dict[str, Any]:
        if result is None:
            return {}
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return dict(result)
        return {}

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

    def _error_stream(self, builder: StreamEventBuilder, response: dict[str, Any], started: float) -> Iterable[AgentStreamEvent]:
        error_text = str(response.get("error_message") or response.get("reply") or "Graph Runtime 执行失败。")
        yield builder.event("error", content=error_text, data={"runtime": "graph"})
        yield builder.event(
            "final",
            content=error_text,
            data={
                "response": compact_response_for_stream(response),
                "route": response.get("route") or "graph_error",
                "success": False,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        yield builder.event("done", content="流式响应已结束。", data={"elapsed_ms": int((time.perf_counter() - started) * 1000)})

    def _error_response(self, state: GraphState, message: str, *, error_type: str = "GraphRuntimeError") -> dict[str, Any]:
        state.mark_elapsed()
        normalized = state.normalized_message
        response = AgentResponse(
            success=False,
            reply=message,
            intent=getattr(state.intent, "intent", "unknown"),
            route="graph_error",
            error_message=message,
            conversation_id=state.conversation_id or (normalized.conversation_id if normalized else None),
            session_id=state.session_id or (normalized.session_id if normalized else None),
            debug=state.public_debug(),
            data={"errors": list(state.errors or []), "error_type": error_type},
            source="graph_runtime",
        ).to_dict()
        if not state.debug_enabled:
            response["debug"] = {}
        return response
