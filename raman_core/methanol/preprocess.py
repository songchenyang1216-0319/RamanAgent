"""光谱预处理与数据增强函数。"""

from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy import sparse
from scipy.signal import savgol_filter
from scipy.sparse.linalg import spsolve


ALS_LAM = 1e5
ALS_P = 0.01
ALS_NITER = 10


def interpolate_to_axis(x: np.ndarray, y: np.ndarray, axis: np.ndarray) -> np.ndarray:
    """将单条光谱插值到统一波数轴。"""
    return np.interp(axis, x, y)


def normalize_01(arr: np.ndarray) -> np.ndarray:
    """将输入按 0 到 1 归一化。"""
    arr = np.asarray(arr, dtype=float)
    arr_min, arr_max = arr.min(), arr.max()
    if arr_max > arr_min:
        arr = (arr - arr_min) / (arr_max - arr_min)
    else:
        arr = np.zeros_like(arr)
    return arr.astype(np.float32)


def apply_sg_smoothing(y: np.ndarray, sg_window: int, sg_order: int) -> np.ndarray:
    """执行 Savitzky-Golay 平滑。"""
    y = np.asarray(y, dtype=float).copy()
    if len(y) >= sg_window and sg_window % 2 == 1 and sg_order < sg_window:
        y = savgol_filter(y, sg_window, sg_order)
    return y.astype(np.float32)


def baseline_als(
    y: np.ndarray,
    lam: float = ALS_LAM,
    p: float = ALS_P,
    niter: int = ALS_NITER,
) -> np.ndarray:
    """使用 ALS 方法估计光谱基线。"""
    y = np.asarray(y, dtype=float)
    length = len(y)
    d = sparse.diags([1, -2, 1], [0, 1, 2], shape=(length - 2, length))
    w = np.ones(length)

    for _ in range(niter):
        w_mat = sparse.spdiags(w, 0, length, length)
        z_mat = w_mat + lam * (d.T @ d)
        z = spsolve(z_mat, w * y)
        w = p * (y > z) + (1 - p) * (y <= z)

    return np.asarray(z, dtype=np.float32)


def preprocess_for_regression_branch(y: np.ndarray, sg_window: int, sg_order: int) -> np.ndarray:
    """回归分支预处理：SG 平滑后归一化。"""
    y_sg = apply_sg_smoothing(y, sg_window, sg_order)
    return normalize_01(y_sg)


def preprocess_for_cdae_branch(y: np.ndarray, sg_window: int, sg_order: int) -> np.ndarray:
    """CDAE 回归分支预处理，当前逻辑与回归分支一致。"""
    return preprocess_for_regression_branch(y, sg_window, sg_order)


def preprocess_for_als_branch(
    y: np.ndarray,
    sg_window: int,
    sg_order: int,
    lam: float = ALS_LAM,
    p: float = ALS_P,
    niter: int = ALS_NITER,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ALS 分支预处理：SG 平滑、ALS 去基线、归一化。"""
    y_sg = apply_sg_smoothing(y, sg_window, sg_order)
    baseline = baseline_als(y_sg, lam=lam, p=p, niter=niter)
    corrected = np.clip(y_sg - baseline, 0.0, None)
    normalized = normalize_01(corrected)
    return normalized, y_sg.astype(np.float32), baseline.astype(np.float32)


def baseline_als_for_pseudo_label(
    y: np.ndarray,
    lam: float = ALS_LAM,
    p: float = ALS_P,
    niter: int = ALS_NITER,
) -> np.ndarray:
    """为 CAE+ 训练生成伪基线标签。"""
    z = baseline_als(y, lam=lam, p=p, niter=niter)
    return np.clip(z, 0.0, 1.0).astype(np.float32)


def correct_by_baseline(denoised: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    """对 1D 或 2D 光谱做基线扣除并归一化。"""
    corrected = np.clip(denoised - baseline, 0.0, None)
    corrected = np.asarray(corrected, dtype=float)
    if corrected.ndim == 1:
        return normalize_01(corrected)
    return np.array([normalize_01(spectrum) for spectrum in corrected], dtype=np.float32)


def add_noise(
    y: np.ndarray,
    rng: np.random.Generator,
    level_range: Tuple[float, float] = (0.01, 0.06),
) -> np.ndarray:
    """加入高斯噪声。"""
    sigma = rng.uniform(*level_range)
    return y + rng.normal(0, sigma, size=len(y))


def add_baseline_distortion(y: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """加入缓慢变化的基线漂移。"""
    x = np.linspace(0, 1, len(y))
    amp = rng.uniform(0.03, 0.18)
    freq = rng.uniform(0.5, 2.0)
    phase = rng.uniform(0, 2 * np.pi)
    drift = amp * np.sin(2 * np.pi * freq * x + phase)
    drift += rng.uniform(-0.06, 0.06) * (x - 0.5) ** 2
    return y + drift


def add_fluorescence_background(y: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """加入荧光型背景。"""
    x = np.arange(len(y))
    center = rng.uniform(0.2 * len(y), 0.8 * len(y))
    width = rng.uniform(0.25 * len(y), 0.6 * len(y))
    amp = rng.uniform(0.08, 0.30)
    background = amp * np.exp(-0.5 * ((x - center) / width) ** 2)
    return y + background


def add_spikes(
    y: np.ndarray,
    rng: np.random.Generator,
    count_range: Tuple[int, int] = (0, 3),
) -> np.ndarray:
    """加入尖峰噪声。"""
    y = y.copy()
    count = rng.integers(count_range[0], count_range[1] + 1)
    for _ in range(count):
        idx = rng.integers(2, len(y) - 2)
        height = rng.uniform(0.10, 0.45)
        y[idx - 1: idx + 2] += np.array([0.4, 1.0, 0.4]) * height
    return y


def augment_spectrum(clean_y: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """构造用于去噪训练的增强光谱。"""
    y = clean_y.copy()
    ops = [add_noise, add_baseline_distortion, add_fluorescence_background, add_spikes]
    rng.shuffle(ops)
    for op in ops[: rng.integers(2, 5)]:
        y = op(y, rng)
    return normalize_01(y)
