from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
from backend.raman_pipeline.pipeline_schema import PipelineRequest, PipelineStep
from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT


BENCHMARKS: dict[str, list[dict[str, Any]]] = {
    "raw": [
        {"algorithm_id": "load_csv_spectrum"},
        {"algorithm_id": "validate_spectrum_csv"},
    ],
    "sg_smoothing": [
        {"algorithm_id": "load_csv_spectrum"},
        {"algorithm_id": "validate_spectrum_csv"},
        {"algorithm_id": "savitzky_golay", "params": {"window_length": 11, "polyorder": 2}},
    ],
    "als_baseline": [
        {"algorithm_id": "load_csv_spectrum"},
        {"algorithm_id": "validate_spectrum_csv"},
        {"algorithm_id": "als_baseline", "params": {"lam": 100000.0, "p": 0.01, "iterations": 10}},
        {"algorithm_id": "baseline_subtraction", "params": {"clip_negative": True}},
    ],
    "sg_plus_als": [
        {"algorithm_id": "load_csv_spectrum"},
        {"algorithm_id": "validate_spectrum_csv"},
        {"algorithm_id": "savitzky_golay", "params": {"window_length": 11, "polyorder": 2}},
        {"algorithm_id": "als_baseline", "params": {"lam": 100000.0, "p": 0.01, "iterations": 10}},
        {"algorithm_id": "baseline_subtraction", "params": {"clip_negative": True}},
    ],
    "normalize": [
        {"algorithm_id": "load_csv_spectrum"},
        {"algorithm_id": "validate_spectrum_csv"},
        {"algorithm_id": "min_max_normalize"},
    ],
    "full_preprocessing_pipeline": [
        {"algorithm_id": "load_csv_spectrum"},
        {"algorithm_id": "validate_spectrum_csv"},
        {"algorithm_id": "remove_nan_inf"},
        {"algorithm_id": "sort_by_wavenumber"},
        {"algorithm_id": "remove_duplicate_wavenumber"},
        {"algorithm_id": "savitzky_golay", "params": {"window_length": 11, "polyorder": 2}},
        {"algorithm_id": "als_baseline", "params": {"lam": 100000.0, "p": 0.01, "iterations": 10}},
        {"algorithm_id": "baseline_subtraction", "params": {"clip_negative": True}},
        {"algorithm_id": "min_max_normalize"},
        {"algorithm_id": "find_peaks_prominence", "params": {"distance": 5, "prominence": 0.05}},
        {"algorithm_id": "spectrum_quality_score"},
    ],
}


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def run(input_csv: Path, output_dir: Path) -> dict[str, Any]:
    runner = RamanPipelineRunner()
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for name, steps in BENCHMARKS.items():
        request = PipelineRequest(
            file_path=str(input_csv),
            steps=[PipelineStep(**step) for step in steps],
            sample_name=input_csv.stem,
            save_history=False,
        )
        payload = runner.run(request).model_dump()
        results.append(
            {
                "pipeline": name,
                "success": bool(payload.get("success")),
                "elapsed_ms": int(payload.get("elapsed_ms") or 0),
                "step_count": len(payload.get("steps") or []),
                "artifact_count": len(payload.get("artifacts") or []),
                "peak_count": int((payload.get("final_spectrum") or {}).get("peak_count") or 0),
                "metrics": payload.get("metrics") or {},
                "warnings": payload.get("warnings") or [],
                "error_message": payload.get("error_message") or "",
                "artifacts": payload.get("artifacts") or [],
            }
        )
    benchmark = {
        "success": all(item["success"] for item in results),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_csv": _rel(input_csv),
        "results": results,
    }
    json_path = output_dir / "raman_benchmark.json"
    csv_path = output_dir / "raman_benchmark.csv"
    json_path.write_text(json.dumps(benchmark, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pipeline", "success", "elapsed_ms", "step_count", "artifact_count", "peak_count", "error_message"])
        writer.writeheader()
        for item in results:
            writer.writerow({key: item.get(key) for key in writer.fieldnames})
    benchmark["json_path"] = _rel(json_path)
    benchmark["csv_path"] = _rel(csv_path)
    return benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RamanAgent demo benchmark pipelines.")
    parser.add_argument("--input", default=str(PROJECT_ROOT / "data" / "demo" / "demo_raman_methanol.csv"))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR / "raman_benchmark"))
    args = parser.parse_args()
    result = run(Path(args.input), Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

