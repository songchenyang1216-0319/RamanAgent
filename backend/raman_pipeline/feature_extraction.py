"""Peak extraction and quality control algorithms."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import signal

from .algorithm_schema import AlgorithmRunOutput, RamanPipelineError


def _xy(data: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if data.get("wavenumber") is None or data.get("intensity") is None:
        raise RamanPipelineError("当前步骤需要先读取光谱数据。")
    x = np.asarray(data["wavenumber"], dtype=float)
    y = np.asarray(data["intensity"], dtype=float)
    if x.size != y.size or x.size < 3:
        raise RamanPipelineError("光谱数据长度不合法。")
    return x, y


def _peaks(data: dict[str, Any]) -> list[dict[str, Any]]:
    return list(data.get("peaks") or [])


def find_peaks_basic(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    distance = int(params.get("distance", 5))
    height = params.get("height")
    indices, properties = signal.find_peaks(y, distance=max(distance, 1), height=height)
    peaks = [
        {
            "index": int(idx),
            "wavenumber": float(x[idx]),
            "height": float(y[idx]),
        }
        for idx in indices
    ]
    out = dict(data)
    out["peaks"] = peaks
    return AlgorithmRunOutput(data=out, metrics={"peak_count": len(peaks), "properties": {k: np.asarray(v).tolist() for k, v in properties.items()}})


def find_peaks_prominence(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    prominence = float(params.get("prominence", max(np.nanstd(y), 1e-9)))
    distance = int(params.get("distance", 5))
    indices, properties = signal.find_peaks(y, prominence=prominence, distance=max(distance, 1))
    peaks = []
    for i, idx in enumerate(indices):
        peaks.append(
            {
                "index": int(idx),
                "wavenumber": float(x[idx]),
                "height": float(y[idx]),
                "prominence": float(properties.get("prominences", [0])[i]),
            }
        )
    out = dict(data)
    out["peaks"] = peaks
    return AlgorithmRunOutput(data=out, metrics={"peak_count": len(peaks), "prominence": prominence})


def peak_height(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    peaks = _peaks(data)
    if not peaks:
        return find_peaks_basic(data, params)
    heights = [float(item.get("height", 0.0)) for item in peaks]
    return AlgorithmRunOutput(data=data, metrics={"max_peak_height": max(heights), "mean_peak_height": float(np.mean(heights))})


def peak_width(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    peaks = _peaks(data)
    if not peaks:
        found = find_peaks_basic(data, params)
        data = found.data
        peaks = _peaks(data)
    indices = np.asarray([int(item["index"]) for item in peaks], dtype=int)
    if indices.size == 0:
        return AlgorithmRunOutput(data=data, metrics={"peak_count": 0})
    widths, _, left_ips, right_ips = signal.peak_widths(y, indices, rel_height=float(params.get("rel_height", 0.5)))
    step = float(np.mean(np.diff(np.sort(x)))) if len(x) > 1 else 1.0
    enriched = []
    for item, width, left, right in zip(peaks, widths, left_ips, right_ips):
        clone = dict(item)
        clone["width_points"] = float(width)
        clone["width_wavenumber"] = float(abs(width * step))
        clone["left_ip"] = float(left)
        clone["right_ip"] = float(right)
        enriched.append(clone)
    out = dict(data)
    out["peaks"] = enriched
    return AlgorithmRunOutput(data=out, metrics={"mean_width_wavenumber": float(np.mean([p["width_wavenumber"] for p in enriched]))})


def peak_area(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    peaks = _peaks(data)
    if not peaks:
        data = find_peaks_basic(data, params).data
        peaks = _peaks(data)
    half_window = int(params.get("half_window", 8))
    enriched = []
    for item in peaks:
        idx = int(item["index"])
        left = max(0, idx - half_window)
        right = min(len(y), idx + half_window + 1)
        clone = dict(item)
        clone["area"] = float(np.trapezoid(y[left:right], x[left:right]))
        enriched.append(clone)
    out = dict(data)
    out["peaks"] = enriched
    return AlgorithmRunOutput(data=out, metrics={"total_peak_area": float(sum(float(p.get("area", 0.0)) for p in enriched))})


def peak_table_export(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    peaks = _peaks(data)
    table = pd.DataFrame(peaks).to_dict(orient="records") if peaks else []
    out = dict(data)
    out.setdefault("tables", {})["peaks"] = table
    return AlgorithmRunOutput(data=out, metrics={"rows": len(table)}, artifacts=[{"type": "table", "title": "峰表", "rows": table[:50]}])


def estimate_snr(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    noise = np.diff(y)
    noise_std = float(np.nanstd(noise) / np.sqrt(2)) if noise.size else 0.0
    signal_range = float(np.nanmax(y) - np.nanmin(y))
    snr = signal_range / noise_std if noise_std > 0 else float("inf")
    return AlgorithmRunOutput(data=data, metrics={"snr": float(snr), "noise_std": noise_std, "signal_range": signal_range})


def baseline_drift_score(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    coeff = np.polyfit(x, y, 1)
    drift = float(abs(coeff[0]) * (np.nanmax(x) - np.nanmin(x)) / (np.nanmax(y) - np.nanmin(y) + 1e-12))
    return AlgorithmRunOutput(data=data, metrics={"baseline_drift_score": drift})


def saturation_check(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    threshold = float(params.get("threshold", np.nanmax(y) * 0.995))
    saturated = int(np.sum(y >= threshold))
    return AlgorithmRunOutput(data=data, metrics={"saturated_points": saturated, "saturation_ratio": float(saturated / len(y))})


def cosmic_ray_check(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    z = np.abs((y - np.nanmedian(y)) / (np.nanstd(y) + 1e-12))
    threshold = float(params.get("z_threshold", 8.0))
    count = int(np.sum(z > threshold))
    return AlgorithmRunOutput(data=data, metrics={"cosmic_ray_candidates": count, "z_threshold": threshold})


def fluorescence_background_score(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    coeff = np.polyfit(x, y, 2)
    background = np.polyval(coeff, x)
    score = float(np.nanstd(background) / (np.nanstd(y) + 1e-12))
    return AlgorithmRunOutput(data=data, metrics={"fluorescence_background_score": score})


def spectrum_quality_score(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    metrics: dict[str, Any] = {}
    for fn in (estimate_snr, baseline_drift_score, saturation_check, cosmic_ray_check, fluorescence_background_score):
        metrics.update(fn(data, params).metrics)
    snr_score = min(float(metrics.get("snr", 0.0)) / 50.0, 1.0)
    drift_penalty = min(float(metrics.get("baseline_drift_score", 0.0)), 1.0)
    saturation_penalty = min(float(metrics.get("saturation_ratio", 0.0)) * 5, 1.0)
    cosmic_penalty = min(float(metrics.get("cosmic_ray_candidates", 0.0)) / 10.0, 1.0)
    final = max(0.0, min(1.0, 0.55 * snr_score + 0.45 * (1 - max(drift_penalty, saturation_penalty, cosmic_penalty))))
    metrics["spectrum_quality_score"] = float(final)
    return AlgorithmRunOutput(data=data, metrics=metrics)

