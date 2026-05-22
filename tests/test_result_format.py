from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.methanol_service import build_public_prediction_result, calculate_model_disagreement


def test_result_format():
    raw_result = {
        "sample_file": "甲醇-0.1717-5.csv",
        "sample_path": "data/demo/甲醇-0.1717-5.csv",
        "svr_prediction": 0.0207,
        "rf_prediction": 0.2454,
        "fusion_prediction": 0.1106,
        "unit": "percent_or_ppm",
        "confidence": {
            "knn_distance": 0.083,
            "threshold": 0.129,
            "status": "可信度正常",
        },
        "figures": {
            "raw": "outputs/figures/a_raw.png",
            "preprocessed": "outputs/figures/a_preprocessed.png",
            "cdae": "outputs/figures/a_cdae.png",
            "final": "outputs/figures/a_final.png",
        },
        "pipeline": [
            "统一波数轴",
            "SG平滑",
            "ALS去基线",
            "CDAE去噪",
            "CAE+预测基线",
            "SVR/RF融合预测",
        ],
        "intermediate": {
            "aligned_y": [1, 2, 3],
            "corrected_y": [0.1, 0.2, 0.3],
        },
    }

    public_result = build_public_prediction_result(raw_result, include_intermediate=False)
    assert "intermediate" not in public_result
    assert "model_disagreement" in public_result
    assert "result_summary" in public_result

    debug_result = build_public_prediction_result(raw_result, include_intermediate=True)
    assert "intermediate" in debug_result

    high_value_small_relative = calculate_model_disagreement(48.6484, 48.3709, 48.5374)
    assert high_value_small_relative["warning"] is False

    low_value_warning_case = calculate_model_disagreement(0.02, 0.245, 0.11)
    assert low_value_warning_case["warning"] is True

    high_value_relative_warning = calculate_model_disagreement(80, 90, 85)
    assert high_value_relative_warning["warning"] is True


if __name__ == "__main__":
    test_result_format()
    print("result format test passed")
