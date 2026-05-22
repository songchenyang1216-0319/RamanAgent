from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.history_service import (
    delete_analysis_history,
    get_analysis_history,
    init_history_db,
    list_analysis_history,
    parse_expected_value_from_filename,
    save_analysis_history,
)


def test_history_service():
    assert parse_expected_value_from_filename("甲醇-65.3531-4.csv") == 65.3531
    assert parse_expected_value_from_filename("甲醇-48.7482-4_abc123.csv") == 48.7482
    assert parse_expected_value_from_filename("sample.csv") is None

    test_db_path = PROJECT_ROOT / "outputs" / "results" / "test_ramanagent.db"
    if test_db_path.exists():
        test_db_path.unlink()

    init_history_db(test_db_path)
    payload = {
        "saved_file": "data/raw/sample.csv",
        "result": {
            "sample_file": "甲醇-65.3531-4.csv",
            "sample_path": "data/raw/sample.csv",
            "svr_prediction": 65.1,
            "rf_prediction": 65.4,
            "fusion_prediction": 65.2,
            "unit": "%",
            "confidence": {
                "status": "可信度正常",
                "knn_distance": 0.08,
                "threshold": 0.12,
            },
            "model_disagreement": {
                "absolute_difference": 0.3,
                "relative_difference": 0.0046,
                "warning": False,
                "message": "SVR 与 RF 预测结果一致性较好。",
            },
            "pipeline": ["统一波数轴", "SG平滑"],
            "expected_value_from_filename": 65.3531,
            "prediction_error_from_filename": -0.1531,
        },
        "llm_explanation": "这是测试解释",
        "report": {
            "report_file": "sample_report.md",
            "report_path": "outputs/reports/sample_report.md",
        },
        "web_urls": {
            "figures": {
                "raw": "/static/figures/raw.png",
                "preprocessed": "/static/figures/pre.png",
                "cdae": "/static/figures/cdae.png",
                "final": "/static/figures/final.png",
            }
        },
        "professional_analysis": {
            "professional_summary": {"overall_level": "good"},
            "quality_analysis": {"quality_level": "good"},
            "baseline_analysis": {"baseline_level": "normal"},
            "peak_analysis": {"peak_count": 4},
        },
        "model_info": {"model_version": "methanol_v1"},
        "experiment_metadata": {
            "sample_name": "样品A",
            "sample_type": "液体",
            "operator": "tester",
            "instrument": "Raman-01",
            "laser_power": "10mW",
            "integration_time": "5s",
            "remarks": "note",
        },
    }

    saved = save_analysis_history(payload, test_db_path)
    assert "task_id" in saved

    listing = list_analysis_history(limit=10, offset=0, db_path=test_db_path)
    assert listing["total"] >= 1
    assert listing["items"][0]["task_id"] == saved["task_id"]
    filtered = list_analysis_history(limit=10, offset=0, db_path=test_db_path, model_version="methanol_v1")
    assert filtered["total"] >= 1

    detail = get_analysis_history(saved["task_id"], test_db_path)
    assert detail is not None
    assert detail["sample_file"] == "甲醇-65.3531-4.csv"
    assert detail["model_version"] == "methanol_v1"

    deleted = delete_analysis_history(saved["task_id"], test_db_path)
    assert deleted is True
    assert get_analysis_history(saved["task_id"], test_db_path) is None

    if test_db_path.exists():
        test_db_path.unlink()


if __name__ == "__main__":
    test_history_service()
    print("history service test passed")
