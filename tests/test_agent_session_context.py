from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import agent_router
from backend.agent.session_store import clear_sessions, get_last_analysis, get_session
from backend.main import app


def _mock_valid_agent_run_tool(tool_name, params=None):
    standardized_result = {
        "sample_file": "甲醇-1.3967-1.csv",
        "sample_path": "outputs/uploads/甲醇-1.3967-1.csv",
        "unit": "%",
        "final_prediction": 1.2345,
        "svr_prediction": 1.1234,
        "rf_prediction": 1.3456,
        "model_disagreement": {"warning": False, "message": "一致性较好"},
        "confidence": {"status": "可信度正常", "knn_distance": 0.1, "threshold": 0.2},
        "figure_paths": {
            "raw": "outputs/figures/raw.png",
            "preprocessed": "outputs/figures/pre.png",
            "cdae": "outputs/figures/cdae.png",
            "final": "outputs/figures/final.png",
        },
        "warnings": [],
        "pipeline": ["统一波数轴", "SVR/RF融合预测"],
    }
    raw_result = {
        "sample_file": standardized_result["sample_file"],
        "sample_path": standardized_result["sample_path"],
        "fusion_prediction": standardized_result["final_prediction"],
        "svr_prediction": standardized_result["svr_prediction"],
        "rf_prediction": standardized_result["rf_prediction"],
        "model_disagreement": standardized_result["model_disagreement"],
        "confidence": standardized_result["confidence"],
        "figures": standardized_result["figure_paths"],
        "pipeline": standardized_result["pipeline"],
        "unit": standardized_result["unit"],
    }

    if tool_name == "predict_methanol":
        return {
            "success": True,
            "result": standardized_result,
            "raw_result": raw_result,
            "final_prediction": standardized_result["final_prediction"],
            "svr_prediction": standardized_result["svr_prediction"],
            "rf_prediction": standardized_result["rf_prediction"],
            "warnings": [],
        }
    if tool_name == "professional_spectral_analysis":
        return {
            "success": True,
            "peak_analysis": {"success": True, "peaks": []},
            "quality_analysis": {"success": True, "quality_level": "good"},
            "baseline_analysis": {"success": True, "baseline_level": "normal"},
            "similarity_analysis": {"success": True, "similar_records": []},
            "professional_summary": {"overall_level": "good", "key_findings": [], "risks": [], "suggestions": []},
        }
    if tool_name == "explain_result":
        return {"success": True, "explanation": "刚才这次结果整体比较可靠，模型一致性也不错。", "error_message": None}
    if tool_name == "generate_report":
        return {
            "success": True,
            "report_path": "outputs/reports/mock_report.md",
            "report_file": "mock_report.md",
        }
    if tool_name == "find_similar_history":
        return {
            "success": True,
            "similar_records": [{"task_id": "1", "sample_file": "history.csv", "final_prediction": 1.2}],
            "message": "找到 1 条预测浓度接近的历史记录。",
        }
    raise AssertionError(f"未知工具: {tool_name}")


def test_chat_without_session_id_returns_new_session_id():
    clear_sessions()
    client = TestClient(app)

    response = client.post("/api/agent/chat", json={"message": "你好"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["session_id"]

    session = get_session(payload["session_id"])
    assert session is not None
    assert len(session["messages"]) == 2
    assert session["messages"][0]["role"] == "user"
    assert session["messages"][1]["role"] == "assistant"


def test_analyze_file_writes_last_analysis_to_session():
    clear_sessions()
    client = TestClient(app)
    session_id = client.post("/api/agent/chat", json={"message": "你好"}).json()["session_id"]

    original_run_tool = agent_router.service.run_tool
    agent_router.service.run_tool = _mock_valid_agent_run_tool
    try:
        response = client.post(
            "/api/agent/analyze-file",
            data={"session_id": session_id},
            files={"file": ("甲醇-1.3967-1.csv", b"x,y\n1,2\n", "text/csv")},
        )
    finally:
        agent_router.service.run_tool = original_run_tool

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["session_id"] == session_id

    last_analysis = get_last_analysis(session_id)
    assert last_analysis is not None
    assert last_analysis["result"]["final_prediction"] == 1.2345
    assert last_analysis["report"]["report_file"] == "mock_report.md"


def test_chat_can_answer_from_last_analysis_context():
    clear_sessions()
    client = TestClient(app)
    session_id = client.post("/api/agent/chat", json={"message": "你好"}).json()["session_id"]

    original_run_tool = agent_router.service.run_tool
    agent_router.service.run_tool = _mock_valid_agent_run_tool
    try:
        client.post(
            "/api/agent/analyze-file",
            data={"session_id": session_id},
            files={"file": ("甲醇-1.3967-1.csv", b"x,y\n1,2\n", "text/csv")},
        )
    finally:
        agent_router.service.run_tool = original_run_tool

    response = client.post("/api/agent/chat", json={"message": "这个结果靠谱吗", "session_id": session_id})
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["session_id"] == session_id
    assert "比较可靠" in payload["reply"]


def test_chat_without_last_analysis_prompts_upload_first():
    clear_sessions()
    client = TestClient(app)

    response = client.post("/api/agent/chat", json={"message": "这个结果靠谱吗", "session_id": "session-no-analysis"})
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["session_id"] == "session-no-analysis"
    assert "我还没有看到你本轮会话中的分析结果" in payload["reply"]


if __name__ == "__main__":
    raise SystemExit("Run with pytest")
