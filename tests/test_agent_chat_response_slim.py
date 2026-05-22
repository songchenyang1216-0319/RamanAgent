from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app


def _assert_natural_general_reply(payload: dict, keywords: tuple[str, ...]) -> None:
    assert payload["success"] is True
    assert payload["category"] == "general_chat"
    assert payload["reply"]
    assert any(keyword in payload["reply"] for keyword in keywords)


def test_chat_response_slim_default_and_debug():
    client = TestClient(app)

    slim_response = client.post("/api/agent/chat", json={"message": "当前用的是哪个模型？"})
    assert slim_response.status_code == 200
    payload = slim_response.json()
    assert payload["success"] is True
    assert payload["intent"] == "get_current_model"
    assert "available_tools" not in payload
    assert "tool_result" not in payload
    assert payload["data"]["model_version"] == "methanol_v1"
    assert payload["data"]["model_name"] == "Methanol Raman SVR/RF Fusion Model"

    debug_response = client.post("/api/agent/chat", json={"message": "当前用的是哪个模型？", "debug": True})
    assert debug_response.status_code == 200
    debug_payload = debug_response.json()
    assert debug_payload["success"] is True
    assert "available_tools" in debug_payload
    assert "tool_result" in debug_payload
    assert isinstance(debug_payload["available_tools"], list)
    assert isinstance(debug_payload["tool_result"], dict)


def test_chat_response_general_conversation_cases():
    client = TestClient(app)

    greeting = client.post("/api/agent/chat", json={"message": "你好"}).json()
    _assert_natural_general_reply(greeting, ("你好", "RamanAgent", "分析 CSV"))

    who_are_you = client.post("/api/agent/chat", json={"message": "你是谁"}).json()
    _assert_natural_general_reply(who_are_you, ("RamanAgent", "拉曼", "甲醇"))

    capability = client.post("/api/agent/chat", json={"message": "你能做什么"}).json()
    _assert_natural_general_reply(capability, ("拉曼", "甲醇", "CSV", "报告"))

    thanks = client.post("/api/agent/chat", json={"message": "谢谢"}).json()
    _assert_natural_general_reply(thanks, ("不客气", "随时", "继续"))

    limitation = client.post("/api/agent/chat", json={"message": "你是不是只能回答拉曼问题"}).json()
    _assert_natural_general_reply(limitation, ("不只", "也能", "基础聊天", "RamanAgent"))


def test_chat_response_llm_intent_fallback_cases(monkeypatch):
    client = TestClient(app)

    def fake_classify(self, message: str) -> dict:
        mapping = {
            "这个谱图质量怎么样？": {"intent": "spectral_quality", "confidence": 0.89, "reason": "想评估谱图质量", "slots": {}},
            "这个峰大概是什么物质的？": {"intent": "peak_analysis", "confidence": 0.88, "reason": "询问峰解释", "slots": {}},
        }
        return mapping[message]

    monkeypatch.setattr("backend.agent.llm_intent_classifier.LLMIntentClassifier.classify", fake_classify)

    quality = client.post("/api/agent/chat", json={"message": "这个谱图质量怎么样？"}).json()
    assert quality["success"] is True
    assert quality["category"] == "tool"
    assert quality["intent"] == "analyze_spectrum_quality"
    assert "上传 CSV" in quality["reply"]

    peak = client.post("/api/agent/chat", json={"message": "这个峰大概是什么物质的？"}).json()
    assert peak["success"] is True
    assert peak["category"] == "tool"
    assert peak["intent"] == "detect_peaks"
    assert "上传 CSV" in peak["reply"]

    casual = client.post("/api/agent/chat", json={"message": "随便聊聊"}).json()
    assert casual["success"] is True
    assert casual["category"] == "general_chat"
    assert casual["intent"] == "general_chat"


def test_tools_endpoint_still_returns_full_tool_specs():
    client = TestClient(app)
    response = client.get("/api/agent/tools")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert isinstance(payload["available_tools"], list)
    assert any("input_schema" in tool for tool in payload["available_tools"])


if __name__ == "__main__":
    raise SystemExit("Run with pytest")
