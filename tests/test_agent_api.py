from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.agent_service import RamanAgentService
from backend.main import app


def _mock_llm(monkeypatch):
    monkeypatch.setattr(
        "backend.services.llm_service.LLMService._chat_complete",
        lambda self, system_prompt, user_prompt: (f"模拟回复：当前使用 {self.provider}/{self.model}。", {"mock": True}),
    )


def test_agent_service_and_router(monkeypatch):
    _mock_llm(monkeypatch)
    service = RamanAgentService()
    tools = service.list_tools()
    tool_names = {tool["name"] for tool in tools}

    assert "predict_methanol" in tool_names
    assert "list_history" in tool_names
    assert "check_artifacts" in tool_names

    route_paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/api/agent/chat" in route_paths
    assert "/api/agent/tools" in route_paths

    response = service.chat("当前用的是哪个模型？")
    assert response["success"] is True
    assert "available_tools" not in response
    assert "tool_result" not in response
    assert "data" in response
    assert response["intent"] == "system_info_query"
    assert response["data"]["query_type"] == "current_model"
    assert response["data"]["current_model"]["model_version"] == "methanol_v1"
    assert "next_action" in response

    greeting = service.chat("你好")
    assert greeting["success"] is True
    assert greeting["category"] == "general_chat"
    assert greeting["intent"] == "smalltalk"
    assert greeting["reply"]

    capability = service.chat("你能做什么")
    assert capability["success"] is True
    assert capability["category"] == "general_chat"
    assert capability["intent"] == "capability_intro"
    assert capability["reply"]


def test_agent_service_llm_intent_fallback(monkeypatch):
    service = RamanAgentService()

    def fake_classify(self, message: str) -> dict:
        mapping = {
            "你现在背后跑的是什么模型？": {"intent": "model_info", "confidence": 0.91, "reason": "询问当前模型", "slots": {"system_info_target": "current_model"}},
            "刚才分析用的是哪套权重？": {"intent": "model_info", "confidence": 0.88, "reason": "询问当前权重", "slots": {"system_info_target": "current_model"}},
            "你现在用的是哪个平台的大模型？": {"intent": "system_info_query", "confidence": 0.93, "reason": "询问平台来源", "slots": {"system_info_target": "provider"}},
            "帮我看看最近一次实验结果": {"intent": "history_query", "confidence": 0.9, "reason": "查询历史", "slots": {}},
            "和之前的样品比一下": {"intent": "compare_history", "confidence": 0.86, "reason": "想和历史样品对比", "slots": {}},
            "这个峰大概是什么物质的？": {"intent": "peak_analysis", "confidence": 0.87, "reason": "询问峰解释", "slots": {}},
        }
        return mapping[message]

    monkeypatch.setattr("backend.agent.llm_intent_classifier.LLMIntentClassifier.classify", fake_classify)

    model_response = service.chat("你现在背后跑的是什么模型？")
    assert model_response["category"] == "tool"
    assert model_response["intent"] == "system_info_query"
    assert model_response["data"]["query_type"] == "current_model"
    assert model_response["data"]["current_model"]["model_version"] == "methanol_v1"

    weight_response = service.chat("刚才分析用的是哪套权重？")
    assert weight_response["category"] == "tool"
    assert weight_response["intent"] == "system_info_query"
    assert weight_response["data"]["query_type"] == "current_model"

    provider_response = service.chat("你现在用的是哪个平台的大模型？")
    assert provider_response["category"] == "tool"
    assert provider_response["intent"] == "system_info_query"
    assert provider_response["data"]["query_type"] == "provider"
    assert "provider_info" in provider_response["data"]

    history_response = service.chat("帮我看看最近一次实验结果")
    assert history_response["category"] == "tool"
    assert history_response["intent"] == "get_experiment_history"

    compare_response = service.chat("和之前的样品比一下")
    assert compare_response["category"] == "tool"
    assert compare_response["intent"] == "find_similar_history"
    assert "历史样品" in compare_response["reply"] or "上传 CSV" in compare_response["reply"]

    peak_response = service.chat("这个峰大概是什么物质的？")
    assert peak_response["category"] == "tool"
    assert peak_response["intent"] == "detect_peaks"
    assert "上传 CSV" in peak_response["reply"]


def test_agent_service_llm_intent_fallback_unavailable(monkeypatch):
    service = RamanAgentService()

    def broken_classify(self, message: str) -> dict:
        raise RuntimeError("no llm")

    monkeypatch.setattr("backend.agent.llm_intent_classifier.LLMIntentClassifier.classify", broken_classify)

    response = service.chat("你现在背后跑的是什么模型？")
    assert response["success"] is True
    assert response["category"] == "tool"
    assert response["intent"] in {"get_current_model", "system_info_query"}
    assert response["reply"]


if __name__ == "__main__":
    test_agent_service_and_router()
    print("agent api test passed")
