from __future__ import annotations

from backend.agent.intent_router import detect_intent
from backend.services.llm_service import LLMService


def test_detect_intent_for_llm_provider_question() -> None:
    intent = detect_intent("我想看一下他用的是哪一个平台的大模型，是硅基流动的还是其他的？")
    assert intent["intent"] == "system_info_query"
    assert intent["category"] == "tool"
    assert intent["params"]["query_type"] == "provider"


def test_llm_service_provider_info_has_required_fields() -> None:
    info = LLMService().get_provider_info()
    assert "configured" in info
    assert "provider_name" in info
    assert "base_url" in info
    assert "model" in info
    assert isinstance(info["configured"], bool)
