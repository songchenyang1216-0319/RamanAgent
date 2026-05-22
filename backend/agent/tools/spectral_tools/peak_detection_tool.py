"""Raman 主要峰识别工具。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.agent.tools.spectral_tools.spectrum_loader import load_raman_csv
from backend.knowledge.raman_peaks import annotate_peaks


def _moving_average(y: np.ndarray, window: int) -> np.ndarray:
    """使用简单移动平均做轻量平滑。"""
    window = max(3, min(window, len(y) // 2 * 2 - 1))
    if window < 3:
        return y
    kernel = np.ones(window) / window
    return np.convolve(y, kernel, mode="same")


def _fallback_find_peaks(y: np.ndarray, distance: int) -> tuple[np.ndarray, dict]:
    """scipy 不可用时使用局部极大值作为 fallback。"""
    candidates = []
    last_index = -distance
    for index in range(1, len(y) - 1):
        if index - last_index < distance:
            continue
        if y[index] > y[index - 1] and y[index] >= y[index + 1]:
            candidates.append(index)
            last_index = index
    peaks = np.asarray(candidates, dtype=int)
    prominences = y[peaks] - np.median(y) if len(peaks) else np.asarray([])
    return peaks, {"prominences": prominences}


def detect_peaks(csv_path: str | Path, top_n: int = 8, min_prominence: float | None = None, min_distance: int | None = None) -> dict:
    """识别 Raman 光谱中的主要峰。"""
    loaded = load_raman_csv(csv_path)
    if not loaded.get("success"):
        return loaded

    warnings = ["当前峰识别基于原始 CSV 光谱，未直接使用模型中间预处理数组。"]
    x = np.asarray(loaded["x"], dtype=float)
    y = np.asarray(loaded["y"], dtype=float)
    y_range = float(np.ptp(y))
    if y_range <= 1e-12:
        return {
            "success": True,
            "peaks": [],
            "peak_count": 0,
            "warnings": ["光谱强度变化过小，无法可靠识别主要峰。"],
        }

    smoothed = _moving_average(y, max(5, len(y) // 80))
    distance = int(min_distance or max(3, len(y) // 80))
    prominence = float(min_prominence if min_prominence is not None else y_range * 0.06)

    try:
        from scipy.signal import find_peaks

        peak_indices, props = find_peaks(smoothed, prominence=prominence, distance=distance)
    except Exception:
        peak_indices, props = _fallback_find_peaks(smoothed, distance=distance)

    prominences = np.asarray(props.get("prominences", np.zeros(len(peak_indices))), dtype=float)
    ranked = []
    for idx, prom in zip(peak_indices, prominences):
        if prom < prominence * 0.35:
            continue
        ranked.append(
            {
                "wavenumber": float(x[int(idx)]),
                "intensity": float(y[int(idx)]),
                "prominence": float(prom),
            }
        )
    ranked.sort(key=lambda item: (item["prominence"], item["intensity"]), reverse=True)

    peaks = []
    for rank, item in enumerate(ranked[: max(1, int(top_n))], start=1):
        peaks.append({**item, "rank": rank})
    peaks = annotate_peaks(peaks)

    if len(peaks) < min(3, int(top_n)):
        warnings.append("检测到的有效峰较少，可能是光谱噪声较大、峰不明显或预处理过强。")

    return {
        "success": True,
        "peaks": peaks,
        "peak_count": len(peaks),
        "warnings": warnings,
    }
