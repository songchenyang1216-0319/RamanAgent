"""甲醇预测服务层。"""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

import numpy as np

from backend.services.model_registry_service import ModelRegistryService

_predictor_instance = None
_predictor_model_version = None


def reset_predictor_cache() -> None:
    """模型切换后清空预测器缓存，避免继续使用旧 artifact。"""
    global _predictor_instance
    global _predictor_model_version
    _predictor_instance = None
    _predictor_model_version = None


def _to_builtin(value: Any) -> Any:
    """递归将 numpy、Path 等对象转换为可 JSON 序列化类型。"""
    if isinstance(value, dict):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_builtin(item) for item in value]
    if isinstance(value, tuple):
        return [_to_builtin(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def get_predictor():
    """延迟初始化预测器，避免每次请求都重复加载模型。"""
    global _predictor_instance
    global _predictor_model_version

    registry_service = ModelRegistryService()
    default_model_response = registry_service.get_default_model()
    model_info = default_model_response.get("data") if default_model_response.get("success") else {}
    model_version = str((model_info or {}).get("model_version") or "methanol_v1")
    artifact_dir = str((model_info or {}).get("artifact_dir") or "artifacts")

    if _predictor_instance is None or _predictor_model_version != model_version:
        try:
            from raman_core.methanol import MethanolPredictor
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "无法导入 MethanolPredictor，请确认已安装推理依赖，例如 torch。"
            ) from exc

        try:
            _predictor_instance = MethanolPredictor(artifact_dir=artifact_dir)
            _predictor_model_version = model_version
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"初始化预测器失败，缺少模型文件: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"初始化预测器失败: {exc}") from exc
    return _predictor_instance


def calculate_model_disagreement(
    svr_prediction: float,
    rf_prediction: float,
    fusion_prediction: float,
) -> dict:
    """计算 SVR 与 RF 预测差异，并给出提醒信息。"""
    def _safe_float(env_name: str, default: float) -> float:
        try:
            value = float(os.getenv(env_name, str(default)))
        except (TypeError, ValueError):
            return default
        if value <= 0:
            return default
        # 只接受更严格的阈值，避免环境变量把测试和默认行为放松得过头。
        return min(value, default)

    abs_threshold = _safe_float("MODEL_DISAGREEMENT_ABS_THRESHOLD", 1.0)
    rel_threshold = _safe_float("MODEL_DISAGREEMENT_REL_THRESHOLD", 0.05)
    low_value_threshold = _safe_float("MODEL_DISAGREEMENT_LOW_VALUE_THRESHOLD", 5.0)
    low_abs_threshold = _safe_float("MODEL_DISAGREEMENT_LOW_ABS_THRESHOLD", 0.2)

    absolute_difference = abs(float(svr_prediction) - float(rf_prediction))
    relative_difference = absolute_difference / max(abs(float(fusion_prediction)), 1e-8)

    high_relative_warning = relative_difference > rel_threshold
    low_value_abs_warning = abs(float(fusion_prediction)) < low_value_threshold and absolute_difference > low_abs_threshold
    warning = high_relative_warning or low_value_abs_warning

    if low_value_abs_warning:
        message = "当前样本预测值较低，SVR 与 RF 的绝对差异需要关注，建议人工复核。"
    elif high_relative_warning:
        message = "SVR 与 RF 的相对差异较大，建议结合图谱和重复样本进行复核。"
    else:
        message = "SVR 与 RF 预测结果一致性较好。"

    return {
        "absolute_difference": float(absolute_difference),
        "relative_difference": float(relative_difference),
        "abs_threshold": float(abs_threshold),
        "rel_threshold": float(rel_threshold),
        "low_value_threshold": float(low_value_threshold),
        "low_abs_threshold": float(low_abs_threshold),
        "warning": bool(warning),
        "message": message,
    }


def parse_expected_value_from_filename(sample_file: str | None) -> float | None:
    """尝试从样品文件名中解析疑似真实浓度。"""
    if not sample_file:
        return None
    match = re.search(r"-(\d+(?:\.\d+)?)-", str(sample_file))
    return float(match.group(1)) if match else None


def _resolve_unit(raw_result: dict) -> str:
    """整理结果中的单位字段，优先使用环境变量覆盖占位符。"""
    unit = str(raw_result.get("unit", "") or "").strip()
    if not unit or unit == "percent_or_ppm":
        unit = str(os.getenv("METHANOL_UNIT", "%")).strip() or "%"
    return unit


def build_public_prediction_result(raw_result: dict, include_intermediate: bool = False) -> dict:
    """
    将 MethanolPredictor.predict 的原始结果整理成适合接口返回的公开结果。
    默认隐藏 intermediate 大数组。
    """
    serializable = _to_builtin(raw_result)
    unit = _resolve_unit(serializable)
    svr_prediction = float(serializable["svr_prediction"])
    rf_prediction = float(serializable["rf_prediction"])
    fusion_prediction = float(serializable["fusion_prediction"])
    model_disagreement = calculate_model_disagreement(
        svr_prediction=svr_prediction,
        rf_prediction=rf_prediction,
        fusion_prediction=fusion_prediction,
    )
    expected_value = parse_expected_value_from_filename(serializable.get("sample_file"))
    prediction_error = None if expected_value is None else float(fusion_prediction - expected_value)

    figures = serializable.get("figures", {}) or {}
    pipeline = serializable.get("pipeline", []) or []
    confidence = serializable.get("confidence", {}) or {}
    result = {
        "model_version": serializable.get("model_version") or _predictor_model_version,
        "sample_file": serializable.get("sample_file"),
        "sample_path": serializable.get("sample_path"),
        "svr_prediction": svr_prediction,
        "rf_prediction": rf_prediction,
        "fusion_prediction": fusion_prediction,
        "unit": unit,
        "confidence": confidence,
        "model_disagreement": model_disagreement,
        "expected_value_from_filename": expected_value,
        "prediction_error_from_filename": prediction_error,
        "result_summary": {
            "sample_file": serializable.get("sample_file"),
            "prediction_text": f"融合预测结果为 {fusion_prediction:.4f} {unit}",
            "svr_text": f"SVR 预测值为 {svr_prediction:.4f} {unit}",
            "rf_text": f"RF 预测值为 {rf_prediction:.4f} {unit}",
            "confidence_text": confidence.get("status", ""),
            "model_disagreement_text": model_disagreement["message"],
            "figure_count": len(figures),
            "pipeline_text": " → ".join(pipeline),
            "expected_value_from_filename": expected_value,
            "prediction_error_from_filename": prediction_error,
        },
        "figures": figures,
        "pipeline": pipeline,
    }

    if include_intermediate and "intermediate" in serializable:
        result["intermediate"] = serializable["intermediate"]

    return result


def predict_methanol(file_path: Path, include_intermediate: bool = False) -> dict:
    """调用核心预测器完成甲醇含量推理，并整理为接口公开结果。"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"待预测文件不存在: {path}")
    if path.suffix.lower() != ".csv":
        raise ValueError("只支持 CSV 光谱文件。")

    predictor = get_predictor()
    try:
        result = predictor.predict(path)
    except FileNotFoundError:
        raise
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"执行甲醇预测失败: {exc}") from exc

    return build_public_prediction_result(result, include_intermediate=include_intermediate)
