"""Small report builder for pipeline responses."""

from __future__ import annotations

from typing import Any

import numpy as np


def build_final_spectrum(data: dict[str, Any], preview_points: int = 12) -> dict[str, Any]:
    if data.get("wavenumber") is None or data.get("intensity") is None:
        return {}
    x = np.asarray(data["wavenumber"], dtype=float)
    y = np.asarray(data["intensity"], dtype=float)
    head = min(preview_points, len(x))
    return {
        "points": int(len(x)),
        "wavenumber_min": float(np.nanmin(x)) if len(x) else None,
        "wavenumber_max": float(np.nanmax(x)) if len(x) else None,
        "intensity_min": float(np.nanmin(y)) if len(y) else None,
        "intensity_max": float(np.nanmax(y)) if len(y) else None,
        "preview": [{"wavenumber": float(a), "intensity": float(b)} for a, b in zip(x[:head], y[:head])],
    }


def merge_metrics(step_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for metrics in step_metrics:
        for key, value in metrics.items():
            merged[key] = value
    return merged
