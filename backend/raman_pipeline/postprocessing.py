"""Postprocessing helpers for Raman pipeline outputs."""

from __future__ import annotations

from typing import Any

import numpy as np

from .algorithm_schema import AlgorithmRunOutput, RamanPipelineError


def collect_basic_features(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    y = data.get("intensity")
    if y is None:
        raise RamanPipelineError("特征提取需要先读取光谱。")
    arr = np.asarray(y, dtype=float)
    features = {
        "mean_intensity": float(np.nanmean(arr)),
        "std_intensity": float(np.nanstd(arr)),
        "max_intensity": float(np.nanmax(arr)),
        "min_intensity": float(np.nanmin(arr)),
        "area_index": float(np.trapezoid(arr)),
    }
    out = dict(data)
    out["features"] = {**dict(out.get("features") or {}), **features}
    return AlgorithmRunOutput(data=out, metrics=features)

