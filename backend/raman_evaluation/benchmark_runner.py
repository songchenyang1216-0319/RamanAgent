from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.raman_evaluation.metrics import summarize_pipeline_result
from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
from backend.raman_pipeline.pipeline_schema import PipelineRequest, PipelineStep
from backend.services.workspace_manager import now_iso, read_json, write_json
from raman_core.methanol.config import PROJECT_ROOT


DATASETS_PATH = PROJECT_ROOT / "storage" / "raman_datasets.json"
BENCHMARKS_PATH = PROJECT_ROOT / "storage" / "raman_benchmarks.json"


class RamanBenchmarkRunner:
    def __init__(self, runner: RamanPipelineRunner | None = None) -> None:
        self.runner = runner or RamanPipelineRunner()

    def list_datasets(self) -> list[dict[str, Any]]:
        value = read_json(DATASETS_PATH, [])
        return value if isinstance(value, list) else []

    def create_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        files = [str(item) for item in (payload.get("files") or []) if str(item).strip()]
        item = {
            "dataset_id": str(payload.get("dataset_id") or uuid4().hex),
            "name": str(payload.get("name") or "未命名 Raman 数据集"),
            "description": str(payload.get("description") or ""),
            "sample_count": int(payload.get("sample_count") or len(files)),
            "target_type": str(payload.get("target_type") or "regression"),
            "target_name": str(payload.get("target_name") or "methanol"),
            "files": files,
            "labels": dict(payload.get("labels") or {}),
            "created_at": now_iso(),
        }
        items = self.list_datasets()
        items.append(item)
        write_json(DATASETS_PATH, items)
        return item

    def run_benchmark(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(payload.get("dataset_id") or "")
        datasets = self.list_datasets()
        dataset = next((item for item in datasets if str(item.get("dataset_id")) == dataset_id), None)
        if dataset is None:
            raise KeyError("Raman 测试集不存在。")
        files = list(dataset.get("files") or [])
        if not files:
            raise ValueError("Raman 测试集没有文件，无法运行 benchmark。")
        pipelines = list(payload.get("pipelines") or [{"template_id": "basic_preprocessing"}])
        benchmark_id = uuid4().hex
        rows: list[dict[str, Any]] = []
        for file_path in files:
            resolved = Path(file_path)
            if not resolved.is_absolute():
                resolved = PROJECT_ROOT / file_path
            for index, pipeline in enumerate(pipelines, start=1):
                request = PipelineRequest(
                    file_path=str(resolved),
                    template_id=pipeline.get("template_id"),
                    steps=[PipelineStep(**step) for step in pipeline.get("steps", [])],
                    save_history=False,
                )
                result = self.runner.run(request).model_dump()
                rows.append(
                    {
                        "file": str(file_path),
                        "pipeline_index": index,
                        "pipeline_name": pipeline.get("template_id") or f"custom_{index}",
                        "success": bool(result.get("success")),
                        "error_message": result.get("error_message") or "",
                        **summarize_pipeline_result(result),
                    }
                )
        summary = {
            "benchmark_id": benchmark_id,
            "dataset_id": dataset_id,
            "created_at": now_iso(),
            "rows": rows,
            "total_runs": len(rows),
            "failure_rate": sum(1 for row in rows if not row.get("success")) / max(1, len(rows)),
        }
        history = read_json(BENCHMARKS_PATH, [])
        history = history if isinstance(history, list) else []
        history.append(summary)
        write_json(BENCHMARKS_PATH, history)
        return summary

    def get_benchmark(self, benchmark_id: str) -> dict[str, Any] | None:
        history = read_json(BENCHMARKS_PATH, [])
        for item in history if isinstance(history, list) else []:
            if str(item.get("benchmark_id") or "") == str(benchmark_id):
                return dict(item)
        return None

