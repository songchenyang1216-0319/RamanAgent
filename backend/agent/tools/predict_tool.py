"""甲醇预测工具。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from backend.services.methanol_service import predict_methanol


logger = logging.getLogger(__name__)


def _pick_first(data: dict[str, Any], keys: list[str]) -> Any:
    """按候选字段顺序返回第一个非空值。"""
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return None


def normalize_prediction_result(raw_result: dict | None) -> dict | None:
    """将不同风格的预测返回统一成 Agent 对外结构。"""
    if not raw_result or not isinstance(raw_result, dict):
        return None

    final_prediction = _pick_first(
        raw_result,
        ["final_prediction", "fused_prediction", "fusion_prediction", "prediction", "concentration"],
    )
    svr_prediction = _pick_first(raw_result, ["svr_prediction", "svr"])
    rf_prediction = _pick_first(raw_result, ["rf_prediction", "rf"])
    figure_paths = _pick_first(raw_result, ["figure_paths", "figures", "plot_paths"]) or {}

    if final_prediction is None or svr_prediction is None or rf_prediction is None:
        return None

    warnings = []
    if not figure_paths:
        warnings.append("预测完成，但未返回图像路径")

    return {
        "sample_file": raw_result.get("sample_file"),
        "sample_path": raw_result.get("sample_path"),
        "unit": raw_result.get("unit"),
        "final_prediction": float(final_prediction),
        "svr_prediction": float(svr_prediction),
        "rf_prediction": float(rf_prediction),
        "model_disagreement": raw_result.get("model_disagreement", {}) or {},
        "confidence": raw_result.get("confidence", {}) or {},
        "figure_paths": figure_paths if isinstance(figure_paths, dict) else {},
        "warnings": warnings,
        "pipeline": raw_result.get("pipeline", []) or [],
    }


def predict_methanol_tool(file_path: str | Path, debug: bool = False) -> dict:
    """封装甲醇预测调用，供 Agent 工具编排使用。"""
    try:
        result = predict_methanol(Path(file_path), include_intermediate=debug)
    except FileNotFoundError as exc:
        return {"success": False, "error_message": str(exc), "warnings": ["待分析文件不存在。"]}
    except ValueError as exc:
        return {"success": False, "error_message": str(exc), "warnings": ["上传的文件格式不正确。"]}
    except RuntimeError as exc:
        return {"success": False, "error_message": str(exc), "warnings": ["预测流程执行失败。"]}
    except Exception as exc:
        return {"success": False, "error_message": f"执行预测时出现未预期错误: {exc}", "warnings": []}

    raw_keys = sorted(result.keys()) if isinstance(result, dict) else []
    logger.info("predict_methanol_tool raw result keys: %s", raw_keys)
    normalized_result = normalize_prediction_result(result)
    if normalized_result is None:
        return {
            "success": False,
            "error_message": "预测服务没有返回有效结果",
            "raw_keys": raw_keys,
            "warnings": ["预测流程返回内容不完整。"],
        }

    return {
        "success": True,
        "result": normalized_result,
        "raw_result": result,
        "final_prediction": normalized_result.get("final_prediction"),
        "svr_prediction": normalized_result.get("svr_prediction"),
        "rf_prediction": normalized_result.get("rf_prediction"),
        "model_disagreement": normalized_result.get("model_disagreement"),
        "confidence": normalized_result.get("confidence"),
        "figure_paths": normalized_result.get("figure_paths", {}),
        "report_path": None,
        "warnings": normalized_result.get("warnings", []),
        "raw_keys": raw_keys,
    }
