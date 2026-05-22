"""实验报告生成大 Skill。"""

from __future__ import annotations

from typing import Any

from backend.agent.tools.report_tool import generate_report_tool

from .base import BaseSkill, SkillResult


class ExperimentReportSkill(BaseSkill):
    """聚合报告相关能力。"""

    name = "experiment_report_skill"
    display_name = "实验报告生成"
    description = "根据光谱分析结果、样品信息、模型预测结果和图像结果，生成结构化实验报告。"
    category = "报告生成"
    requires_file = False
    supported_file_types: list[str] = []
    usage = "在已有分析结果后，可以让 Agent 输出 Markdown/HTML 报告。"
    actions = [
        {
            "name": "generate_summary",
            "display_name": "生成摘要",
            "description": "根据已有分析结果生成简要实验摘要。",
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        },
        {
            "name": "generate_markdown_report",
            "display_name": "生成 Markdown 报告",
            "description": "根据预测结果生成 Markdown/HTML 报告。",
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        },
        {
            "name": "generate_experiment_record",
            "display_name": "生成实验记录",
            "description": "整理样品信息和结果为实验记录。",
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        },
        {
            "name": "export_report",
            "display_name": "导出报告",
            "description": "导出已生成的报告文件路径。",
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        },
    ]

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "generate_markdown_report")
        result = dict(kwargs.get("result") or {})
        if not result:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="生成报告需要已有分析结果。",
                errors=["缺少 result 参数。"],
            )

        if action_name == "generate_summary":
            summary = (result.get("result_summary") or {}).get("prediction_text") or "当前没有可用摘要。"
            return SkillResult(
                success=True,
                skill_name=self.name,
                action_name=action_name,
                summary="实验摘要已生成。",
                data={"summary": summary},
            )

        report_result = generate_report_tool(
            result=result,
            llm_explanation=kwargs.get("llm_explanation"),
            professional_analysis=kwargs.get("professional_analysis"),
            model_info=kwargs.get("model_info"),
            experiment_metadata=kwargs.get("experiment_metadata"),
        )
        if not report_result.get("success"):
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="实验报告生成失败。",
                errors=[str(report_result.get("error_message") or "未知错误")],
            )

        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name=action_name,
            summary="实验报告已生成。",
            data=dict(report_result),
        )
