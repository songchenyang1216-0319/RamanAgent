"""基于 LLM 的意图识别 fallback。"""

from __future__ import annotations

import json

from backend.agent.prompts.intent_classifier_prompt import (
    ALLOWED_LLM_INTENTS,
    build_intent_classifier_system_prompt,
    build_intent_classifier_user_prompt,
)
from backend.services.llm_service import LLMService


class LLMIntentClassifier:
    """使用 LLM 对模糊表达进行结构化意图分类。"""

    def __init__(self) -> None:
        self.llm_service = LLMService()

    def _normalize_response(self, payload: dict) -> dict:
        """校验并标准化 LLM 返回的 JSON。"""
        intent = str(payload.get("intent", "unknown")).strip()
        if intent not in ALLOWED_LLM_INTENTS:
            intent = "unknown"

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(max(confidence, 0.0), 1.0)

        reason = str(payload.get("reason", "") or "").strip() or "LLM 未提供明确原因。"
        slots = payload.get("slots", {})
        if not isinstance(slots, dict):
            slots = {}

        return {
            "intent": intent,
            "confidence": confidence,
            "reason": reason,
            "slots": slots,
        }

    def classify(self, message: str) -> dict:
        """调用 LLM 输出结构化意图 JSON。"""
        system_prompt = build_intent_classifier_system_prompt()
        user_prompt = build_intent_classifier_user_prompt(message)
        content, raw = self.llm_service._chat_complete(system_prompt, user_prompt)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM 意图分类未返回合法 JSON: {exc}") from exc
        normalized = self._normalize_response(parsed)
        normalized["raw_response"] = raw
        return normalized
