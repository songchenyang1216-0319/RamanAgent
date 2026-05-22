from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.agent_service import RamanAgentService
from backend.agent.intent_router import detect_intent
from backend.main import app


def test_intent_router():
    check_result = detect_intent("检查模型文件是否齐全")
    assert check_result["intent"] == "check_artifacts"
    assert check_result["category"] == "tool"

    list_result = detect_intent("查看历史记录")
    assert list_result["intent"] == "list_history"
    assert list_result["category"] == "tool"

    detail_result = detect_intent("查看第 3 条记录详情")
    assert detail_result["intent"] == "get_history_detail"
    assert detail_result["params"]["history_index"] == 3

    explicit_id_result = detect_intent("history_id=5")
    assert explicit_id_result["intent"] == "get_history_detail"
    assert explicit_id_result["params"]["history_id"] == "5"

    identity_result = detect_intent("你是谁")
    assert identity_result["intent"] == "capability_intro"
    assert identity_result["category"] == "general_chat"

    thanks_result = detect_intent("谢谢")
    assert thanks_result["intent"] == "gratitude"
    assert thanks_result["category"] == "general_chat"


def test_agent_service_tool_calling():
    service = RamanAgentService()

    check_response = service.chat("当前用的是哪个模型？")
    assert check_response["success"] is True
    assert check_response["category"] == "tool"
    assert "available_tools" not in check_response
    assert "tool_result" not in check_response
    assert check_response["data"]["model_version"] == "methanol_v1"

    debug_response = service.chat("当前用的是哪个模型？", debug=True)
    assert "available_tools" in debug_response
    assert "tool_result" in debug_response
    assert isinstance(debug_response["available_tools"], list)
    assert isinstance(debug_response["tool_result"], dict)

    check_response = service.chat("检查模型文件是否齐全")
    assert check_response["tool_used"] == "check_artifacts"
    assert check_response["category"] == "tool"
    assert "tool_result" not in check_response
    assert "available_tools" not in check_response
    assert check_response["data"]["missing_count"] >= 0

    history_response = service.chat("查看历史记录")
    assert history_response["tool_used"] == "list_history"
    assert history_response["category"] == "tool"
    assert "available_tools" not in history_response
    assert "tool_result" not in history_response
    assert "data" in history_response

    predict_response = service.chat("帮我分析这个csv")
    assert predict_response["success"] is True
    assert predict_response["category"] == "tool"
    assert "需要上传 CSV 文件" in predict_response["reply"]


def test_agent_router_endpoints():
    client = TestClient(app)

    tools_response = client.get("/api/agent/tools")
    assert tools_response.status_code == 200
    assert tools_response.json()["success"] is True

    chat_response = client.post(
        "/api/agent/chat",
        json={"message": "检查模型文件是否齐全"},
    )
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["tool_used"] == "check_artifacts"
    assert "tool_result" not in payload
    assert "available_tools" not in payload
    assert payload["data"]["missing_count"] >= 0


if __name__ == "__main__":
    test_intent_router()
    test_agent_service_tool_calling()
    test_agent_router_endpoints()
    print("agent tool calling test passed")
