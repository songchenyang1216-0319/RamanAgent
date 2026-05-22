"""甲醇光谱分析大 Skill。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agent.tools.report_tool import explain_result_tool
from backend.services.model_registry_service import ModelRegistryService

from .base import BaseSkill, SkillResult
from .raman_methanol_skill import RamanMethanolSkill
from .spectrum_loader_skill import SpectrumLoaderSkill


class MethanolAnalysisSkill(BaseSkill):
    """聚合甲醇预测相关能力。"""

    name = "methanol_analysis_skill"
    display_name = "甲醇光谱分析"
    description = "负责甲醇拉曼光谱的模型预测和结果解释，包括甲醇浓度预测、模型调用、结果汇总和关键指标输出。"
    category = "模型预测"
    requires_file = True
    supported_file_types = ["csv"]
    usage = "点击聊天框左侧 + 上传 CSV 文件，然后发送甲醇光谱分析请求。"

    def __init__(self) -> None:
        self._prediction_skill = RamanMethanolSkill()
        self._loader_skill = SpectrumLoaderSkill()
        self._registry_service = ModelRegistryService()
        self.actions = [
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
                "display_name": "结果解释",
                "description": "对预测结果做中文说明。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "get_model_info",
                "display_name": "查看模型信息",
                "description": "返回当前甲醇模型版本和基本信息。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "check_prediction_input",
                "display_name": "检查预测输入",
                "description": "在执行预测前检查输入文件是否满足最基本要求。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
        ]

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "predict_methanol_concentration")
        file_path = str(kwargs.get("file_path") or "").strip()

        if action_name == "get_model_info":
            result = self._registry_service.get_default_model()
            if not result.get("success"):
                return SkillResult(
                    success=False,
                    skill_name=self.name,
                    action_name=action_name,
                    summary="获取模型信息失败。",
                    errors=[str(result.get("error_message") or "未知错误")],
                )
            return SkillResult(
                success=True,
                skill_name=self.name,
                action_name=action_name,
                summary="当前模型信息已获取。",
                data=dict(result.get("data") or {}),
            )

        if not file_path:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="甲醇光谱分析需要先上传 CSV 文件。",
                errors=["缺少 file_path 参数。"],
            )

        if action_name == "check_prediction_input":
            return self._loader_skill.run(file_path=file_path, action_name="validate_csv")

        prediction_result = self._prediction_skill.run(
            file_path=file_path,
            metadata=kwargs.get("metadata") or {},
            include_intermediate=bool(kwargs.get("include_intermediate", False)),
        )
        if not prediction_result.success:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="甲醇光谱分析失败。",
                errors=list(prediction_result.errors),
            )

        if action_name == "predict_methanol_concentration":
            return SkillResult(
                success=True,
                skill_name=self.name,
                action_name=action_name,
                summary=prediction_result.summary,
                data=dict(prediction_result.data or {}),
                plots=list(prediction_result.plots),
            )

        if action_name == "explain_prediction":
            result = dict(prediction_result.data.get("result") or {})
            explanation = explain_result_tool(result=result)
            return SkillResult(
                success=bool(explanation.get("success")),
                skill_name=self.name,
                action_name=action_name,
                summary="预测结果解释已生成。" if explanation.get("explanation") else "预测结果解释生成失败。",
                data={
                    "result": result,
                    "explanation": explanation.get("explanation"),
                    "error_message": explanation.get("error_message"),
                },
                errors=[str(explanation.get("error_message"))] if explanation.get("success") is False and explanation.get("error_message") else [],
            )

        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary="当前 action 未实现。",
            errors=[f"未识别的 action: {action_name}"],
        )
