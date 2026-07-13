"""Pipeline validator and runner."""

from __future__ import annotations

import math
import time
import uuid
from typing import Any, Callable

import numpy as np

from .algorithm_registry import AlgorithmRegistry, get_algorithm_registry
from .algorithm_schema import AlgorithmRunOutput, RamanPipelineError
from .pipeline_schema import PipelineRequest, PipelineResult, PipelineStep, PipelineStepResult
from .pipeline_store import PipelineStore
from .report_builder import build_final_spectrum, merge_metrics
from .visualization import save_spectrum_plot


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return value
    return value


def _shape(data: dict[str, Any]) -> dict[str, Any]:
    x = data.get("wavenumber")
    y = data.get("intensity")
    peaks = data.get("peaks")
    return {
        "points": int(len(y)) if y is not None else 0,
        "wavenumber_points": int(len(x)) if x is not None else 0,
        "peak_count": int(len(peaks)) if isinstance(peaks, list) else 0,
        "has_baseline": data.get("baseline") is not None,
        "has_features": bool(data.get("features")),
    }


class RamanPipelineRunner:
    def __init__(self, registry: AlgorithmRegistry | None = None, store: PipelineStore | None = None) -> None:
        self.registry = registry or get_algorithm_registry()
        self.store = store or PipelineStore()

    def expand_request(self, request: PipelineRequest) -> PipelineRequest:
        if request.steps:
            return request
        if not request.template_id:
            raise RamanPipelineError("Pipeline 不能为空：请提供 steps 或 template_id。")
        template = self.store.get_template(request.template_id)
        if template is None:
            raise RamanPipelineError(f"未找到内置模板：{request.template_id}")
        return PipelineRequest(
            file_path=request.file_path,
            template_id=request.template_id,
            steps=[PipelineStep(**step) for step in template.get("steps", [])],
            params=dict(request.params or {}),
            sample_name=request.sample_name,
            save_history=request.save_history,
        )

    def validate(self, request: PipelineRequest) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        expanded: PipelineRequest | None = None
        try:
            expanded = self.expand_request(request)
        except RamanPipelineError as exc:
            errors.append(str(exc))
        if expanded is not None:
            for index, step in enumerate(expanded.steps, start=1):
                spec = self.registry.get(step.algorithm_id)
                if spec is None:
                    errors.append(f"第 {index} 步算法不存在：{step.algorithm_id}")
                    continue
                if not spec.available:
                    errors.append(f"第 {index} 步算法不可用：{spec.display_name}。{spec.unavailable_reason}")
                merged_params = {**spec.default_params, **dict(step.params or {})}
                if step.algorithm_id == "savitzky_golay":
                    window = int(merged_params.get("window_length", 11))
                    if window % 2 == 0:
                        errors.append("参数错误：SG window_length 必须是奇数。")
                if spec.requires_model_file and not spec.available:
                    warnings.append(spec.unavailable_reason)
        return {
            "success": not errors,
            "errors": errors,
            "warnings": warnings,
            "steps": [step.model_dump() for step in expanded.steps] if expanded else [],
        }

    def run(self, request: PipelineRequest, cancellation_checker: Callable[[], bool] | None = None) -> PipelineResult:
        expanded = self.expand_request(request)
        run_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        data: dict[str, Any] = {"file_path": expanded.file_path, "sample_name": expanded.sample_name}
        step_results: list[PipelineStepResult] = []
        warnings: list[str] = []
        artifacts: list[dict[str, Any]] = []

        for index, step in enumerate(expanded.steps, start=1):
            if cancellation_checker is not None and cancellation_checker():
                raise InterruptedError("任务已请求取消。")
            spec = self.registry.get(step.algorithm_id)
            step_id = step.step_id or f"{index:02d}_{step.algorithm_id}"
            input_shape = _shape(data)
            step_started = time.perf_counter()
            params = dict(spec.default_params if spec else {})
            params.update(dict(expanded.params.get(step.algorithm_id) or {}) if isinstance(expanded.params.get(step.algorithm_id), dict) else {})
            params.update(dict(step.params or {}))
            if expanded.file_path:
                params.setdefault("file_path", expanded.file_path)

            if spec is None:
                result = PipelineStepResult(
                    step_id=step_id,
                    algorithm_id=step.algorithm_id,
                    display_name=step.algorithm_id,
                    status="failed",
                    params=params,
                    input_shape=input_shape,
                    output_shape=input_shape,
                    error_message=f"算法不存在：{step.algorithm_id}",
                    elapsed_ms=int((time.perf_counter() - step_started) * 1000),
                )
                step_results.append(result)
                return self._finish(False, run_id, expanded, step_results, data, artifacts, warnings, result.error_message, started)

            if not spec.available:
                error = spec.unavailable_reason or f"算法不可用：{spec.display_name}"
                result = PipelineStepResult(
                    step_id=step_id,
                    algorithm_id=step.algorithm_id,
                    display_name=spec.display_name,
                    status="failed",
                    params=params,
                    input_shape=input_shape,
                    output_shape=input_shape,
                    error_message=error,
                    elapsed_ms=int((time.perf_counter() - step_started) * 1000),
                )
                step_results.append(result)
                return self._finish(False, run_id, expanded, step_results, data, artifacts, warnings, error, started)

            try:
                output: AlgorithmRunOutput = self.registry.handler(step.algorithm_id)(data, params)
                if cancellation_checker is not None and cancellation_checker():
                    raise InterruptedError("任务已请求取消。")
                data.update(output.data or {})
                step_artifacts = list(output.artifacts or [])
                plot = save_spectrum_plot(data, run_id, step_id, spec.display_name)
                if plot:
                    step_artifacts.append(plot)
                artifacts.extend(step_artifacts)
                if output.warning:
                    warnings.append(output.warning)
                result = PipelineStepResult(
                    step_id=step_id,
                    algorithm_id=step.algorithm_id,
                    display_name=spec.display_name,
                    status="success",
                    params=_jsonable(params),
                    input_shape=input_shape,
                    output_shape=_shape(data),
                    metrics=_jsonable(output.metrics),
                    artifacts=_jsonable(step_artifacts),
                    warning=output.warning,
                    elapsed_ms=int((time.perf_counter() - step_started) * 1000),
                )
                step_results.append(result)
            except InterruptedError:
                raise
            except RamanPipelineError as exc:
                error = str(exc)
                result = PipelineStepResult(
                    step_id=step_id,
                    algorithm_id=step.algorithm_id,
                    display_name=spec.display_name,
                    status="failed",
                    params=_jsonable(params),
                    input_shape=input_shape,
                    output_shape=_shape(data),
                    error_message=error,
                    elapsed_ms=int((time.perf_counter() - step_started) * 1000),
                )
                step_results.append(result)
                return self._finish(False, run_id, expanded, step_results, data, artifacts, warnings, error, started)
            except Exception as exc:
                error = f"算法执行失败：{exc}"
                result = PipelineStepResult(
                    step_id=step_id,
                    algorithm_id=step.algorithm_id,
                    display_name=spec.display_name,
                    status="failed",
                    params=_jsonable(params),
                    input_shape=input_shape,
                    output_shape=_shape(data),
                    error_message=error,
                    elapsed_ms=int((time.perf_counter() - step_started) * 1000),
                )
                step_results.append(result)
                return self._finish(False, run_id, expanded, step_results, data, artifacts, warnings, error, started)

        return self._finish(True, run_id, expanded, step_results, data, artifacts, warnings, "", started)

    def _finish(
        self,
        success: bool,
        run_id: str,
        request: PipelineRequest,
        steps: list[PipelineStepResult],
        data: dict[str, Any],
        artifacts: list[dict[str, Any]],
        warnings: list[str],
        error_message: str,
        started: float,
    ) -> PipelineResult:
        step_metrics = [step.metrics for step in steps if step.metrics]
        message = "Raman Pipeline 运行完成。" if success else "Raman Pipeline 运行失败。"
        failed_step = next((step.step_id for step in steps if step.status != "success"), None)
        final_spectrum = _jsonable(build_final_spectrum(data))
        pipeline_name = request.template_id or "custom_pipeline"
        unique_warnings = list(dict.fromkeys([item for item in warnings if item]))
        result = PipelineResult(
            success=success,
            run_id=run_id,
            pipeline_run_id=run_id,
            template_id=request.template_id,
            pipeline_name=pipeline_name,
            total_steps=len(request.steps),
            completed_steps=sum(1 for step in steps if step.status == "success"),
            failed_step=failed_step,
            message=message,
            steps=steps,
            step_results=steps,
            metrics=_jsonable(merge_metrics(step_metrics)),
            artifacts=_jsonable(artifacts),
            report={
                "title": f"Raman Pipeline Report - {pipeline_name}",
                "summary": message,
                "success": success,
                "error_message": error_message,
                "warnings": unique_warnings,
                "final_spectrum": final_spectrum,
            },
            final_spectrum=final_spectrum,
            warnings=unique_warnings,
            error_message=error_message,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        if request.save_history:
            self.store.append_history(result.model_dump())
        return result
