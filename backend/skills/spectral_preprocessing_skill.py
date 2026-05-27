"""光谱预处理大 Skill。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.services.methanol_service import get_predictor
from backend.services.model_registry_service import ModelRegistryService
from backend.utils.plot_style import apply_chinese_plot_style
from raman_core.methanol.preprocess import (
    apply_sg_smoothing,
    baseline_als,
    correct_by_baseline,
    interpolate_to_axis,
    normalize_01,
    preprocess_for_als_branch,
    preprocess_for_cdae_branch,
)
from raman_core.methanol.config import PREPROCESSED_DIR, PLOT_DIR, PROJECT_ROOT, ensure_dirs
from raman_core.methanol.spectrum_io import read_csv_spectrum

from .base import BaseSkill, SkillResult


class SpectralPreprocessingSkill(BaseSkill):
    """对外聚合光谱预处理相关能力。"""

    name = "spectral_preprocessing_skill"
    display_name = "光谱预处理"
    description = "负责拉曼光谱预处理，包括平滑、归一化、去噪、基线校正、重采样等处理流程。"
    category = "光谱预处理"
    requires_file = True
    supported_file_types = ["csv"]
    usage = "上传 CSV 后，可以让 Agent 对光谱进行平滑、去噪、基线校正和归一化处理。"

    def __init__(self) -> None:
        self._registry_service = ModelRegistryService()
        self.available = True
        self.unavailable_reason = ""
        model_reason = self._model_artifact_unavailable_reason()
        self.actions = [
            {
                "name": "sg_smoothing",
                "display_name": "SG 平滑",
                "description": "使用 Savitzky-Golay 方法对光谱进行平滑处理。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "normalization",
                "display_name": "归一化",
                "description": "对光谱强度做 0-1 归一化。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "als_baseline_correction",
                "display_name": "ALS 基线校正",
                "description": "使用 ALS 方法估计并扣除拉曼光谱基线。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "baseline_subtraction",
                "display_name": "基线扣除",
                "description": "从光谱中扣除估计基线并输出校正后结果。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "cdae_denoise",
                "display_name": "CDAE 去噪",
                "description": "使用卷积去噪自编码器进行光谱去噪。",
                "enabled": True,
                "available": model_reason == "",
                "status": "ready" if model_reason == "" else "unavailable",
                "unavailable_reason": model_reason,
            },
            {
                "name": "cae_baseline_prediction",
                "display_name": "CAE 基线预测",
                "description": "使用 CAE+ 模型预测光谱基线背景。",
                "enabled": True,
                "available": model_reason == "",
                "status": "ready" if model_reason == "" else "unavailable",
                "unavailable_reason": model_reason,
            },
            {
                "name": "resample_wavenumber_axis",
                "display_name": "统一波数轴",
                "description": "把输入光谱插值到统一波数坐标轴。",
                "enabled": True,
                "available": model_reason == "",
                "status": "ready" if model_reason == "" else "unavailable",
                "unavailable_reason": model_reason,
            },
            {
                "name": "full_preprocess_pipeline",
                "display_name": "完整预处理流程",
                "description": "执行统一波数轴、平滑、ALS 去基线、归一化、CDAE 去噪和 CAE+ 基线估计。",
                "enabled": True,
                "available": model_reason == "",
                "status": "ready" if model_reason == "" else "unavailable",
                "unavailable_reason": model_reason,
            },
        ]
        if model_reason:
            self.available = True
            self.unavailable_reason = ""

    def _model_artifact_unavailable_reason(self) -> str:
        """只检查模型工件，不在 Skills 元数据阶段触发真实模型加载。"""
        artifact_check = self._registry_service.check_model_artifacts()
        if artifact_check.get("success"):
            return ""

        missing_files = ((artifact_check.get("data") or {}).get("missing_files") or [])
        if missing_files:
            missing_names = [str(item.get("name") or item.get("path") or "未知文件") for item in missing_files]
            return "模型工件缺失：" + "、".join(missing_names)

        error_message = str(artifact_check.get("error_message") or "").strip()
        return error_message or "模型工件检查失败。"

    def _load_arrays(self, file_path: str) -> tuple[np.ndarray, np.ndarray]:
        x_arr, y_arr = read_csv_spectrum(Path(file_path))
        return x_arr.astype(float), y_arr.astype(float)

    def _build_web_url(self, path: Path) -> str:
        return "/" + str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")

    def _save_processed_csv(self, axis: np.ndarray, values: np.ndarray, source_path: Path, action_name: str) -> tuple[str, str]:
        ensure_dirs()
        PREPROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        output_path = PREPROCESSED_DIR / f"{source_path.stem}_{action_name}.csv"
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["wavenumber", "intensity"])
            for x_value, y_value in zip(axis, values):
                writer.writerow([float(x_value), float(y_value)])
        return str(output_path.relative_to(PROJECT_ROOT)).replace("\\", "/"), self._build_web_url(output_path)

    def _save_comparison_plot(
        self,
        raw_axis: np.ndarray,
        raw_values: np.ndarray,
        processed_axis: np.ndarray,
        processed_values: np.ndarray,
        source_path: Path,
        action_name: str,
    ) -> tuple[str, str]:
        ensure_dirs()
        PLOT_DIR.mkdir(parents=True, exist_ok=True)
        plot_path = PLOT_DIR / f"{source_path.stem}_{action_name}_comparison.png"
        apply_chinese_plot_style()
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(raw_axis, raw_values, label="Raw", alpha=0.72)
        ax.plot(processed_axis, processed_values, label="Processed", alpha=0.92)
        ax.set_xlabel("Wavenumber")
        ax.set_ylabel("Intensity")
        ax.set_title("Preprocessing Comparison")
        ax.grid(alpha=0.2)
        ax.legend()
        fig.tight_layout()
        fig.savefig(plot_path, dpi=150)
        plt.close(fig)
        return str(plot_path.relative_to(PROJECT_ROOT)).replace("\\", "/"), self._build_web_url(plot_path)

    def _save_single_plot(
        self,
        axis: np.ndarray,
        values: np.ndarray,
        source_path: Path,
        suffix: str,
        title: str,
    ) -> tuple[str, str]:
        ensure_dirs()
        PLOT_DIR.mkdir(parents=True, exist_ok=True)
        plot_path = PLOT_DIR / f"{source_path.stem}_{suffix}.png"
        apply_chinese_plot_style()
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(axis, values, linewidth=1.2)
        ax.set_xlabel("Wavenumber")
        ax.set_ylabel("Intensity")
        ax.set_title(title)
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(plot_path, dpi=150)
        plt.close(fig)
        return str(plot_path.relative_to(PROJECT_ROOT)).replace("\\", "/"), self._build_web_url(plot_path)

    def _required_actions_for(self, action_name: str) -> list[str]:
        if action_name == "full_preprocess_pipeline":
            return [
                "sg_smoothing",
                "normalization",
                "als_baseline_correction",
                "cdae_denoise",
                "cae_baseline_prediction",
                "resample_wavenumber_axis",
            ]
        if action_name == "cdae_denoise":
            return ["cdae_denoise"]
        if action_name == "cae_baseline_prediction":
            return ["cae_baseline_prediction"]
        if action_name == "resample_wavenumber_axis":
            return ["resample_wavenumber_axis"]
        if action_name in {"als_baseline_correction", "baseline_subtraction"}:
            return ["sg_smoothing", "als_baseline_correction"]
        if action_name == "normalization":
            return ["normalization"]
        if action_name == "sg_smoothing":
            return ["sg_smoothing"]
        return []

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "full_preprocess_pipeline")
        file_path = str(kwargs.get("file_path") or "").strip()
        action_enabled_map = dict(kwargs.get("action_enabled_map") or {})
        if not file_path:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="预处理需要先提供 CSV 文件。",
                errors=["缺少 file_path 参数。"],
            )

        disabled_dependencies = [
            action
            for action in self._required_actions_for(action_name)
            if action_enabled_map.get(action) is False
        ]
        if disabled_dependencies:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="光谱预处理失败。",
                errors=[f"预处理依赖的子能力已禁用：{'、'.join(disabled_dependencies)}"],
            )

        try:
            x_arr, y_arr = self._load_arrays(file_path)
        except Exception as exc:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="光谱读取失败，无法执行预处理。",
                errors=[str(exc)],
            )

        sg_window = int(kwargs.get("sg_window") or 11)
        sg_order = int(kwargs.get("sg_order") or 2)

        try:
            if action_name == "sg_smoothing":
                smoothed = apply_sg_smoothing(y_arr, sg_window=sg_window, sg_order=sg_order)
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="SG 平滑完成。",
                    data={"smoothed_y": smoothed.tolist(), "points": len(smoothed)},
                )

            if action_name == "normalization":
                normalized = normalize_01(y_arr)
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="归一化完成。",
                    data={"normalized_y": normalized.tolist(), "points": len(normalized)},
                )

            if action_name in {"als_baseline_correction", "baseline_subtraction"}:
                smoothed = apply_sg_smoothing(y_arr, sg_window=sg_window, sg_order=sg_order)
                baseline = baseline_als(smoothed)
                corrected = np.clip(smoothed - baseline, 0.0, None)
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="ALS 基线校正完成。",
                    data={
                        "baseline_y": baseline.tolist(),
                        "corrected_y": corrected.tolist(),
                        "normalized_corrected_y": normalize_01(corrected).tolist(),
                    },
                )

            predictor = get_predictor()
            common_axis = predictor.common_axis
            aligned_y = interpolate_to_axis(x_arr, y_arr, common_axis)

            if action_name == "resample_wavenumber_axis":
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="统一波数轴完成。",
                    data={"common_axis": common_axis.tolist(), "aligned_y": aligned_y.tolist()},
                )

            reg_processed = preprocess_for_cdae_branch(aligned_y, sg_window=sg_window, sg_order=sg_order)
            als_processed, smoothed_y, baseline_y = preprocess_for_als_branch(
                aligned_y,
                sg_window=sg_window,
                sg_order=sg_order,
            )

            if action_name == "cdae_denoise":
                denoised_reg = predictor._run_cdae_single(predictor.cdae_reg_model, reg_processed)
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="CDAE 去噪完成。",
                    data={"denoised_reg_y": denoised_reg.tolist()},
                )

            if action_name == "cae_baseline_prediction":
                denoised_reg = predictor._run_cdae_single(predictor.cdae_reg_model, reg_processed)
                estimated_baseline = predictor._run_caeplus_single(denoised_reg)
                corrected = correct_by_baseline(denoised_reg, estimated_baseline)
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="CAE+ 基线预测完成。",
                    data={
                        "estimated_baseline": estimated_baseline.tolist(),
                        "corrected_y": corrected.tolist(),
                    },
                )

            if action_name == "full_preprocess_pipeline":
                denoised_als = predictor._run_cdae_single(predictor.cdae_display_model, als_processed)
                denoised_reg = predictor._run_cdae_single(predictor.cdae_reg_model, reg_processed)
                estimated_baseline = predictor._run_caeplus_single(denoised_reg)
                corrected = correct_by_baseline(denoised_reg, estimated_baseline)
                source_path = Path(file_path)
                output_csv_path, output_csv_url = self._save_processed_csv(common_axis, corrected, source_path, action_name)
                raw_plot_path, raw_plot_url = self._save_single_plot(
                    x_arr,
                    y_arr,
                    source_path,
                    f"{action_name}_raw",
                    "原始光谱图",
                )
                processed_plot_path, processed_plot_url = self._save_single_plot(
                    common_axis,
                    corrected,
                    source_path,
                    f"{action_name}_processed",
                    "预处理后光谱图",
                )
                plot_path, plot_url = self._save_comparison_plot(x_arr, y_arr, common_axis, corrected, source_path, action_name)
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="完整预处理流程执行完成。",
                    data={
                        "result_kind": "preprocessing",
                        "common_axis": common_axis.tolist(),
                        "aligned_y": aligned_y.tolist(),
                        "smoothed_y": smoothed_y.tolist(),
                        "baseline_y": baseline_y.tolist(),
                        "als_processed_y": als_processed.tolist(),
                        "denoised_als_y": denoised_als.tolist(),
                        "reg_processed_y": reg_processed.tolist(),
                        "denoised_reg_y": denoised_reg.tolist(),
                        "estimated_baseline": estimated_baseline.tolist(),
                        "corrected_y": corrected.tolist(),
                        "steps": [
                            "CSV 文件读取完成",
                            "统一波数轴完成",
                            "SG 平滑完成",
                            "ALS 基线校正完成",
                            "归一化完成",
                            "CDAE 去噪完成",
                            "CAE+ 基线预测完成",
                        ],
                        "input_file": str(source_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                        "output_file": output_csv_path,
                        "output_file_url": output_csv_url,
                        "plots": [
                            {
                                "title": "原始光谱图",
                                "path": raw_plot_path,
                                "url": raw_plot_url,
                                "kind": "raw",
                                "description": "处理前的原始光谱，用于观察原始峰形和噪声水平。",
                            },
                            {
                                "title": "预处理后光谱图",
                                "path": processed_plot_path,
                                "url": processed_plot_url,
                                "kind": "processed",
                                "description": "完成统一波数轴、平滑、去基线和修正后的光谱。",
                            },
                            {
                                "title": "预处理前后叠加对比图",
                                "path": plot_path,
                                "url": plot_url,
                                "kind": "overlay",
                                "description": "将处理前后曲线放在同一张图中辅助比较形状变化。",
                            }
                        ],
                        "metrics": {
                            "points": int(len(corrected)),
                            "wavenumber_min": float(np.min(common_axis)),
                            "wavenumber_max": float(np.max(common_axis)),
                            "intensity_min": float(np.min(corrected)),
                            "intensity_max": float(np.max(corrected)),
                        },
                        "warnings": list(kwargs.get("warnings") or []),
                    },
                    plots=[raw_plot_url, processed_plot_url, plot_url],
                )
        except Exception as exc:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="光谱预处理失败。",
                errors=[str(exc)],
            )

        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary="当前 action 未实现。",
            errors=[f"未识别的 action: {action_name}"],
        )
