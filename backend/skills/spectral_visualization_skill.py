"""光谱可视化大 Skill。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.services.methanol_service import get_predictor
from backend.services.model_registry_service import ModelRegistryService
from raman_core.methanol.preprocess import interpolate_to_axis, preprocess_for_als_branch, preprocess_for_cdae_branch, correct_by_baseline
from raman_core.methanol.spectrum_io import read_csv_spectrum
from raman_core.methanol.visualization import save_stage_figures

from .base import BaseSkill, SkillResult


class SpectralVisualizationSkill(BaseSkill):
    """聚合图谱生成相关能力。"""

    name = "spectral_visualization_skill"
    display_name = "光谱可视化"
    description = "负责生成拉曼光谱图、预处理前后对比图、基线校正图、预测结果图等。"
    category = "可视化绘图"
    requires_file = False
    supported_file_types = ["csv"]
    usage = "在上传 CSV 后，可以让 Agent 输出原始图谱和预处理对比图。"

    def __init__(self) -> None:
        self._registry_service = ModelRegistryService()
        reason = self._visualization_unavailable_reason()
        self.available = reason == ""
        self.unavailable_reason = reason
        status = "ready" if reason == "" else "unavailable"
        self.actions = [
            {
                "name": "plot_raw_spectrum",
                "display_name": "原始光谱图",
                "description": "绘制统一波数轴后的原始光谱图。",
                "enabled": True,
                "available": reason == "",
                "status": status,
                "unavailable_reason": reason,
            },
            {
                "name": "plot_preprocessed_spectrum",
                "display_name": "预处理对比图",
                "description": "绘制预处理前后的光谱图。",
                "enabled": True,
                "available": reason == "",
                "status": status,
                "unavailable_reason": reason,
            },
            {
                "name": "plot_baseline_comparison",
                "display_name": "基线对比图",
                "description": "绘制基线估计与扣除效果图。",
                "enabled": True,
                "available": reason == "",
                "status": status,
                "unavailable_reason": reason,
            },
            {
                "name": "plot_prediction_result",
                "display_name": "预测结果图",
                "description": "输出当前预测链路生成的四阶段图谱。",
                "enabled": True,
                "available": reason == "",
                "status": status,
                "unavailable_reason": reason,
            },
        ]

    def _visualization_unavailable_reason(self) -> str:
        """只做轻量工件检查，避免 Skills 接口阻塞在模型加载阶段。"""
        artifact_check = self._registry_service.check_model_artifacts()
        if artifact_check.get("success"):
            return ""

        missing_files = ((artifact_check.get("data") or {}).get("missing_files") or [])
        if missing_files:
            missing_names = [str(item.get("name") or item.get("path") or "未知文件") for item in missing_files]
            return "模型工件缺失：" + "、".join(missing_names)

        error_message = str(artifact_check.get("error_message") or "").strip()
        return error_message or "模型工件检查失败。"

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "plot_prediction_result")
        file_path = str(kwargs.get("file_path") or "").strip()
        if not file_path:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="绘图需要先上传 CSV 文件。",
                errors=["缺少 file_path 参数。"],
            )

        try:
            predictor = get_predictor()
            raw_x, raw_y = read_csv_spectrum(Path(file_path))
            aligned_y = interpolate_to_axis(raw_x, raw_y, predictor.common_axis)
            sg_window = int(predictor.config["sg_window"])
            sg_order = int(predictor.config["sg_order"])
            als_processed, _, _ = preprocess_for_als_branch(aligned_y, sg_window=sg_window, sg_order=sg_order)
            denoised_als = predictor._run_cdae_single(predictor.cdae_display_model, als_processed)
            reg_processed = preprocess_for_cdae_branch(aligned_y, sg_window=sg_window, sg_order=sg_order)
            denoised_reg = predictor._run_cdae_single(predictor.cdae_reg_model, reg_processed)
            estimated_baseline = predictor._run_caeplus_single(denoised_reg)
            corrected = correct_by_baseline(denoised_reg, estimated_baseline)
            figures = save_stage_figures(
                sample_name=Path(file_path).name,
                common_axis=predictor.common_axis,
                raw=aligned_y,
                preprocessed=als_processed,
                cdae=denoised_als,
                final=corrected,
                titles=predictor.config,
            )
            return SkillResult(
                success=True,
                skill_name=self.name,
                action_name=action_name,
                summary="光谱图已生成。",
                data={"figures": figures},
                plots=list(figures.values()),
            )
        except Exception as exc:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="光谱可视化失败。",
                errors=[str(exc)],
            )
