from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import agent_router
from backend.agent.tools.predict_tool import normalize_prediction_result, predict_methanol_tool
from backend.main import app


def test_predict_tool_empty_result(monkeypatch):
    monkeypatch.setattr(
        "backend.agent.tools.predict_tool.predict_methanol",
        lambda file_path, include_intermediate=False: {},
    )
    result = predict_methanol_tool("dummy.csv")
    assert result["success"] is False
    assert result["error_message"] == "预测服务没有返回有效结果"


def test_normalize_prediction_result_field_mapping():
    raw_result = {
        "sample_file": "甲醇-1.3967-1.csv",
        "sample_path": "outputs/uploads/sample.csv",
        "fusion_prediction": 1.23,
        "svr_prediction": 1.11,
        "rf_prediction": 1.35,
        "model_disagreement": {"warning": False},
        "confidence": {"status": "可信度正常"},
        "figures": {"raw": "outputs/figures/a.png"},
        "pipeline": ["统一波数轴", "SVR/RF融合预测"],
        "unit": "%",
    }
    normalized = normalize_prediction_result(raw_result)
    assert normalized is not None
    assert normalized["final_prediction"] == 1.23
    assert normalized["svr_prediction"] == 1.11
    assert normalized["rf_prediction"] == 1.35
    assert "figure_paths" in normalized


def test_analyze_file_invalid_prediction_result():
    client = TestClient(app)

    def fake_run_tool(tool_name, params=None):
        if tool_name == "predict_methanol":
            return {"success": False, "error_message": "预测服务没有返回有效结果", "raw_keys": []}
        raise AssertionError(f"不应调用工具: {tool_name}")

    original_run_tool = agent_router.service.run_tool
    agent_router.service.run_tool = fake_run_tool
    try:
        response = client.post(
            "/api/agent/analyze-file",
            files={"file": ("甲醇-1.3967-1.csv", b"x,y\n1,2\n", "text/csv")},
        )
    finally:
        agent_router.service.run_tool = original_run_tool

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is False
    assert payload["result"] is None
    assert payload["llm_explanation"] == "预测结果无效，暂不生成大模型解释。"


def test_analyze_file_valid_prediction_result():
    client = TestClient(app)

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

    def fake_run_tool(tool_name, params=None):
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
            return {"success": True, "explanation": "这是基于真实预测值的解释。", "error_message": None}
        if tool_name == "generate_report":
            return {
                "success": True,
                "report_path": "outputs/reports/mock_report.md",
                "report_file": "mock_report.md",
            }
        raise AssertionError(f"未知工具: {tool_name}")

    original_run_tool = agent_router.service.run_tool
    agent_router.service.run_tool = fake_run_tool
    try:
        response = client.post(
            "/api/agent/analyze-file",
            files={"file": ("甲醇-1.3967-1.csv", b"x,y\n1,2\n", "text/csv")},
        )
    finally:
        agent_router.service.run_tool = original_run_tool

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert payload["result"]["final_prediction"] == 1.2345
    assert payload["result"]["svr_prediction"] == 1.1234
    assert payload["result"]["rf_prediction"] == 1.3456
    assert payload["web_urls"]["figures"]["raw"].endswith("/raw.png")


if __name__ == "__main__":
    raise SystemExit("Run with pytest")
