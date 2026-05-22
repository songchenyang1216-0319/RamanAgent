from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import agent_router
from backend.agent.intent_router import detect_intent
from backend.agent.tool_registry import get_tool_spec
from backend.agent.tools.report_tool import explain_result_tool
from backend.main import app


def test_stage3_tools_registered():
    assert get_tool_spec("detect_peaks") is not None
    assert get_tool_spec("analyze_spectrum_quality") is not None
    assert get_tool_spec("professional_spectral_analysis") is not None


def test_stage3_intents():
    assert detect_intent("这个光谱质量怎么样")["intent"] == "analyze_spectrum_quality"
    assert detect_intent("帮我找主要峰")["intent"] == "detect_peaks"
    assert detect_intent("这个结果可信吗")["intent"] == "professional_spectral_analysis"
    assert detect_intent("当前用的模型是什么")["intent"] == "get_current_model"
    assert detect_intent("实验记录")["intent"] == "get_experiment_history"


def test_agent_chat_stage3_without_file():
    client = TestClient(app)
    response = client.post("/api/agent/chat", json={"message": "这个光谱质量怎么样"})
    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert "需要先上传 CSV 文件" in payload["reply"]


def test_analyze_file_includes_professional_analysis():
    client = TestClient(app)
    standardized_result = {
        "sample_file": "mock.csv",
        "sample_path": "outputs/uploads/mock.csv",
        "unit": "%",
        "final_prediction": 1.2,
        "svr_prediction": 1.1,
        "rf_prediction": 1.3,
        "model_disagreement": {"warning": False, "message": "一致性较好"},
        "confidence": {"status": "可信度正常"},
        "figure_paths": {"raw": "outputs/figures/raw.png"},
        "warnings": [],
        "pipeline": [],
    }
    raw_result = {
        "sample_file": "mock.csv",
        "sample_path": "outputs/uploads/mock.csv",
        "fusion_prediction": 1.2,
        "svr_prediction": 1.1,
        "rf_prediction": 1.3,
        "unit": "%",
        "confidence": {"status": "可信度正常"},
        "model_disagreement": {"warning": False, "message": "一致性较好"},
        "figures": {"raw": "outputs/figures/raw.png"},
        "pipeline": [],
    }
    professional = {
        "success": True,
        "peak_analysis": {"success": True, "peaks": []},
        "quality_analysis": {"success": True, "quality_level": "good"},
        "baseline_analysis": {"success": True, "baseline_level": "normal"},
        "similarity_analysis": {"success": True, "similar_records": []},
        "professional_summary": {"overall_level": "good", "key_findings": [], "risks": [], "suggestions": []},
    }

    def fake_run_tool(tool_name, params=None):
        if tool_name == "predict_methanol":
            return {"success": True, "result": dict(standardized_result), "raw_result": raw_result, "warnings": []}
        if tool_name == "professional_spectral_analysis":
            return professional
        if tool_name == "explain_result":
            return {"success": True, "explanation": "基于真实结果的解释", "error_message": None}
        if tool_name == "generate_report":
            return {"success": True, "report_path": "outputs/reports/mock.md", "report_file": "mock.md"}
        raise AssertionError(tool_name)

    original_run_tool = agent_router.service.run_tool
    agent_router.service.run_tool = fake_run_tool
    try:
        response = client.post(
            "/api/agent/analyze-file",
            files={"file": ("mock.csv", b"1,2\n2,3\n", "text/csv")},
        )
    finally:
        agent_router.service.run_tool = original_run_tool

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert "professional_analysis" in payload
    assert "professional_analysis" not in payload["result"]
    assert "peak_analysis" in payload["professional_analysis"]
    assert "quality_analysis" in payload["professional_analysis"]
    assert "baseline_analysis" in payload["professional_analysis"]
    assert "professional_summary" in payload["professional_analysis"]


def test_llm_fallback_does_not_explain_empty_as_zero():
    response = explain_result_tool({})
    assert response["success"] is False
    assert "预测结果无效" in response["explanation"]
    assert "0.0000" not in response["explanation"]


if __name__ == "__main__":
    raise SystemExit("Run with pytest")
