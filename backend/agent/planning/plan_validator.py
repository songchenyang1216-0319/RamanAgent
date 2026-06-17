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
            for arg_name in list(action.required_args or []):
                if arg_name not in dict(step.args or {}):
                    errors.append(f"{tool.display_name}/{action.action_name} 缺少参数：{arg_name}")
            self._validate_args_schema(tool.display_name, action.action_name, action.input_schema or action.arg_schema or {}, dict(step.args or {}), errors)
            self._validate_danger_contract(tool.display_name, action, errors)
            if action.requires_confirmation and not bool((step.args or {}).get("confirmed")):
                errors.append(f"{tool.display_name}/{action.action_name} 属于需要确认的操作，请先确认后再执行。")

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

    def _validate_args_schema(self, tool_display_name: str, action_name: str, schema: dict[str, Any], args: dict[str, Any], errors: list[str]) -> None:
        if not schema:
            return
        required = list(schema.get("required") or [])
        for key in required:
            if key not in args:
                errors.append(f"{tool_display_name}/{action_name} 缺少 schema 必填参数：{key}")
        properties = dict(schema.get("properties") or {})
        for key, spec in properties.items():
            if key not in args or not isinstance(spec, dict):
                continue
            expected = spec.get("type")
            if expected and not self._type_matches(args.get(key), expected):
                errors.append(f"{tool_display_name}/{action_name} 参数 {key} 类型不合法，应为 {expected}。")

    def _type_matches(self, value: Any, expected: str | list[str]) -> bool:
        expected_types = expected if isinstance(expected, list) else [expected]
        mapping = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        return any(isinstance(value, mapping.get(item, object)) for item in expected_types)

    def _validate_danger_contract(self, tool_display_name: str, action: Any, errors: list[str]) -> None:
        side_effects = set(action.side_effects or [])
        danger = str(action.danger_level or "low")
        risky_effects = {"execute_code", "delete_file", "modify_model", "cost_money"}
        if side_effects & risky_effects and danger not in {"medium", "high", "critical"}:
            errors.append(f"{tool_display_name}/{action.action_name} 声明了高风险副作用，但 danger_level 低于 medium。")
        if danger in {"high", "critical"} and not action.requires_confirmation:
            errors.append(f"{tool_display_name}/{action.action_name} 为高风险动作，必须 requires_confirmation=true。")

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
