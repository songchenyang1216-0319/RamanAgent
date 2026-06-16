"""Built-in templates and JSON history for Raman pipelines."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from raman_core.methanol.config import OUTPUT_DIR


def _step(algorithm_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"algorithm_id": algorithm_id, "params": params or {}}


BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "basic_preprocessing": {
        "template_id": "basic_preprocessing",
        "display_name": "基础预处理",
        "description": "读取 CSV、清理异常值、排序、去重、SG 平滑、ALS 基线扣除和 Min-Max 归一化。",
        "steps": [
            _step("load_csv_spectrum"),
            _step("validate_spectrum_csv"),
            _step("remove_nan_inf"),
            _step("sort_by_wavenumber"),
            _step("remove_duplicate_wavenumber"),
            _step("savitzky_golay", {"window_length": 11, "polyorder": 2}),
            _step("als_baseline", {"lam": 100000.0, "p": 0.01, "iterations": 10}),
            _step("baseline_subtraction", {"clip_negative": True}),
            _step("min_max_normalize"),
        ],
    },
    "quality_check": {
        "template_id": "quality_check",
        "display_name": "质量检查",
        "description": "读取并清洗光谱后输出 SNR、漂移、饱和、尖峰、荧光背景和总质量分。",
        "steps": [
            _step("load_csv_spectrum"),
            _step("validate_spectrum_csv"),
            _step("remove_nan_inf"),
            _step("sort_by_wavenumber"),
            _step("estimate_snr"),
            _step("baseline_drift_score"),
            _step("saturation_check"),
            _step("cosmic_ray_check"),
            _step("fluorescence_background_score"),
            _step("spectrum_quality_score"),
        ],
    },
    "methanol_prediction": {
        "template_id": "methanol_prediction",
        "display_name": "甲醇预测前处理",
        "description": "用于旧甲醇预测链路前的标准化预处理和质量汇总；真正预测仍由 MethanolPredictor.predict 兼容入口执行。",
        "steps": [
            _step("load_csv_spectrum"),
            _step("validate_spectrum_csv"),
            _step("remove_nan_inf"),
            _step("sort_by_wavenumber"),
            _step("remove_duplicate_wavenumber"),
            _step("resample_linear", {"points": 1024}),
            _step("savitzky_golay", {"window_length": 11, "polyorder": 2}),
            _step("als_baseline", {"lam": 100000.0, "p": 0.01, "iterations": 10}),
            _step("baseline_subtraction", {"clip_negative": True}),
            _step("min_max_normalize"),
            _step("collect_basic_features"),
            _step("spectrum_quality_score"),
        ],
    },
    "peak_analysis": {
        "template_id": "peak_analysis",
        "display_name": "峰分析",
        "description": "平滑后执行显著峰检测，并输出峰高、峰宽、峰面积和峰表。",
        "steps": [
            _step("load_csv_spectrum"),
            _step("remove_nan_inf"),
            _step("sort_by_wavenumber"),
            _step("savitzky_golay", {"window_length": 11, "polyorder": 2}),
            _step("find_peaks_prominence", {"distance": 5, "prominence": 0.05}),
            _step("peak_height"),
            _step("peak_width"),
            _step("peak_area"),
            _step("peak_table_export"),
        ],
    },
    "deep_learning_placeholder": {
        "template_id": "deep_learning_placeholder",
        "display_name": "深度学习占位",
        "description": "展示深度学习算法占位和模型缺失/未接入时的错误处理。",
        "steps": [
            _step("load_csv_spectrum"),
            _step("validate_spectrum_csv"),
            _step("cdae_denoise"),
            _step("cae_baseline_prediction"),
        ],
    },
    "ml_compare": {
        "template_id": "ml_compare",
        "display_name": "机器学习对比",
        "description": "预处理并提取基础特征；执行 ML 回归器前需要为对应步骤提供 train_features 和 train_targets。",
        "steps": [
            _step("load_csv_spectrum"),
            _step("remove_nan_inf"),
            _step("sort_by_wavenumber"),
            _step("resample_linear", {"points": 64}),
            _step("min_max_normalize"),
            _step("collect_basic_features"),
            _step("svr_regressor"),
            _step("random_forest_regressor"),
            _step("pls_regressor"),
            _step("linear_regressor"),
            _step("ridge_regressor"),
            _step("lasso_regressor"),
        ],
    },
}


class PipelineStore:
    def __init__(self, history_path: Path | None = None) -> None:
        self.history_path = history_path or (OUTPUT_DIR / "raman_pipeline" / "history.json")

    def list_templates(self) -> dict[str, Any]:
        return {"total": len(BUILTIN_TEMPLATES), "templates": list(BUILTIN_TEMPLATES.values())}

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        template = BUILTIN_TEMPLATES.get(str(template_id))
        return json.loads(json.dumps(template, ensure_ascii=False)) if template else None

    def _read_history(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            return list(data if isinstance(data, list) else [])
        except Exception:
            return []

    def append_history(self, result: dict[str, Any]) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        history = self._read_history()
        item = dict(result)
        item["created_at"] = datetime.now().isoformat(timespec="seconds")
        history.insert(0, item)
        self.history_path.write_text(json.dumps(history[:100], ensure_ascii=False, indent=2), encoding="utf-8")

    def list_history(self, limit: int = 30) -> dict[str, Any]:
        history = self._read_history()[: max(1, int(limit))]
        return {"total": len(history), "history": history}

