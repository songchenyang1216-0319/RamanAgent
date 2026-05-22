from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.report_service import generate_methanol_markdown_report


def test_report_format():
    result = {
        "sample_file": "sample.csv",
        "sample_path": "data/demo/sample.csv",
        "svr_prediction": 48.64841,
        "rf_prediction": 48.37091,
        "fusion_prediction": 48.53744,
        "unit": "%",
        "confidence": {"knn_distance": 0.083219, "threshold": 0.129887, "status": "可信度正常"},
        "model_disagreement": {
            "absolute_difference": 0.2775,
            "relative_difference": 0.0057,
            "warning": False,
            "message": "SVR 与 RF 预测结果一致性较好。",
        },
        "figures": {
            "raw": "outputs/figures/sample_raw.png",
            "preprocessed": "outputs/figures/sample_preprocessed.png",
            "cdae": "outputs/figures/sample_cdae.png",
            "final": "outputs/figures/sample_final.png",
        },
        "pipeline": ["统一波数轴", "SG平滑", "ALS去基线", "CDAE去噪"],
    }

    report = generate_methanol_markdown_report(result, "## 结果怎么理解\n这是测试解释。")
    report_path = PROJECT_ROOT / report["report_path"]
    content = report_path.read_text(encoding="utf-8")

    assert "48.5374" in content
    assert "48.6484" in content
    assert "简要结论" in content


if __name__ == "__main__":
    test_report_format()
    print("report format test passed")
