from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import backend.skills.spectral_preprocessing_skill as preprocessing_module
from backend.skills.spectral_preprocessing_skill import SpectralPreprocessingSkill


class _FakePredictor:
    def __init__(self) -> None:
        self.common_axis = np.linspace(400, 1800, 32)
        self.config = {"sg_window": 5, "sg_order": 2}
        self.cdae_display_model = object()
        self.cdae_reg_model = object()

    def _run_cdae_single(self, _model, values):
        return np.asarray(values) * 0.95

    def _run_caeplus_single(self, values):
        return np.asarray(values) * 0.1


def test_full_preprocess_pipeline_outputs_three_plots() -> None:
    original_get_predictor = preprocessing_module.get_predictor
    try:
        preprocessing_module.get_predictor = lambda: _FakePredictor()
        output_root = PROJECT_ROOT / "outputs"
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as tmp_dir:
            csv_path = Path(tmp_dir) / "sample.csv"
            axis = np.linspace(400, 1800, 32)
            values = np.sin(np.linspace(0, 3.14, 32)) + 1.5
            csv_lines = ["wavenumber,intensity"] + [f"{float(x)},{float(y)}" for x, y in zip(axis, values)]
            csv_path.write_text("\n".join(csv_lines), encoding="utf-8")

            skill = SpectralPreprocessingSkill()
            result = skill.run(action_name="full_preprocess_pipeline", file_path=str(csv_path))

            assert result.success is True
            plots = (result.data or {}).get("plots") or []
            assert len(plots) >= 3
            kinds = {item.get("kind") for item in plots if isinstance(item, dict)}
            assert {"raw", "processed", "overlay"}.issubset(kinds)
    finally:
        preprocessing_module.get_predictor = original_get_predictor


if __name__ == "__main__":
    test_full_preprocess_pipeline_outputs_three_plots()
    print("preprocess visuals test passed")
