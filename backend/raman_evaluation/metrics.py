from __future__ import annotations

from typing import Any

import numpy as np


def regression_metrics(y_true: list[float], y_pred: list[float]) -> dict[str, Any]:
    if not y_true or not y_pred or len(y_true) != len(y_pred):
        return {"prediction_rmse": None, "prediction_mae": None, "prediction_r2": None}
    true = np.asarray(y_true, dtype=float)
    pred = np.asarray(y_pred, dtype=float)
    rmse = float(np.sqrt(np.mean((true - pred) ** 2)))
    mae = float(np.mean(np.abs(true - pred)))
    denom = float(np.sum((true - np.mean(true)) ** 2))
    r2 = None if denom == 0 else float(1 - np.sum((true - pred) ** 2) / denom)
    return {"prediction_rmse": rmse, "prediction_mae": mae, "prediction_r2": r2}


def summarize_pipeline_result(result: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(result.get("metrics") or {})
    return {
        "SNR": metrics.get("snr") or metrics.get("estimate_snr"),
        "baseline_drift_score": metrics.get("baseline_drift_score"),
        "peak_count": metrics.get("peak_count") or ((result.get("final_spectrum") or {}).get("peak_count")),
        "peak_shift": metrics.get("peak_shift"),
        "runtime_ms": result.get("elapsed_ms"),
        "failure_rate": 0 if result.get("success") else 1,
    }

