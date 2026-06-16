from __future__ import annotations

from typing import Any

from backend.raman_pipeline.algorithm_registry import get_algorithm_registry
from backend.raman_pipeline.algorithm_schema import RamanPipelineError
from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
from backend.raman_pipeline.pipeline_schema import PipelineRequest, PipelineStep
from backend.raman_pipeline.pipeline_store import PipelineStore

from .base import BaseSkill, SkillResult
from .experiment_report_skill import ExperimentReportSkill
from .methanol_analysis_skill import MethanolAnalysisSkill
from .spectral_file_skill import SpectralFileSkill
from .spectral_preprocessing_skill import SpectralPreprocessingSkill
from .spectral_visualization_skill import SpectralVisualizationSkill


def _clean_skill_kwargs(kwargs: dict | None) -> dict:
    """转发给子 Skill 前移除会造成重复绑定的公共参数。"""
    clean_kwargs = dict(kwargs or {})
    clean_kwargs.pop("action_name", None)
    return clean_kwargs


class RamanSpectroscopySkill(BaseSkill):
    """把 Raman 领域能力聚合成一个对外 Skill。"""

    name = "raman_spectroscopy_skill"
    display_name = "Raman 光谱处理"
    description = "聚合 Raman 光谱读取、校验、预处理、可视化、甲醇浓度预测与实验报告生成能力。"
    category = "领域技能"
    requires_file = True
    supported_file_types = ["csv"]
    usage = "上传 Raman CSV 后，可以通过这个 Skill 完成读取、预处理、预测、绘图和报告输出。"

    def __init__(self) -> None:
        self._file_skill = SpectralFileSkill()
        self._preprocess_skill = SpectralPreprocessingSkill()
        self._analysis_skill = MethanolAnalysisSkill()
        self._visualization_skill = SpectralVisualizationSkill()
        self._report_skill = ExperimentReportSkill()
        self._pipeline_store = PipelineStore()
        self._pipeline_runner = RamanPipelineRunner(store=self._pipeline_store)
        self.actions = [
            {
                "name": "load_csv",
                "display_name": "读取光谱 CSV",
                "description": "读取 Raman 光谱 CSV，并返回基础数组结果。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "validate_csv",
                "display_name": "校验光谱 CSV",
                "description": "检查文件后缀、列数、空值和有效点数。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "inspect_spectrum",
                "display_name": "检查光谱范围",
                "description": "统计波数范围、强度范围和点数。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "extract_metadata",
                "display_name": "提取光谱元数据",
                "description": "从 CSV 中提取光谱基础信息，供后续分析使用。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "full_preprocess_pipeline",
                "display_name": "完整预处理流程",
                "description": "执行统一波数轴、平滑、ALS 去基线、归一化、CDAE 去噪和 CAE+ 基线估计。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "plot_prediction_result",
                "display_name": "绘制光谱图",
                "description": "输出原始光谱、预处理对比和预测链路图谱。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "predict_methanol_concentration",
                "display_name": "甲醇浓度预测",
                "description": "调用甲醇回归模型预测甲醇浓度。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "explain_prediction",
                "display_name": "解释预测结果",
                "description": "对预测结果做中文说明。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "get_model_info",
                "display_name": "查看 Raman 模型信息",
                "description": "返回当前 Raman/甲醇模型版本和基本信息。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "generate_markdown_report",
                "display_name": "生成实验报告",
                "description": "根据预测结果生成 Markdown/HTML 报告。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "list_algorithms",
                "display_name": "列出 Raman 算法库",
                "description": "返回新 Raman Pipeline 注册表中的算法元数据。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "validate_pipeline",
                "display_name": "校验自定义 Pipeline",
                "description": "校验 Pipeline 步骤、算法可用性和关键参数。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "run_custom_pipeline",
                "display_name": "运行自定义 Pipeline",
                "description": "按用户配置的算法步骤运行 Raman Pipeline。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "run_template_pipeline",
                "display_name": "运行模板 Pipeline",
                "description": "按内置模板运行 Raman Pipeline。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "list_pipeline_templates",
                "display_name": "列出 Pipeline 模板",
                "description": "返回 basic_preprocessing、quality_check、peak_analysis 等内置模板。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "get_pipeline_history",
                "display_name": "查看 Pipeline 历史",
                "description": "查看最近 Raman Pipeline 运行记录。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "compare_pipelines",
                "display_name": "对比多个 Pipeline",
                "description": "在同一 CSV 上运行多个模板或自定义 Pipeline 并汇总对比结果。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
        ]

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "predict_methanol_concentration")
        clean_kwargs = _clean_skill_kwargs(kwargs)

        if action_name in {
            "list_algorithms",
            "validate_pipeline",
            "run_custom_pipeline",
            "run_template_pipeline",
            "list_pipeline_templates",
            "get_pipeline_history",
            "compare_pipelines",
        }:
            return self._run_pipeline_action(action_name, **clean_kwargs)

        if action_name in {"load_csv", "validate_csv", "inspect_spectrum", "extract_metadata"}:
            result = self._file_skill.run(action_name=action_name, **clean_kwargs)
            return self._normalize_result(result, action_name)

        if action_name in {
            "sg_smoothing",
            "normalization",
            "als_baseline_correction",
            "baseline_subtraction",
            "cdae_denoise",
            "cae_baseline_prediction",
            "resample_wavenumber_axis",
            "full_preprocess_pipeline",
        }:
            result = self._preprocess_skill.run(action_name=action_name, **clean_kwargs)
            return self._normalize_result(result, action_name)

        if action_name in {
            "plot_raw_spectrum",
            "plot_preprocessed_spectrum",
            "plot_baseline_comparison",
            "plot_prediction_result",
        }:
            result = self._visualization_skill.run(action_name=action_name, **clean_kwargs)
            return self._normalize_result(result, action_name)

        if action_name in {
            "predict_methanol_concentration",
            "explain_prediction",
            "get_model_info",
            "check_prediction_input",
        }:
            result = self._analysis_skill.run(action_name=action_name, **clean_kwargs)
            return self._normalize_result(result, action_name)

        if action_name in {
            "generate_summary",
            "generate_markdown_report",
            "generate_experiment_record",
            "export_report",
        }:
            result = self._report_skill.run(action_name=action_name, **clean_kwargs)
            return self._normalize_result(result, action_name)

        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary="当前 action 未实现。",
            errors=[f"未识别的 action: {action_name}"],
        )

    def _build_pipeline_request(self, **kwargs: Any) -> PipelineRequest:
        steps = kwargs.get("steps") or []
        normalized_steps = [
            step if isinstance(step, PipelineStep) else PipelineStep(**dict(step))
            for step in steps
        ]
        return PipelineRequest(
            file_path=str(kwargs.get("file_path") or "").strip() or None,
            template_id=str(kwargs.get("template_id") or "").strip() or None,
            steps=normalized_steps,
            params=dict(kwargs.get("params") or {}),
            sample_name=str(kwargs.get("sample_name") or "").strip() or None,
            save_history=bool(kwargs.get("save_history", True)),
        )

    def _run_pipeline_action(self, action_name: str, **kwargs: Any) -> SkillResult:
        try:
            if action_name == "list_algorithms":
                payload = get_algorithm_registry().to_dict()
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary=f"已返回 {payload.get('total', 0)} 个 Raman Pipeline 算法。",
                    data=payload,
                )

            if action_name == "list_pipeline_templates":
                payload = self._pipeline_store.list_templates()
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary=f"已返回 {payload.get('total', 0)} 个 Raman Pipeline 模板。",
                    data=payload,
                )

            if action_name == "get_pipeline_history":
                payload = self._pipeline_store.list_history(limit=int(kwargs.get("limit") or 30))
                return SkillResult(
                    success=True,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="Raman Pipeline 历史记录已获取。",
                    data=payload,
                )

            if action_name == "validate_pipeline":
                request = self._build_pipeline_request(**kwargs)
                payload = self._pipeline_runner.validate(request)
                return SkillResult(
                    success=bool(payload.get("success")),
                    skill_name=self.name,
                    action_name=action_name,
                    summary="Pipeline 校验通过。" if payload.get("success") else "Pipeline 校验未通过。",
                    data=payload,
                    errors=list(payload.get("errors") or []),
                )

            if action_name == "run_template_pipeline":
                kwargs.setdefault("template_id", "basic_preprocessing")
                request = self._build_pipeline_request(**kwargs)
                result = self._pipeline_runner.run(request)
                return SkillResult(
                    success=result.success,
                    skill_name=self.name,
                    action_name=action_name,
                    summary=result.message,
                    data=result.model_dump(),
                    plots=[str(item.get("url")) for item in result.artifacts if item.get("type") == "image" and item.get("url")],
                    errors=[result.error_message] if result.error_message else [],
                )

            if action_name == "run_custom_pipeline":
                request = self._build_pipeline_request(**kwargs)
                result = self._pipeline_runner.run(request)
                return SkillResult(
                    success=result.success,
                    skill_name=self.name,
                    action_name=action_name,
                    summary=result.message,
                    data=result.model_dump(),
                    plots=[str(item.get("url")) for item in result.artifacts if item.get("type") == "image" and item.get("url")],
                    errors=[result.error_message] if result.error_message else [],
                )

            if action_name == "compare_pipelines":
                file_path = str(kwargs.get("file_path") or "").strip()
                pipeline_items = list(kwargs.get("pipelines") or [])
                if not file_path:
                    raise RamanPipelineError("对比 Pipeline 需要提供 file_path。")
                if not pipeline_items:
                    pipeline_items = [{"template_id": "basic_preprocessing"}, {"template_id": "quality_check"}]
                results = []
                for item in pipeline_items:
                    request = self._build_pipeline_request(file_path=file_path, save_history=False, **dict(item))
                    result = self._pipeline_runner.run(request)
                    results.append(result.model_dump())
                return SkillResult(
                    success=all(bool(item.get("success")) for item in results),
                    skill_name=self.name,
                    action_name=action_name,
                    summary=f"已完成 {len(results)} 个 Pipeline 的对比运行。",
                    data={"results": results},
                    errors=[str(item.get("error_message")) for item in results if item.get("error_message")],
                )
        except Exception as exc:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="Raman Pipeline 操作失败。",
                errors=[str(exc)],
            )

        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary="当前 Pipeline action 未实现。",
            errors=[f"未识别的 Pipeline action: {action_name}"],
        )

    def _normalize_result(self, result: SkillResult, action_name: str) -> SkillResult:
        return SkillResult(
            success=result.success,
            skill_name=self.name,
            action_name=action_name,
            summary=result.summary,
            data=dict(result.data or {}),
            plots=list(result.plots),
            errors=list(result.errors),
        )
