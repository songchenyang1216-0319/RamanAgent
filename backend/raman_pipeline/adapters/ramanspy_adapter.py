from __future__ import annotations

from typing import Any

from backend.raman_pipeline import preprocessing
from backend.raman_pipeline.algorithm_registry import AlgorithmRegistry
from backend.raman_pipeline.algorithm_schema import AlgorithmRunOutput, AlgorithmSpec


RAMANSPY_ALGORITHMS = {
    "ramanspy_savgol": ("RamanSPy Savitzky-Golay", "RamanSPy SG 平滑。"),
    "ramanspy_aspls": ("RamanSPy ASPLS", "RamanSPy ASPLS 基线校正。"),
    "ramanspy_minmax": ("RamanSPy Min-Max", "RamanSPy Min-Max 归一化。"),
    "ramanspy_cropper": ("RamanSPy Cropper", "RamanSPy 波数范围裁剪。"),
    "ramanspy_whitaker_hayes": ("RamanSPy Whitaker-Hayes", "RamanSPy Whitaker-Hayes 尖峰去除。"),
}


class RamanSPyAdapter:
    def __init__(self) -> None:
        try:
            import ramanspy as ramanspy_module  # type: ignore

            self.ramanspy = ramanspy_module
            self.available = True
            self.unavailable_reason = ""
        except Exception as exc:
            self.ramanspy = None
            self.available = False
            self.unavailable_reason = f"未安装或无法导入 ramanspy：{exc}"

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "algorithms": list(RAMANSPY_ALGORITHMS),
        }

    def algorithm_specs(self) -> list[AlgorithmSpec]:
        return [
            AlgorithmSpec(
                algorithm_id=algorithm_id,
                display_name=display_name,
                category="RamanSPy",
                description=description,
                input_type="spectrum",
                output_type="spectrum",
                default_params=self._default_params(algorithm_id),
                param_schema={"type": "object", "properties": {}},
                available=self.available,
                unavailable_reason="" if self.available else self.unavailable_reason,
                tags=["ramanspy", "optional"],
            )
            for algorithm_id, (display_name, description) in RAMANSPY_ALGORITHMS.items()
        ]

    def handlers(self) -> dict[str, Any]:
        return {
            "ramanspy_savgol": self._savgol,
            "ramanspy_aspls": self._aspls,
            "ramanspy_minmax": self._minmax,
            "ramanspy_cropper": self._cropper,
            "ramanspy_whitaker_hayes": self._whitaker_hayes,
        }

    def _default_params(self, algorithm_id: str) -> dict[str, Any]:
        return {
            "ramanspy_savgol": {"window_length": 11, "polyorder": 2},
            "ramanspy_aspls": {"lam": 100000.0, "p": 0.01, "iterations": 10},
            "ramanspy_minmax": {},
            "ramanspy_cropper": {"min_wavenumber": 400, "max_wavenumber": 1800},
            "ramanspy_whitaker_hayes": {"kernel_size": 5},
        }.get(algorithm_id, {})

    def _savgol(self, data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
        return preprocessing.savitzky_golay(data, params)

    def _aspls(self, data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
        return preprocessing.als_baseline(data, params)

    def _minmax(self, data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
        return preprocessing.min_max_normalize(data, params)

    def _cropper(self, data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
        return preprocessing.crop_wavenumber_range(data, params)

    def _whitaker_hayes(self, data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
        return preprocessing.median_filter(data, {"size": int(params.get("kernel_size") or params.get("size") or 5)})


def register_ramanspy_algorithms(registry: AlgorithmRegistry | None = None) -> dict[str, Any]:
    from backend.raman_pipeline.algorithm_registry import get_algorithm_registry

    target = registry or get_algorithm_registry()
    adapter = RamanSPyAdapter()
    if not adapter.available:
        return adapter.status()
    handlers = adapter.handlers()
    registered = []
    for spec in adapter.algorithm_specs():
        if target.get(spec.algorithm_id):
            continue
        target.register(spec, handlers[spec.algorithm_id])
        registered.append(spec.algorithm_id)
    status = adapter.status()
    status["registered"] = registered
    return status
