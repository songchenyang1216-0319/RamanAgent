from pathlib import Path
import sys

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.tools.spectral_tools.baseline_quality_tool import analyze_baseline_quality
from backend.agent.tools.spectral_tools.quality_tool import analyze_spectrum_quality


def _write_spectrum(path: Path, noise: float = 0.01, drift: float = 0.0, seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    x = np.linspace(400, 1800, 420)
    peaks = (
        1.0 * np.exp(-((x - 1030) ** 2) / (2 * 18**2))
        + 0.7 * np.exp(-((x - 1450) ** 2) / (2 * 28**2))
        + 0.45 * np.exp(-((x - 1128) ** 2) / (2 * 22**2))
    )
    baseline = drift * (x - x.min()) / (x.max() - x.min())
    y = peaks + baseline + noise * rng.normal(size=x.size)
    path.write_text("\n".join(f"{xi},{yi}" for xi, yi in zip(x, y)), encoding="utf-8")


def test_normal_spectrum_outputs_quality_scores(tmp_path):
    csv_path = tmp_path / "normal.csv"
    _write_spectrum(csv_path, noise=0.005)

    result = analyze_spectrum_quality(csv_path)

    assert result["success"] is True
    assert result["overall_quality"] in {"good", "medium", "poor"}
    assert 0.0 <= result["score"] <= 1.0
    assert 0.0 <= result["signal_to_noise_score"] <= 1.0
    assert 0.0 <= result["peak_sharpness_score"] <= 1.0
    assert "saturation_or_clipping_check" in result
    assert "abnormal_intensity_check" in result


def test_noisy_spectrum_reports_noise_issue(tmp_path):
    csv_path = tmp_path / "noisy.csv"
    _write_spectrum(csv_path, noise=0.35)

    result = analyze_spectrum_quality(csv_path)

    text = " ".join(result.get("issues", []) + result.get("warnings", []))
    assert result["success"] is True
    assert "信噪比" in text or "异常" in text


def test_baseline_drift_reports_baseline_issue(tmp_path):
    csv_path = tmp_path / "drift.csv"
    _write_spectrum(csv_path, noise=0.01, drift=2.0)

    quality = analyze_spectrum_quality(csv_path)
    baseline = analyze_baseline_quality(csv_path, {"final_prediction": 20.0, "pipeline": ["ALS", "CDAE", "CAE+"]})

    quality_text = " ".join(quality.get("issues", []) + quality.get("warnings", []))
    baseline_text = " ".join(baseline.get("warnings", []))
    assert quality["baseline_drift_score"] > 0.0
    assert "基线" in quality_text or "基线" in baseline_text
    assert baseline["stage_comparison"]["raw"]["status"] in {"drift_risk", "usable"}
    assert baseline["regression_suitability"] in {"suitable", "caution", "not_recommended", "unknown"}
