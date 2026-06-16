"""Local Raman preprocessing algorithms."""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy import interpolate, signal, sparse
from scipy.ndimage import gaussian_filter1d, median_filter as scipy_median_filter
from scipy.sparse.linalg import spsolve
from scipy.spatial import ConvexHull

from .algorithm_schema import AlgorithmRunOutput, RamanPipelineError


def _xy(data: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if data.get("wavenumber") is None or data.get("intensity") is None:
        raise RamanPipelineError("当前步骤需要先读取光谱数据。")
    x = np.asarray(data["wavenumber"], dtype=float)
    y = np.asarray(data["intensity"], dtype=float)
    if x.size != y.size:
        raise RamanPipelineError("波数数组和强度数组长度不一致。")
    if x.size < 3:
        raise RamanPipelineError("光谱点数过少，无法执行该算法。")
    return x, y


def _with_y(data: dict[str, Any], y: np.ndarray, **extra: Any) -> dict[str, Any]:
    out = dict(data)
    out["intensity"] = np.asarray(y, dtype=float)
    out.update(extra)
    return out


def _with_xy(data: dict[str, Any], x: np.ndarray, y: np.ndarray, **extra: Any) -> dict[str, Any]:
    out = dict(data)
    out["wavenumber"] = np.asarray(x, dtype=float)
    out["intensity"] = np.asarray(y, dtype=float)
    out.update(extra)
    return out


def remove_nan_inf(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    mask = np.isfinite(x) & np.isfinite(y)
    removed = int((~mask).sum())
    if mask.sum() < 3:
        raise RamanPipelineError("移除 NaN/Inf 后有效点不足 3 个。")
    return AlgorithmRunOutput(data=_with_xy(data, x[mask], y[mask]), metrics={"removed_points": removed})


def sort_by_wavenumber(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    order = np.argsort(x)
    changed = bool(np.any(order != np.arange(len(order))))
    return AlgorithmRunOutput(data=_with_xy(data, x[order], y[order]), metrics={"changed": changed})


def remove_duplicate_wavenumber(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    unique_x, inverse = np.unique(x, return_inverse=True)
    sums = np.zeros_like(unique_x, dtype=float)
    counts = np.zeros_like(unique_x, dtype=float)
    np.add.at(sums, inverse, y)
    np.add.at(counts, inverse, 1)
    unique_y = sums / np.maximum(counts, 1)
    return AlgorithmRunOutput(data=_with_xy(data, unique_x, unique_y), metrics={"removed_duplicates": int(len(x) - len(unique_x))})


def crop_wavenumber_range(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    min_value = float(params.get("min_wavenumber", np.nanmin(x)))
    max_value = float(params.get("max_wavenumber", np.nanmax(x)))
    if min_value >= max_value:
        raise RamanPipelineError("参数错误：min_wavenumber 必须小于 max_wavenumber。")
    mask = (x >= min_value) & (x <= max_value)
    if mask.sum() < 3:
        raise RamanPipelineError("裁剪后有效点不足 3 个，请放宽波数范围。")
    return AlgorithmRunOutput(data=_with_xy(data, x[mask], y[mask]), metrics={"points": int(mask.sum())})


def _target_axis(x: np.ndarray, params: dict[str, Any]) -> np.ndarray:
    if isinstance(params.get("target_axis"), list) and len(params["target_axis"]) >= 3:
        axis = np.asarray(params["target_axis"], dtype=float)
    else:
        start = float(params.get("start", np.nanmin(x)))
        end = float(params.get("end", np.nanmax(x)))
        points = int(params.get("points", len(x)))
        if points < 3:
            raise RamanPipelineError("参数错误：points 至少为 3。")
        if start >= end:
            raise RamanPipelineError("参数错误：start 必须小于 end。")
        axis = np.linspace(start, end, points)
    if axis.size < 3:
        raise RamanPipelineError("目标波数轴至少需要 3 个点。")
    return axis


def resample_linear(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(sort_by_wavenumber(data, {}).data)
    axis = _target_axis(x, params)
    y_new = np.interp(axis, x, y)
    return AlgorithmRunOutput(data=_with_xy(data, axis, y_new), metrics={"points": int(len(axis))})


def resample_cubic(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(sort_by_wavenumber(data, {}).data)
    axis = _target_axis(x, params)
    if len(x) < 4:
        raise RamanPipelineError("三次插值至少需要 4 个有效点。")
    interpolator = interpolate.interp1d(x, y, kind="cubic", bounds_error=False, fill_value="extrapolate")
    return AlgorithmRunOutput(data=_with_xy(data, axis, interpolator(axis)), metrics={"points": int(len(axis))})


def align_to_reference_axis(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    if not isinstance(params.get("reference_axis"), list) or len(params["reference_axis"]) < 3:
        raise RamanPipelineError("参数错误：reference_axis 必须是至少 3 个波数点的数组。")
    return resample_linear(data, {"target_axis": params["reference_axis"]})


def savitzky_golay(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    window_length = int(params.get("window_length", 11))
    polyorder = int(params.get("polyorder", 2))
    if window_length % 2 == 0:
        raise RamanPipelineError("参数错误：SG window_length 必须是奇数。")
    if window_length <= polyorder:
        raise RamanPipelineError("参数错误：SG window_length 必须大于 polyorder。")
    if window_length > len(y):
        raise RamanPipelineError("参数错误：SG window_length 不能大于光谱点数。")
    y_new = signal.savgol_filter(y, window_length=window_length, polyorder=polyorder)
    return AlgorithmRunOutput(data=_with_y(data, y_new), metrics={"window_length": window_length, "polyorder": polyorder})


def moving_average(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    window_size = int(params.get("window_size", 5))
    if window_size < 1:
        raise RamanPipelineError("参数错误：window_size 必须大于 0。")
    kernel = np.ones(window_size, dtype=float) / window_size
    y_new = np.convolve(y, kernel, mode="same")
    return AlgorithmRunOutput(data=_with_y(data, y_new), metrics={"window_size": window_size})


def gaussian_filter(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    sigma = float(params.get("sigma", 1.0))
    if sigma <= 0:
        raise RamanPipelineError("参数错误：sigma 必须大于 0。")
    return AlgorithmRunOutput(data=_with_y(data, gaussian_filter1d(y, sigma=sigma)), metrics={"sigma": sigma})


def median_filter(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    size = int(params.get("size", 5))
    if size < 1:
        raise RamanPipelineError("参数错误：size 必须大于 0。")
    return AlgorithmRunOutput(data=_with_y(data, scipy_median_filter(y, size=size)), metrics={"size": size})


def butterworth_lowpass(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    cutoff = float(params.get("cutoff", 0.08))
    order = int(params.get("order", 3))
    if cutoff <= 0 or cutoff >= 1:
        raise RamanPipelineError("参数错误：cutoff 必须在 0 到 1 之间。")
    b, a = signal.butter(order, cutoff, btype="lowpass")
    y_new = signal.filtfilt(b, a, y) if len(y) > max(len(a), len(b)) * 3 else signal.lfilter(b, a, y)
    return AlgorithmRunOutput(data=_with_y(data, y_new), metrics={"cutoff": cutoff, "order": order})


def polynomial_baseline(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    degree = int(params.get("degree", 3))
    if degree < 0 or degree >= len(x):
        raise RamanPipelineError("参数错误：degree 必须不小于 0 且小于光谱点数。")
    coeff = np.polyfit(x, y, degree)
    baseline = np.polyval(coeff, x)
    return AlgorithmRunOutput(data={**data, "baseline": baseline}, metrics={"degree": degree})


def rubberband_baseline(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(sort_by_wavenumber(data, {}).data)
    points = np.column_stack([x, y])
    try:
        hull = ConvexHull(points)
        vertices = np.sort(hull.vertices)
        lower = vertices[np.argsort(x[vertices])]
        lower = lower[np.argsort(y[lower])[: max(3, len(lower) // 2)]]
        lower = np.sort(lower)
        if lower.size < 2:
            raise ValueError("convex hull lower vertices too few")
        baseline = np.interp(x, x[lower], y[lower])
    except Exception:
        baseline = np.interp(x, [x[0], x[-1]], [y[0], y[-1]])
    return AlgorithmRunOutput(data={**data, "wavenumber": x, "intensity": y, "baseline": baseline}, metrics={"method": "rubberband"})


def _als(y: np.ndarray, lam: float, p: float, iterations: int) -> np.ndarray:
    length = len(y)
    d = sparse.diags([1, -2, 1], [0, 1, 2], shape=(length - 2, length))
    w = np.ones(length)
    for _ in range(iterations):
        w_matrix = sparse.spdiags(w, 0, length, length)
        z = w_matrix + lam * d.T @ d
        baseline = spsolve(z, w * y)
        w = p * (y > baseline) + (1 - p) * (y < baseline)
    return baseline


def als_baseline(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    lam = float(params.get("lam", 100000.0))
    p = float(params.get("p", 0.01))
    iterations = int(params.get("iterations", 10))
    if lam <= 0 or not (0 < p < 1) or iterations < 1:
        raise RamanPipelineError("参数错误：lam 必须大于 0，p 必须在 0 到 1 之间，iterations 必须大于 0。")
    baseline = _als(y, lam, p, iterations)
    return AlgorithmRunOutput(data={**data, "baseline": baseline}, metrics={"lam": lam, "p": p, "iterations": iterations})


def airpls_baseline(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    lam = float(params.get("lam", 100000.0))
    iterations = int(params.get("iterations", 12))
    baseline = _als(y, lam, 0.001, iterations)
    return AlgorithmRunOutput(data={**data, "baseline": baseline}, metrics={"lam": lam, "iterations": iterations})


def baseline_subtraction(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    baseline = data.get("baseline")
    if baseline is None:
        baseline = als_baseline(data, params).data["baseline"]
    baseline_arr = np.asarray(baseline, dtype=float)
    if baseline_arr.size != y.size:
        raise RamanPipelineError("基线长度与强度数组长度不一致。")
    corrected = y - baseline_arr
    if bool(params.get("clip_negative", False)):
        corrected = np.clip(corrected, 0, None)
    return AlgorithmRunOutput(data=_with_y(data, corrected, baseline=baseline_arr), metrics={"baseline_subtracted": True})


def min_max_normalize(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    span = float(np.nanmax(y) - np.nanmin(y))
    if span == 0:
        raise RamanPipelineError("强度没有变化，无法做 min-max 归一化。")
    return AlgorithmRunOutput(data=_with_y(data, (y - np.nanmin(y)) / span), metrics={"method": "min_max"})


def z_score_normalize(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    std = float(np.nanstd(y))
    if std == 0:
        raise RamanPipelineError("强度标准差为 0，无法做 z-score 归一化。")
    return AlgorithmRunOutput(data=_with_y(data, (y - np.nanmean(y)) / std), metrics={"method": "z_score"})


def vector_normalize(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    norm = float(np.linalg.norm(y))
    if norm == 0:
        raise RamanPipelineError("强度向量范数为 0，无法做向量归一化。")
    return AlgorithmRunOutput(data=_with_y(data, y / norm), metrics={"norm": norm})


def area_normalize(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    x, y = _xy(data)
    area = float(np.trapezoid(y, x))
    if area == 0:
        raise RamanPipelineError("曲线面积为 0，无法做面积归一化。")
    return AlgorithmRunOutput(data=_with_y(data, y / area), metrics={"area": area})


def max_intensity_normalize(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    max_value = float(np.nanmax(np.abs(y)))
    if max_value == 0:
        raise RamanPipelineError("最大强度为 0，无法归一化。")
    return AlgorithmRunOutput(data=_with_y(data, y / max_value), metrics={"max_abs_intensity": max_value})


def standard_normal_variate(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    return z_score_normalize(data, params)


def multiplicative_scatter_correction(data: dict[str, Any], params: dict[str, Any]) -> AlgorithmRunOutput:
    _, y = _xy(data)
    reference = params.get("reference")
    ref = np.asarray(reference, dtype=float) if isinstance(reference, list) and len(reference) == len(y) else np.linspace(y[0], y[-1], len(y))
    coeff = np.polyfit(ref, y, 1)
    if coeff[0] == 0:
        raise RamanPipelineError("MSC 拟合斜率为 0，无法校正。")
    corrected = (y - coeff[1]) / coeff[0]
    return AlgorithmRunOutput(data=_with_y(data, corrected), metrics={"slope": float(coeff[0]), "intercept": float(coeff[1])})

