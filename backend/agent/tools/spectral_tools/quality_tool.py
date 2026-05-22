"""Raman 光谱质量评估工具。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.agent.tools.spectral_tools.spectrum_loader import load_raman_csv


QUALITY_THRESHOLDS = {
    "good_snr": 25.0,
    "acceptable_snr": 8.0,
    "high_outlier_ratio": 0.03,
    "low_points": 50,
    "flat_range": 1e-8,
}


def _clip01(value: float) -> float:
    """把评分限制到 0 到 1。"""
    return float(np.clip(value, 0.0, 1.0))


def _smooth_signal(y: np.ndarray) -> np.ndarray:
    """优先使用 Savitzky-Golay 平滑，失败时退化为移动平均。"""
    try:
        from scipy.signal import savgol_filter

        window = min(max(7, len(y) // 35 * 2 + 1), len(y) - 1 if len(y) % 2 == 0 else len(y))
        window = max(5, window if window % 2 == 1 else window - 1)
        if window >= len(y):
            window = len(y) - 1 if len(y) % 2 == 0 else len(y)
        return savgol_filter(y, window_length=max(5, window), polyorder=2)
    except Exception:
        window = max(5, min(len(y) // 20, 31))
        kernel = np.ones(window) / window
        return np.convolve(y, kernel, mode="same")


def _signal_to_noise_score(estimated_snr: float) -> float:
    """把启发式 SNR 转成质量分，5 以下较差，35 以上较好。"""
    return _clip01((float(estimated_snr) - 5.0) / 30.0)


def _baseline_scores(y: np.ndarray) -> tuple[float, float]:
    """返回基线漂移风险分和对应质量分。"""
    y_range = float(np.ptp(y))
    if y_range <= 1e-12 or len(y) < 4:
        return 1.0, 0.0
    x_norm = np.linspace(0.0, 1.0, len(y))
    y_norm = (y - np.min(y)) / y_range
    linear_fit = np.polyval(np.polyfit(x_norm, y_norm, deg=1), x_norm)
    cubic_fit = np.polyval(np.polyfit(x_norm, y_norm, deg=3), x_norm)
    end_to_end = abs(float(linear_fit[-1] - linear_fit[0]))
    low_frequency = float(np.std(cubic_fit - np.mean(y_norm)))
    drift_risk = _clip01(max(end_to_end / 0.35, low_frequency / 0.28))
    return drift_risk, _clip01(1.0 - drift_risk)


def _peak_sharpness_score(y: np.ndarray) -> float:
    """估计峰是否清晰；峰越突出且宽度不过分离散，分数越高。"""
    y_range = float(np.ptp(y))
    if y_range <= 1e-12 or len(y) < 8:
        return 0.0
    smoothed = _smooth_signal(y)
    try:
        from scipy.signal import find_peaks, peak_widths

        peaks, props = find_peaks(smoothed, prominence=max(y_range * 0.04, 1e-12), distance=max(3, len(y) // 120))
        if len(peaks) == 0:
            return 0.25
        prominences = np.asarray(props.get("prominences", []), dtype=float)
        widths = np.asarray(peak_widths(smoothed, peaks, rel_height=0.5)[0], dtype=float)
        prominence_score = _clip01(float(np.median(prominences)) / max(y_range * 0.25, 1e-12))
        width_ratio = float(np.median(widths)) / max(float(len(y)), 1.0)
        width_score = _clip01(1.0 - abs(width_ratio - 0.035) / 0.12)
        count_score = _clip01(len(peaks) / 5.0)
        return _clip01(0.55 * prominence_score + 0.30 * width_score + 0.15 * count_score)
    except Exception:
        curvature = float(np.percentile(np.abs(np.diff(smoothed, n=2)), 90))
        return _clip01(curvature / max(y_range * 0.015, 1e-12))


def _saturation_or_clipping_check(y: np.ndarray) -> dict:
    """检查峰顶削平或接近饱和的轻量风险。"""
    y_range = float(np.ptp(y))
    if y_range <= 1e-12:
        return {"risk": True, "clipped_ratio": 1.0, "score": 0.0, "message": "强度几乎不变化，可能为空白、饱和或读取异常。"}
    upper = float(np.max(y) - y_range * 0.005)
    lower = float(np.min(y) + y_range * 0.005)
    near_extreme_ratio = float(np.mean((y >= upper) | (y <= lower)))
    rounded = np.round(y, decimals=8)
    most_common_ratio = float(max(np.unique(rounded, return_counts=True)[1]) / len(y))
    clipped_ratio = max(near_extreme_ratio, most_common_ratio if most_common_ratio > 0.03 else 0.0)
    risk = clipped_ratio > 0.035
    message = "未发现明显饱和或削顶。"
    if risk:
        message = "存在饱和或削顶迹象，峰顶形状可能失真。"
    return {"risk": bool(risk), "clipped_ratio": clipped_ratio, "score": _clip01(1.0 - clipped_ratio / 0.08), "message": message}


def _abnormal_intensity_check(y: np.ndarray) -> dict:
    """检查强度异常点和尖峰比例。"""
    median = float(np.median(y))
    mad = float(np.median(np.abs(y - median))) or 1e-12
    robust_z = np.abs((y - median) / (1.4826 * mad))
    outlier_ratio = float(np.mean(robust_z > 7.0))
    diff = np.diff(y)
    diff_mad = float(np.median(np.abs(diff - np.median(diff)))) or 1e-12
    spike_ratio = float(np.mean(np.abs(diff - np.median(diff)) / (1.4826 * diff_mad) > 8.0)) if len(diff) else 0.0
    risk = outlier_ratio > 0.02 or spike_ratio > 0.03
    message = "强度分布未见明显异常。"
    if risk:
        message = "检测到异常尖峰或强度离群点，可能影响弱峰识别。"
    return {
        "risk": bool(risk),
        "outlier_ratio": outlier_ratio,
        "spike_ratio": spike_ratio,
        "score": _clip01(1.0 - max(outlier_ratio / 0.08, spike_ratio / 0.10)),
        "message": message,
    }


def analyze_spectrum_quality(csv_path: str | Path) -> dict:
    """评估光谱点数、信噪比、异常值和过平滑风险。"""
    loaded = load_raman_csv(csv_path)
    if not loaded.get("success"):
        return loaded

    try:
        y = np.asarray(loaded["y"], dtype=float)
        smoothed = _smooth_signal(y)
        residual = y - smoothed
        noise_std = float(np.std(residual))
        intensity_range = float(np.ptp(y))
        estimated_snr = float(intensity_range / max(noise_std, 1e-12))
        robust_std = float(np.std(y)) or 1e-12
        z_scores = np.abs((y - np.median(y)) / robust_std)
        outlier_ratio = float(np.mean(z_scores > 5.0))
        smoothness_score = float(np.std(np.diff(y)) / max(intensity_range, 1e-12))
        snr_score = _signal_to_noise_score(estimated_snr)
        baseline_drift_score, baseline_quality_score = _baseline_scores(y)
        peak_score = _peak_sharpness_score(y)
        clipping_check = _saturation_or_clipping_check(y)
        abnormal_check = _abnormal_intensity_check(y)

        warnings = []
        issues = []
        suggestions = []
        if loaded["points"] < QUALITY_THRESHOLDS["low_points"]:
            warnings.append("光谱点数较少，可能影响峰识别和质量判断稳定性。")
            issues.append("采样点数偏少")
        if intensity_range <= QUALITY_THRESHOLDS["flat_range"]:
            warnings.append("光谱强度范围过小，可能接近空白或读取异常。")
            issues.append("强度范围过小")
        if estimated_snr < QUALITY_THRESHOLDS["acceptable_snr"]:
            warnings.append("估计信噪比较低，主要峰和预测结果可能不够稳定。")
            issues.append("信噪比较低")
            suggestions.extend(["增加积分时间", "做重复采集", "检查暗噪声和背景"])
        elif estimated_snr < QUALITY_THRESHOLDS["good_snr"]:
            issues.append("信噪比中等")
        if outlier_ratio > QUALITY_THRESHOLDS["high_outlier_ratio"]:
            warnings.append("异常点比例偏高，可能存在尖峰或采集异常。")
            issues.append("异常点比例偏高")
            suggestions.extend(["检查宇宙射线尖峰", "检查采集异常点"])
        if smoothness_score < 0.002:
            warnings.append("光谱变化非常平缓，可能存在过度平滑或有效峰不明显。")
            issues.append("峰形变化不明显")
        if baseline_drift_score > 0.5:
            warnings.append("基线漂移评分偏高，建议结合四阶段预处理图检查。")
            issues.append("基线漂移风险")
            suggestions.extend(["检查荧光背景", "重新采集背景或优化 ALS 参数"])
        if clipping_check["risk"]:
            warnings.append(clipping_check["message"])
            issues.append("饱和或削顶风险")
            suggestions.append("降低曝光或积分时间后重复采集")
        if abnormal_check["risk"]:
            warnings.append(abnormal_check["message"])
            issues.append("异常强度点")
            suggestions.append("检查宇宙射线尖峰并考虑重复采集")

        if estimated_snr >= QUALITY_THRESHOLDS["good_snr"] and not warnings:
            quality_level = "good"
        elif estimated_snr >= QUALITY_THRESHOLDS["acceptable_snr"] and outlier_ratio <= QUALITY_THRESHOLDS["high_outlier_ratio"]:
            quality_level = "acceptable"
        else:
            quality_level = "poor"

        overall_quality_score = _clip01(
            0.35 * snr_score
            + 0.25 * baseline_quality_score
            + 0.20 * peak_score
            + 0.10 * clipping_check["score"]
            + 0.10 * abnormal_check["score"]
        )
        if overall_quality_score >= 0.72 and quality_level != "poor":
            overall_quality = "good"
        elif overall_quality_score >= 0.45:
            overall_quality = "medium"
        else:
            overall_quality = "poor"

        return {
            "success": True,
            "quality_level": quality_level,
            "overall_quality": overall_quality,
            "score": overall_quality_score,
            "issues": list(dict.fromkeys(issues)),
            "metrics": {
                "points": int(loaded["points"]),
                "intensity_range": intensity_range,
                "mean_intensity": float(np.mean(y)),
                "std_intensity": float(np.std(y)),
                "estimated_noise": noise_std,
                "estimated_snr": estimated_snr,
                "outlier_ratio": outlier_ratio,
                "smoothness_score": smoothness_score,
                "signal_to_noise_score": snr_score,
                "baseline_drift_score": baseline_drift_score,
                "baseline_quality_score": baseline_quality_score,
                "peak_sharpness_score": peak_score,
            },
            "signal_to_noise_score": snr_score,
            "baseline_drift_score": baseline_drift_score,
            "peak_sharpness_score": peak_score,
            "saturation_or_clipping_check": clipping_check,
            "abnormal_intensity_check": abnormal_check,
            "overall_quality_score": overall_quality_score,
            "warnings": warnings,
            "suggestions": list(dict.fromkeys(suggestions)),
        }
    except Exception as exc:
        return {"success": False, "error_message": f"光谱质量评估失败: {exc}"}
