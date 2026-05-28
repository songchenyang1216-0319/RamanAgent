from __future__ import annotations

from typing import Any

from backend.agent.types import AgentPlan, IntentResult, NormalizedMessage
from backend.schemas.agent_response import AgentResponse


class ResponseBuilder:
    def build(
        self,
        result: dict[str, Any] | AgentResponse,
        normalized: NormalizedMessage,
        intent: IntentResult,
        plan: AgentPlan,
    ) -> dict[str, Any]:
        raw_result = result if isinstance(result, dict) else None
        response = result if isinstance(result, AgentResponse) else self._coerce_result(result or {}, normalized, intent, plan)
        payload = response.to_dict()
        if payload.get("intent") in {None, "", "unknown"}:
            payload["intent"] = intent.intent
        if payload.get("route") in {None, "", "fallback"} and plan.route_type != "fallback":
            payload["route"] = plan.route_type
        payload["conversation_id"] = payload.get("conversation_id") or normalized.conversation_id
        payload["session_id"] = payload.get("session_id") or normalized.session_id
        payload["message"] = payload.get("message") or normalized.message
        payload["intent"] = payload.get("intent") or intent.intent
        payload["route"] = payload.get("route") or plan.route_type
        payload["category"] = payload.get("category") or intent.intent
        payload["skill_name"] = payload.get("skill_name") or response.skill_name
        payload["skill_mode"] = payload.get("skill_mode") or response.skill_mode
        payload["tool_name"] = payload.get("tool_name") or response.tool_name
        payload["provider_id"] = payload.get("provider_id") or response.model_provider or normalized.provider_id
        payload["model_id"] = payload.get("model_id") or response.model_name or normalized.model_id
        payload["used_skill"] = bool(payload.get("used_skill") or response.skill_used)
        payload["action_name"] = payload.get("action_name") or response.action_name
        payload["artifacts"] = payload.get("artifacts") or []
        if not payload.get("tool_info"):
            payload["tool_info"] = (
                (raw_result or {}).get("tool_info")
                or (payload.get("data") or {}).get("tool_info")
                or {}
            )
        if not payload.get("result"):
            result_payload = payload.get("data") or {}
            if isinstance(result_payload, dict) and "data" in result_payload and "skill_name" in result_payload:
                result_payload = result_payload.get("data") or {}
            payload["result"] = {
                "data": result_payload,
                "summary": payload.get("reply") or "",
            }
        for key in ("available_tools", "tool_result", "route_info", "professional_analysis", "result", "warnings", "web_urls", "report", "history"):
            if raw_result is not None and key in raw_result and key not in payload:
                payload[key] = raw_result.get(key)
        if not payload.get("messages"):
            content = payload["reply"] if payload["success"] else (payload["error_message"] or "处理失败。")
            payload["messages"] = [
                {
                    "role": "assistant",
                    "type": "text" if payload["success"] else "error",
                    "content": content,
                    "skill_name": payload.get("skill_name"),
                    "action_name": payload.get("action_name"),
                    "result_kind": "generic",
                    "skill_mode": payload.get("skill_mode"),
                }
            ]
        if payload["success"]:
            payload["error_message"] = None
            if not payload["reply"]:
                payload["reply"] = "处理完成。"
        else:
            payload["error_message"] = payload.get("error_message") or "处理失败，请查看后端日志。"
            if payload.get("reply") and payload["reply"] == payload["error_message"]:
                pass
            elif not payload.get("reply"):
                payload["reply"] = payload["error_message"]
        if payload.get("intent") == "system_info_query" and "当前使用的模型版本" in str(payload.get("reply") or ""):
            payload["intent"] = "get_current_model"
        if raw_result is not None and isinstance(raw_result.get("tool_used"), str):
            payload["tool_used"] = raw_result.get("tool_used")
        else:
            payload["tool_used"] = bool(payload.get("tool_name") or payload.get("tool_used"))
        payload["source"] = payload.get("source") or (raw_result or {}).get("source") or response.source or "orchestrator"
        return payload

    def _coerce_result(
        self,
        raw: dict[str, Any],
        normalized: NormalizedMessage,
        intent: IntentResult,
        plan: AgentPlan,
    ) -> AgentResponse:
        raw_debug = raw.get("debug")
        debug_payload = dict(raw_debug) if isinstance(raw_debug, dict) else ({"legacy_debug": raw_debug} if raw_debug is not None else {})
        success = bool(raw.get("success", False))
        reply = str(raw.get("reply") or raw.get("llm_explanation") or raw.get("summary") or raw.get("markdown") or "").strip()
        error_message = str(raw.get("error_message") or "").strip() or None
        if reply and not error_message:
            success = True
        if not reply and error_message:
            success = False
        return AgentResponse(
            success=success,
            reply=reply,
            intent=str(raw.get("intent") or intent.intent),
            route=plan.route_type,
            skill_used=bool(raw.get("skill_used") or plan.skill_name),
            skill_name=str(raw.get("skill_name") or plan.skill_name or "") or None,
            skill_mode=str(raw.get("skill_mode") or plan.skill_mode or "") or None,
            tool_used=bool(raw.get("tool_used") or raw.get("tool_name") or plan.tool_name),
            tool_name=str(raw.get("tool_name") or raw.get("tool_used") or plan.tool_name or "") or None,
            model_provider=str(raw.get("model_provider") or normalized.provider_id or "") or None,
            model_name=str(raw.get("model_name") or normalized.model_id or "") or None,
            artifacts=list(raw.get("artifacts") or []),
            debug=debug_payload,
            error_message=error_message if not success else None,
            conversation_id=normalized.conversation_id,
            session_id=normalized.session_id,
            messages=list(raw.get("messages") or []),
            category=raw.get("category") or intent.intent,
            action_name=str(raw.get("action_name") or plan.action_name or "") or None,
            data=dict(raw.get("data") or {}),
            model_info=dict(raw.get("model_info") or {}),
            llm_model_info=dict(raw.get("llm_model_info") or raw.get("model_info") or {}),
            source=str(raw.get("source") or "orchestrator"),
        )
