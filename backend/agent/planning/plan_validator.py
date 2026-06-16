"""Validation layer for LLM-generated plans."""

from __future__ import annotations

from typing import Any

from backend.agent.types import NormalizedMessage
from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
from backend.raman_pipeline.pipeline_schema import PipelineRequest, PipelineStep

from .plan_types import LLMPlan, ValidationResult
from .tool_catalog import ToolCatalog


ALLOWED_PLAN_TYPES = {"model", "tool", "skill", "rag", "raman_pipeline", "hybrid", "fallback"}


class PlanValidator:
    def __init__(self, catalog: ToolCatalog | None = None, pipeline_runner: RamanPipelineRunner | None = None) -> None:
        self.catalog = catalog or ToolCatalog()
        self.pipeline_runner = pipeline_runner or RamanPipelineRunner()

    def validate(self, plan: LLMPlan, normalized: NormalizedMessage) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        if plan.plan_type not in ALLOWED_PLAN_TYPES:
            return ValidationResult(
                valid=False,
                plan=plan,
                errors=[f"plan_type 不合法：{plan.plan_type}"],
                fallback_reason=f"LLM Planner 输出了不合法 plan_type：{plan.plan_type}",
                should_fallback=True,
            )

        if plan.plan_type == "fallback" or not plan.steps:
            return ValidationResult(
                valid=False,
                plan=plan,
                errors=["LLM Planner 未生成可执行步骤。"],
                fallback_reason=plan.reason or "LLM Planner 未生成可执行步骤。",
                should_fallback=True,
            )

        if plan.requires_file and not normalized.has_file and not normalized.file_path:
            errors.append("这个计划需要 CSV 或相关文件，但当前请求没有可用文件。请先上传文件后再运行。")

        for step in plan.steps:
            tool = self.catalog.get(step.tool_name)
            if tool is None:
                return ValidationResult(
                    valid=False,
                    plan=plan,
                    errors=[f"tool 不存在：{step.tool_name}"],
                    fallback_reason=f"LLM Planner 输出了不存在的 tool：{step.tool_name}",
                    should_fallback=True,
                )
            action = tool.get_action(step.action_name)
            if action is None:
                return ValidationResult(
                    valid=False,
                    plan=plan,
                    errors=[f"tool/action 不存在：{step.tool_name}.{step.action_name}"],
                    fallback_reason=f"LLM Planner 输出了不存在的 action：{step.tool_name}.{step.action_name}",
                    should_fallback=True,
                )
            if action.requires_file and not normalized.has_file and not normalized.file_path:
                errors.append(f"{tool.display_name}/{action.action_name} 需要先上传文件。")

            if step.tool_name == "raman_pipeline":
                self._validate_raman_pipeline_step(step.action_name, step.args, normalized, errors, warnings)

        return ValidationResult(
            valid=not errors,
            plan=plan,
            errors=errors,
            warnings=warnings,
            fallback_reason="；".join(errors),
            should_fallback=False,
        )

    def _validate_raman_pipeline_step(
        self,
        action_name: str,
        args: dict[str, Any],
        normalized: NormalizedMessage,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        if action_name == "run_template_pipeline":
            request = PipelineRequest(
                file_path=normalized.file_path,
                template_id=str(args.get("template_id") or ""),
                save_history=False,
            )
            result = self.pipeline_runner.validate(request)
            errors.extend(str(item) for item in result.get("errors") or [])
            warnings.extend(str(item) for item in result.get("warnings") or [])
            return

        if action_name == "run_custom_pipeline":
            raw_steps = args.get("steps") or []
            if not isinstance(raw_steps, list) or not raw_steps:
                errors.append("参数不合法：run_custom_pipeline 需要非空 steps。")
                return
            try:
                request = PipelineRequest(
                    file_path=normalized.file_path,
                    steps=[PipelineStep(**dict(step)) for step in raw_steps],
                    save_history=False,
                )
            except Exception as exc:
                errors.append(f"Pipeline steps 参数不合法：{exc}")
                return
            result = self.pipeline_runner.validate(request)
            errors.extend(str(item) for item in result.get("errors") or [])
            warnings.extend(str(item) for item in result.get("warnings") or [])
            return

        if action_name == "compare_pipelines":
            pipelines = args.get("pipelines") or []
            if not isinstance(pipelines, list) or not pipelines:
                errors.append("参数不合法：compare_pipelines 需要 pipelines 列表。")
                return
            for index, item in enumerate(pipelines, start=1):
                if not isinstance(item, dict):
                    errors.append(f"第 {index} 个 Pipeline 配置不是对象。")
                    continue
                try:
                    request = PipelineRequest(
                        file_path=normalized.file_path,
                        template_id=item.get("template_id"),
                        steps=[PipelineStep(**dict(step)) for step in item.get("steps", [])],
                        save_history=False,
                    )
                except Exception as exc:
                    errors.append(f"第 {index} 个 Pipeline 参数不合法：{exc}")
                    continue
                result = self.pipeline_runner.validate(request)
                errors.extend(f"第 {index} 个 Pipeline：{item}" for item in result.get("errors") or [])
                warnings.extend(f"第 {index} 个 Pipeline：{item}" for item in result.get("warnings") or [])

