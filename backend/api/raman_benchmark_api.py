from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.raman_evaluation.benchmark_runner import RamanBenchmarkRunner
from backend.raman_training.train_registry import RamanTrainRegistry
from backend.raman_training.training_pipeline import RamanTrainingPipeline


router = APIRouter(prefix="/api/raman", tags=["raman-benchmark"])
benchmark_runner = RamanBenchmarkRunner()
train_registry = RamanTrainRegistry()
training_pipeline = RamanTrainingPipeline(registry=train_registry)


class DatasetPayload(BaseModel):
    name: str
    description: str | None = None
    sample_count: int | None = None
    target_type: str | None = None
    target_name: str | None = None
    files: list[str] = []
    labels: dict[str, Any] = {}


class BenchmarkPayload(BaseModel):
    dataset_id: str
    pipelines: list[dict[str, Any]] = []


class TrainingPayload(BaseModel):
    model_type: str = "SVR"
    target: str = "methanol"
    features: list[list[float]] = []
    targets: list[float] = []
    params: dict[str, Any] = {}
    train_dataset_id: str | None = None
    preprocess_pipeline_id: str | None = None
    version: str | None = None


@router.get("/datasets")
def list_datasets(current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    datasets = benchmark_runner.list_datasets()
    return {"success": True, "datasets": datasets, "total": len(datasets)}


@router.post("/datasets")
def create_dataset(payload: DatasetPayload, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    dataset = benchmark_runner.create_dataset(payload.model_dump())
    return {"success": True, "dataset": dataset}


@router.post("/benchmark/run")
def run_benchmark(payload: BenchmarkPayload, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    try:
        result = benchmark_runner.run_benchmark(payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "RAMAN_DATASET_NOT_FOUND", "error_message": str(exc)}) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"error_code": "RAMAN_BENCHMARK_FAILED", "error_message": str(exc)}) from exc
    return {"success": True, "benchmark": result, "benchmark_id": result.get("benchmark_id")}


@router.get("/benchmark/{benchmark_id}")
def get_benchmark(benchmark_id: str, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    result = benchmark_runner.get_benchmark(benchmark_id)
    if result is None:
        raise HTTPException(status_code=404, detail={"error_code": "RAMAN_BENCHMARK_NOT_FOUND", "error_message": "Benchmark 不存在。"})
    return {"success": True, "benchmark": result}


@router.post("/training/run")
def run_training(payload: TrainingPayload, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    return training_pipeline.train(payload.model_dump())


@router.get("/models")
def list_trained_models(current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    models = train_registry.list_models()
    return {"success": True, "models": models, "total": len(models)}


@router.get("/models/{model_id}")
def get_trained_model(model_id: str, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    model = train_registry.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail={"error_code": "RAMAN_MODEL_NOT_FOUND", "error_message": "模型不存在。"})
    return {"success": True, "model": model}


@router.post("/models/{model_id}/activate")
def activate_trained_model(model_id: str, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    try:
        model = train_registry.activate(model_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "RAMAN_MODEL_NOT_FOUND", "error_message": str(exc)}) from exc
    return {"success": True, "model": model}

