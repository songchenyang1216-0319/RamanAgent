"""基线质量启发式分析工具。"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.agent.tools.spectral_tools.spectrum_loader import load_raman_csv


BASELINE_THRESHOLDS = {
    "drift_warning": 0.18,
    "trend_warning": 0.22,
    "over_smooth": 0.003,
    "negative_ratio_warning": 0.08,
}


def _build_stage_comparison(metrics: dict, prediction_result: dict | None) -> dict:
    """生成四阶段基线质量说明；没有中间数组时只做轻量证据提示。"""
    prediction_result = prediction_result or {}
    figure_paths = prediction_result.get("figure_paths") or {}
    pipeline = prediction_result.get("pipeline") or []
    has_pipeline = bool(figure_paths or pipeline)
    raw_status = "drift_risk" if metrics["possible_under_correction"] else "usable"
    processed_status = "available_for_review" if has_pipeline else "not_available"
    processed_note = (
        "预测结果包含预处理流程或图像路径，建议结合四阶段图确认峰形是否被保留。"
        if has_pipeline
        else "当前调用没有提供 ALS/CDAE/CAE+ 中间数组或图像，只能基于原始谱做启发式判断。"
    )
    return {
        "raw": {
            "status": raw_status,
            "note": "原始谱低频趋势明显，需要关注荧光背景或基线漂移。" if raw_status == "drift_risk" else "原始谱未见明显低频基线漂移。",
        },
        "als": {
            "status": processed_status,
            "note": processed_note,
        },
        "cdae": {
            "status": processed_status,
            "note": "CDAE 阶段主要关注噪声降低后弱峰是否仍保留；本工具不直接重算模型中间张量。",
        },
        "caeplus": {
            "status": processed_status,
            "note": "CAE+ 后应重点检查预测基线是否削弱有效峰；如四阶段图峰顶变平，需要人工复核。",
        },
    }


def analyze_baseline_quality(csv_path: str | Path, prediction_result: dict | None = None) -> dict:
    """粗略判断原始光谱中的低频基线漂移和修正风险。"""
    loaded = load_raman_csv(csv_path)
    if not loaded.get("success"):
        return loaded

    try:
        x = np.asarray(loaded["x"], dtype=float)
        y = np.asarray(loaded["y"], dtype=float)
        y_range = float(np.ptp(y))
        if y_range <= 1e-12:
            return {
                "success": True,
                "baseline_level": "unknown",
                "metrics": {
                    "baseline_drift_score": 0.0,
                    "low_frequency_trend_score": 0.0,
                    "possible_overcorrection": False,
                    "possible_under_correction": False,
                },
                "warnings": ["光谱强度变化太小，当前数据不足以判断基线质量。"],
                "suggestions": ["请检查原始 CSV 是否读取正确。"],
            }

        x_norm = (x - np.min(x)) / max(float(np.ptp(x)), 1e-12)
        y_norm = (y - np.min(y)) / y_range
        linear_fit = np.polyval(np.polyfit(x_norm, y_norm, deg=1), x_norm)
        cubic_fit = np.polyval(np.polyfit(x_norm, y_norm, deg=min(3, len(x_norm) - 1)), x_norm)
        baseline_drift_score = float(abs(linear_fit[-1] - linear_fit[0]))
        low_frequency_trend_score = float(np.std(cubic_fit - np.mean(y_norm)))
        high_freq_score = float(np.std(np.diff(y_norm)))
        negative_ratio = float(np.mean(y_norm < -0.02))
        peak_dynamic_ratio = float((np.percentile(y_norm, 95) - np.percentile(y_norm, 50)) / max(np.std(y_norm), 1e-12))

        possible_under = baseline_drift_score > BASELINE_THRESHOLDS["drift_warning"] or low_frequency_trend_score > BASELINE_THRESHOLDS["trend_warning"]
        possible_over = high_freq_score < BASELINE_THRESHOLDS["over_smooth"] and len(prediction_result or {}) > 0
        negative_peak_risk = negative_ratio > BASELINE_THRESHOLDS["negative_ratio_warning"]
        peak_weakening_risk = possible_over or peak_dynamic_ratio < 0.8

        warnings = []
        suggestions = []
        if possible_under:
            warnings.append("原始光谱中低频趋势较明显，可能存在基线漂移。")
            suggestions.extend(["检查 ALS 参数", "对比 CAE+ 去基线前后图", "重新采集背景"])
        if possible_over:
            warnings.append("光谱变化过于平缓，需要关注是否存在过度修正。")
            suggestions.append("结合四阶段图检查有效峰是否被削弱。")
        if negative_peak_risk:
            warnings.append("处理后可能存在负峰风险，需要结合预处理后光谱确认。")
            suggestions.append("检查基线扣除是否过强。")
        if peak_weakening_risk:
            warnings.append("峰形对比度偏弱，需确认预处理是否削弱有效峰。")

        if possible_under:
            baseline_level = "drift_risk"
        elif possible_over:
            baseline_level = "overcorrection_risk"
        else:
            baseline_level = "normal"
        if possible_under or possible_over or negative_peak_risk:
            regression_suitability = "caution"
        elif peak_weakening_risk:
            regression_suitability = "caution"
        else:
            regression_suitability = "suitable"

        metrics = {
            "baseline_drift_score": baseline_drift_score,
            "low_frequency_trend_score": low_frequency_trend_score,
            "possible_overcorrection": bool(possible_over),
            "possible_under_correction": bool(possible_under),
            "negative_ratio": negative_ratio,
            "peak_dynamic_ratio": peak_dynamic_ratio,
        }

        return {
            "success": True,
            "baseline_level": baseline_level,
            "metrics": metrics,
            "over_subtraction_risk": bool(possible_over),
            "peak_weakening_risk": bool(peak_weakening_risk),
            "negative_peak_risk": bool(negative_peak_risk),
            "regression_suitability": regression_suitability,
            "stage_comparison": _build_stage_comparison(metrics, prediction_result),
            "warnings": warnings,
            "suggestions": list(dict.fromkeys(suggestions)),
        }
    except Exception as exc:
        return {"success": False, "error_message": f"基线质量分析失败: {exc}"}
