from pathlib import Path
import sys

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.tools.spectral_tools.spectral_summary_tool import analyze_spectrum_professionally


def _write_mock_spectrum(path: Path) -> None:
    x = np.linspace(400, 1800, 360)
    y = (
        0.04 * np.sin(x / 90)
        + np.exp(-((x - 1030) ** 2) / (2 * 18**2))
        + 0.65 * np.exp(-((x - 1450) ** 2) / (2 * 28**2))
        + 0.35 * np.exp(-((x - 1128) ** 2) / (2 * 20**2))
    )
    path.write_text("\n".join(f"{xi},{yi}" for xi, yi in zip(x, y)), encoding="utf-8")


def test_professional_analysis_has_human_readable_sections(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_mock_spectrum(csv_path)

    result = analyze_spectrum_professionally(csv_path, {"final_prediction": 30.0})
    summary = result["professional_summary"]

    assert result["success"] is True
    assert summary["conclusion"]
    assert isinstance(summary["key_evidence"], list)
    assert isinstance(summary["risks"], list)
    assert isinstance(summary["suggestions"], list)
    assert "ood_risk" in result
    assert summary["ood_risk"]["level"] in {"low", "medium", "high"}


def test_ood_risk_field_exists_for_out_of_range_prediction(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_mock_spectrum(csv_path)

    result = analyze_spectrum_professionally(csv_path, {"final_prediction": 180.0})
    ood = result["ood_risk"]

    assert ood["level"] in {"medium", "high"}
    assert ood["score"] > 0
    assert any("训练" in warning for warning in ood["warnings"])


def test_peak_knowledge_is_included_without_overclaim(tmp_path):
    csv_path = tmp_path / "sample.csv"
    _write_mock_spectrum(csv_path)

    result = analyze_spectrum_professionally(csv_path, {"final_prediction": 30.0})
    peaks = result["peak_analysis"]["peaks"]

    assert peaks
    assert any(peak.get("knowledge_annotations") for peak in peaks)
    joined = " ".join(str(peak.get("knowledge_annotations")) for peak in peaks)
    assert "可能" in joined or "通常" in joined
    assert "确定检出" not in joined
