from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services import report_service


def _write_mock_csv(path: Path) -> None:
    x_values = [400, 500, 600, 700, 800, 900]
    y_values = [0.1, 0.2, 0.5, 0.3, 0.2, 0.1]
    path.write_text("\n".join(f"{x},{y}" for x, y in zip(x_values, y_values)), encoding="utf-8")


def _mock_result(sample_path: Path) -> dict:
    return {
        "sample_file": "甲醇 样品:01?.csv",
        "sample_path": str(sample_path),
        "model_version": "methanol_v1",
        "svr_prediction": 0.12,
        "rf_prediction": 0.13,
        "fusion_prediction": 0.125,
        "unit": "%",
        "confidence": {"knn_distance": 0.08, "threshold": 0.12, "status": "可信度正常"},
        "model_disagreement": {
            "absolute_difference": 0.01,
            "relative_difference": 0.08,
            "warning": False,
            "message": "SVR 与 RF 预测差异在可接受范围内。",
        },
        "figures": {
            "raw": "outputs/figures/sample_raw.png",
            "preprocessed": "outputs/figures/sample_preprocessed.png",
            "cdae": "outputs/figures/sample_cdae.png",
            "final": "outputs/figures/sample_final.png",
        },
        "pipeline": ["统一波数轴", "SG平滑", "ALS去基线", "CDAE去噪", "CAE+预测基线", "SVR/RF融合预测"],
        "professional_analysis": {
            "quality_analysis": {
                "success": True,
                "overall_quality": "good",
                "quality_level": "good",
                "issues": ["轻微基线漂移"],
                "metrics": {
                    "estimated_snr": 22.5,
                    "baseline_drift_score": 0.12,
                    "peak_sharpness_score": 0.81,
                },
                "saturation_or_clipping_check": {"risk": False},
                "abnormal_intensity_check": {"risk": False},
            },
            "baseline_analysis": {
                "success": True,
                "baseline_level": "normal",
                "warnings": ["基线整体稳定"],
            },
            "peak_analysis": {
                "success": True,
                "peaks": [
                    {
                        "rank": 1,
                        "wavenumber": 1030.0,
                        "intensity": 1.0,
                        "prominence": 0.8,
                        "knowledge_annotations": [
                            {
                                "label": "C-O stretching region",
                                "possible_mode": "甲醇中 C-O 伸缩振动通常可能出现在这一带。",
                                "caution": "不能单凭该峰确认成分。",
                                "confidence": "possible",
                            }
                        ],
                    }
                ],
            },
            "similarity_analysis": {
                "success": True,
                "similar_records": [
                    {
                        "sample_file": "history_a.csv",
                        "final_prediction": 0.121,
                        "difference": 0.004,
                        "created_at": "2026-05-15 10:00:00",
                    }
                ],
            },
            "ood_risk": {
                "level": "low",
                "score": 0.12,
                "warnings": [],
            },
            "professional_summary": {
                "conclusion": "当前样品可用于甲醇浓度参考判断。",
                "risks": ["轻微基线漂移"],
                "suggestions": ["建议做一次重复采集"],
                "ood_risk": {"level": "low", "score": 0.12, "warnings": []},
            },
        },
        "model_info": {
            "model_version": "methanol_v1",
            "algorithm": ["SVR", "RF", "CDAE", "CAE+"],
            "training_data": {"concentration_range": [0, 100]},
        },
        "experiment_metadata": {"sample_name": "样品 A", "instrument": "Raman-X"},
    }


def test_report_service_generates_markdown_and_html(tmp_path, monkeypatch):
    monkeypatch.setattr(report_service, "REPORT_DIR", tmp_path / "reports")
    sample_csv = tmp_path / "sample.csv"
    _write_mock_csv(sample_csv)

    report = report_service.generate_methanol_markdown_report(_mock_result(sample_csv), "测试解释")

    markdown_path = report_service.REPORT_DIR / report["report_markdown_file"]
    html_path = report_service.REPORT_DIR / report["report_html_file"]

    assert markdown_path.exists()
    assert html_path.exists()
    assert report["formats"] == ["markdown", "html"]


def test_report_contains_prediction_and_quality_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(report_service, "REPORT_DIR", tmp_path / "reports")
    sample_csv = tmp_path / "sample.csv"
    _write_mock_csv(sample_csv)

    report = report_service.generate_methanol_markdown_report(_mock_result(sample_csv), "测试解释")
    content = (report_service.REPORT_DIR / report["report_markdown_file"]).read_text(encoding="utf-8")

    assert "## 2. 预测结果" in content
    assert "预测浓度" in content
    assert "## 4. 光谱质量评价" in content
    assert "总体质量" in content


def test_report_does_not_include_api_key_or_absolute_path(tmp_path, monkeypatch):
    monkeypatch.setattr(report_service, "REPORT_DIR", tmp_path / "reports")
    sample_csv = tmp_path / "sample.csv"
    _write_mock_csv(sample_csv)
    result = _mock_result(sample_csv)
    result["sample_path"] = str(PROJECT_ROOT / "data" / "demo" / "sample.csv")

    report = report_service.generate_methanol_markdown_report(
        result,
        "API_KEY=secret123\nTraceback (most recent call last): boom\nD:\\secret\\path",
    )
    content = (report_service.REPORT_DIR / report["report_markdown_file"]).read_text(encoding="utf-8")

    assert "secret123" not in content
    assert "Traceback (most recent call last)" not in content
    assert str(PROJECT_ROOT) not in content
    assert "data/demo/sample.csv" not in content


def test_report_file_name_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(report_service, "REPORT_DIR", tmp_path / "reports")
    sample_csv = tmp_path / "sample.csv"
    _write_mock_csv(sample_csv)

    report = report_service.generate_methanol_markdown_report(_mock_result(sample_csv), "测试解释")

    assert ":" not in report["report_markdown_file"]
    assert "?" not in report["report_markdown_file"]
    assert report["report_markdown_file"].endswith(".md")
