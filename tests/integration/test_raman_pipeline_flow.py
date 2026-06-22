from __future__ import annotations

from pathlib import Path

from backend.raman_pipeline import PipelineRequest, PipelineStep, RamanPipelineRunner


DEMO_DIR = Path(__file__).resolve().parents[2] / "data" / "demo"


def test_raman_pipeline_valid_demo_full_preprocessing() -> None:
    runner = RamanPipelineRunner()
    result = runner.run(PipelineRequest(file_path=str(DEMO_DIR / "raman_demo_valid.csv"), template_id="basic_preprocessing", save_history=False))
    assert result.success is True
    assert result.pipeline_run_id == result.run_id
    assert result.total_steps >= 8
    assert result.completed_steps == result.total_steps
    assert result.failed_step is None
    assert result.step_results
    assert result.final_spectrum.get("points", 0) > 20


def test_raman_pipeline_invalid_demo_fails_clearly() -> None:
    runner = RamanPipelineRunner()
    result = runner.run(PipelineRequest(file_path=str(DEMO_DIR / "raman_demo_invalid.csv"), template_id="basic_preprocessing", save_history=False))
    assert result.success is False
    assert result.failed_step
    assert result.error_message
    assert result.completed_steps < result.total_steps


def test_raman_preprocess_only_does_not_predict() -> None:
    runner = RamanPipelineRunner()
    result = runner.run(
        PipelineRequest(
            file_path=str(DEMO_DIR / "raman_demo_valid.csv"),
            steps=[
                PipelineStep(algorithm_id="load_csv_spectrum"),
                PipelineStep(algorithm_id="validate_spectrum_csv"),
                PipelineStep(algorithm_id="savitzky_golay", params={"window_length": 9, "polyorder": 2}),
                PipelineStep(algorithm_id="als_baseline"),
                PipelineStep(algorithm_id="baseline_subtraction"),
                PipelineStep(algorithm_id="min_max_normalize"),
            ],
            save_history=False,
        )
    )
    assert result.success is True
    algorithm_ids = [step.algorithm_id for step in result.steps]
    assert "methanol_predict" not in algorithm_ids
    assert "cdae_denoise" not in algorithm_ids


def test_noisy_demo_quality_metrics_are_available() -> None:
    runner = RamanPipelineRunner()
    result = runner.run(PipelineRequest(file_path=str(DEMO_DIR / "raman_demo_with_noise.csv"), template_id="quality_check", save_history=False))
    assert result.success is True
    assert "quality" in result.metrics or result.metrics
