"""甲醇预测 Skill。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.services.methanol_service import predict_methanol
from backend.services.model_registry_service import ModelRegistryService

from .base import BaseSkill, SkillResult


class RamanMethanolSkill(BaseSkill):
    """调用现有甲醇预测算法并返回统一结果。"""

    name = "methanol_prediction_skill"
    description = "分析 Raman CSV 文件并返回甲醇浓度预测结果。"

    def __init__(self) -> None:
        self._registry_service = ModelRegistryService()

    def run(self, **kwargs: Any) -> SkillResult:
        file_path = str(kwargs.get("file_path") or "").strip()
        metadata = dict(kwargs.get("metadata") or {})
        include_intermediate = bool(kwargs.get("include_intermediate", False))

        if not file_path:
            return SkillResult(
                success=False,
                skill_name=self.name,
                summary="未提供待分析文件路径。",
                errors=["缺少 file_path 参数。"],
            )

        try:
            result = predict_methanol(Path(file_path), include_intermediate=include_intermediate)
        except Exception as exc:
            return SkillResult(
                success=False,
                skill_name=self.name,
                summary="甲醇预测失败。",
                errors=[str(exc)],
            )

        model_response = self._registry_service.get_default_model()
        model_info = dict(model_response.get("data") or {}) if model_response.get("success") else {}
        predicted_value = result.get("fusion_prediction")
        unit = result.get("unit", "")
        summary = f"甲醇浓度预测完成，融合预测值为 {float(predicted_value):.4f} {unit}。"

        plots = list((result.get("figures") or {}).values())
        return SkillResult(
            success=True,
            skill_name=self.name,
            summary=summary,
            data={
                "file_path": file_path,
                "metadata": metadata,
                "predicted_value": predicted_value,
                "unit": unit,
                "model_version": result.get("model_version") or model_info.get("model_version"),
                "model_name": model_info.get("model_name"),
                "svr_prediction": result.get("svr_prediction"),
                "rf_prediction": result.get("rf_prediction"),
                "confidence": result.get("confidence", {}) or {},
                "model_disagreement": result.get("model_disagreement", {}) or {},
                "pipeline": result.get("pipeline", []) or [],
                "figures": result.get("figures", {}) or {},
                "result": result,
            },
            plots=[str(item) for item in plots if item],
        )
