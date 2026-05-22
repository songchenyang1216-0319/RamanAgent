from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import agent_router
from backend.main import app
from backend.services.history_service import delete_analysis_history, get_analysis_history


def test_analyze_file_with_experiment_metadata():
    client = TestClient(app)
    standardized_result = {
        "sample_file": "甲醇-2.6995-1.csv",
        "sample_path": "outputs/uploads/sample.csv",
        "unit": "%",
        "final_prediction": 2.6995,
        "svr_prediction": 2.7330,
        "rf_prediction": 2.6493,
        "model_disagreement": {"warning": False, "message": "一致性较好"},
        "confidence": {"status": "可信度正常"},
        "figure_paths": {"raw": "outputs/figures/raw.png"},
        "warnings": [],
        "pipeline": [],
    }
    raw_result = {
        "sample_file": standardized_result["sample_file"],
        "sample_path": standardized_result["sample_path"],
        "fusion_prediction": standardized_result["final_prediction"],
        "svr_prediction": standardized_result["svr_prediction"],
        "rf_prediction": standardized_result["rf_prediction"],
        "unit": standardized_result["unit"],
        "confidence": standardized_result["confidence"],
        "model_disagreement": standardized_result["model_disagreement"],
        "figures": {"raw": "outputs/figures/raw.png"},
        "pipeline": [],
    }
    professional = {
        "success": True,
        "peak_analysis": {"success": True, "peak_count": 3},
        "quality_analysis": {"success": True, "quality_level": "good"},
        "baseline_analysis": {"success": True, "baseline_level": "normal"},
        "similarity_analysis": {"success": True, "similar_records": []},
        "professional_summary": {"overall_level": "good", "key_findings": [], "risks": [], "suggestions": []},
    }
    model_info = {
        "model_version": "methanol_v1",
        "model_name": "Methanol Raman SVR/RF Fusion Model",
        "target": "methanol_concentration",
        "unit": "%",
        "algorithm": ["SVR", "RandomForest"],
        "training_data": {"concentration_range": [0, 100]},
        "metrics": {"rmse": None},
        "artifact_check": {"success": True, "missing_files": [], "existing_files": []},
    }

    original_run_tool = agent_router.service.run_tool
    original_get_current = agent_router.model_registry_service.get_current_model
    original_check = agent_router.model_registry_service.check_model_artifacts

    def fake_run_tool(tool_name, params=None):
        if tool_name == "predict_methanol":
            return {"success": True, "result": dict(standardized_result), "raw_result": raw_result, "warnings": []}
        if tool_name == "professional_spectral_analysis":
            return professional
        if tool_name == "explain_result":
            return {"success": True, "explanation": "解释正常", "error_message": None}
        if tool_name == "generate_report":
            return {"success": True, "report_path": "outputs/reports/mock.md", "report_file": "mock.md"}
        raise AssertionError(tool_name)

    agent_router.service.run_tool = fake_run_tool
    agent_router.model_registry_service.get_current_model = lambda: {"success": True, "data": model_info, "warnings": [], "error_message": None}
    agent_router.model_registry_service.check_model_artifacts = lambda model_version=None: {
        "success": True,
        "data": {"existing_files": [], "missing_files": []},
        "warnings": [],
        "error_message": None,
    }
    try:
        response = client.post(
            "/api/agent/analyze-file",
            files={"file": ("sample.csv", b"1,2\n2,3\n", "text/csv")},
            data={
                "sample_name": "样品A",
                "sample_type": "液体",
                "operator": "tester",
                "instrument": "Raman-01",
                "laser_power": "10mW",
                "integration_time": "5s",
                "remarks": "stage4",
            },
        )
    finally:
        agent_router.service.run_tool = original_run_tool
        agent_router.model_registry_service.get_current_model = original_get_current
        agent_router.model_registry_service.check_model_artifacts = original_check

    payload = response.json()
    assert response.status_code == 200
    assert payload["success"] is True
    assert "professional_analysis" not in payload["result"]
    assert payload["model_info"]["model_version"] == "methanol_v1"
    assert payload["experiment_metadata"]["sample_name"] == "样品A"
    assert payload["history"]["task_id"]
    detail = get_analysis_history(payload["history"]["task_id"])
    assert detail is not None
    assert detail["model_version"] == "methanol_v1"
    assert detail["experiment_metadata"]["operator"] == "tester"
    delete_analysis_history(payload["history"]["task_id"])


if __name__ == "__main__":
    test_analyze_file_with_experiment_metadata()
    print("experiment metadata test passed")
