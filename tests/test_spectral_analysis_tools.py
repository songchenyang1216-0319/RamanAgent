from pathlib import Path
import sys

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.tools.spectral_tools import spectral_summary_tool
from backend.agent.tools.spectral_tools.baseline_quality_tool import analyze_baseline_quality
from backend.agent.tools.spectral_tools.peak_detection_tool import detect_peaks
from backend.agent.tools.spectral_tools.quality_tool import analyze_spectrum_quality
from backend.agent.tools.spectral_tools.similarity_tool import find_similar_history
from backend.agent.tools.spectral_tools.spectral_summary_tool import analyze_spectrum_professionally
from backend.agent.tools.spectral_tools.spectrum_loader import load_raman_csv


def _write_mock_spectrum(path: Path) -> None:
    x = np.linspace(400, 1800, 300)
    y = (
        0.05 * np.sin(x / 80)
        + np.exp(-((x - 700) ** 2) / (2 * 18**2))
        + 0.8 * np.exp(-((x - 1000) ** 2) / (2 * 24**2))
        + 0.5 * np.exp(-((x - 1450) ** 2) / (2 * 30**2))
    )
    lines = [f"{xi},{yi}" for xi, yi in zip(x, y)]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_spectrum_loader_no_header(tmp_path):
    csv_path = tmp_path / "mock.csv"
    _write_mock_spectrum(csv_path)
    result = load_raman_csv(csv_path)
    assert result["success"] is True
    assert result["points"] == 300
    assert result["x_min"] >= 400


def test_peak_detection_quality_and_baseline(tmp_path):
    csv_path = tmp_path / "mock.csv"
    _write_mock_spectrum(csv_path)

    peaks = detect_peaks(csv_path, top_n=5)
    assert peaks["success"] is True
    assert peaks["peak_count"] >= 2

    quality = analyze_spectrum_quality(csv_path)
    assert quality["success"] is True
    assert quality["quality_level"] in {"good", "acceptable", "poor"}

    baseline = analyze_baseline_quality(csv_path)
    assert baseline["success"] is True
    assert "baseline_level" in baseline


def test_professional_summary_survives_subtool_failure(tmp_path, monkeypatch):
    csv_path = tmp_path / "mock.csv"
    _write_mock_spectrum(csv_path)

    def broken_peak_tool(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(spectral_summary_tool, "detect_peaks", broken_peak_tool)
    result = analyze_spectrum_professionally(csv_path, {"final_prediction": 1.0})
    assert result["success"] is True
    assert "professional_summary" in result
    assert result["warnings"]


def test_invalid_csv_returns_structured_error(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("a,b\nx,y\n", encoding="utf-8")
    result = load_raman_csv(csv_path)
    assert result["success"] is False
    assert "error_message" in result


def test_similarity_tool_filters_mock_and_large_difference(monkeypatch):
    monkeypatch.setattr(
        "backend.agent.tools.spectral_tools.similarity_tool.list_analysis_history",
        lambda limit=100, offset=0: {
            "items": [
                {"task_id": "1", "sample_file": "mock.csv", "fusion_prediction": 2.7, "created_at": "2026-05-14"},
                {"task_id": "2", "sample_file": "real_a.csv", "fusion_prediction": 2.9, "created_at": "2026-05-14"},
                {"task_id": "3", "sample_file": "real_b.csv", "fusion_prediction": 48.5, "created_at": "2026-05-14"},
            ]
        },
    )
    result = find_similar_history({"final_prediction": 2.7}, limit=5)
    assert result["success"] is True
    assert len(result["similar_records"]) == 1
    assert result["similar_records"][0]["sample_file"] == "real_a.csv"
    assert result["message"] == "找到 1 条预测浓度接近的历史记录。"


if __name__ == "__main__":
    raise SystemExit("Run with pytest")
