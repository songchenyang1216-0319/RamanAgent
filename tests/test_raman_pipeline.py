from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.raman_pipeline.algorithm_registry import get_algorithm_registry
from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
from backend.raman_pipeline.pipeline_schema import PipelineRequest, PipelineStep


def _write_mock_spectrum(path: Path) -> None:
    x = np.linspace(400, 1800, 180)
    y = 0.05 * np.sin(x / 45.0) + np.exp(-0.5 * ((x - 1030) / 35) ** 2) + 0.2
    path.write_text(
        "wavenumber,intensity\n" + "\n".join(f"{float(a)},{float(b)}" for a, b in zip(x, y)),
        encoding="utf-8",
    )


def test_algorithm_registry_returns_algorithms() -> None:
    payload = get_algorithm_registry().to_dict()
    assert payload["total"] > 0
    assert any(item["algorithm_id"] == "savitzky_golay" for item in payload["algorithms"])


def test_algorithm_ids_are_unique() -> None:
    algorithms = get_algorithm_registry().to_dict()["algorithms"]
    ids = [item["algorithm_id"] for item in algorithms]
    assert len(ids) == len(set(ids))


def test_unavailable_algorithms_have_reason() -> None:
    algorithms = get_algorithm_registry().to_dict()["algorithms"]
    unavailable = [item for item in algorithms if not item["available"]]
    assert unavailable
    assert all(item["unavailable_reason"] for item in unavailable)


def test_basic_preprocessing_template_runs_on_mock_spectrum(tmp_path: Path) -> None:
    file_path = tmp_path / "mock_spectrum.csv"
    _write_mock_spectrum(file_path)
    result = RamanPipelineRunner().run(
        PipelineRequest(
            file_path=str(file_path),
            template_id="basic_preprocessing",
            save_history=False,
        )
    )
    assert result.success is True
    assert result.final_spectrum["points"] > 10
    assert all(step.status == "success" for step in result.steps)


def test_sg_even_window_length_returns_parameter_error(tmp_path: Path) -> None:
    file_path = tmp_path / "mock_spectrum.csv"
    _write_mock_spectrum(file_path)
    result = RamanPipelineRunner().run(
        PipelineRequest(
            file_path=str(file_path),
            steps=[
                PipelineStep(algorithm_id="load_csv_spectrum"),
                PipelineStep(algorithm_id="savitzky_golay", params={"window_length": 10, "polyorder": 2}),
            ],
            save_history=False,
        )
    )
    assert result.success is False
    assert "window_length 必须是奇数" in result.error_message

