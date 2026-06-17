from __future__ import annotations

from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
from backend.raman_pipeline.pipeline_schema import PipelineRequest, PipelineStep
from backend.skills.registry import execute_skill
from backend.tool_runtime.tool_context import ToolContext
from backend.tool_runtime.tool_result import ToolResult


class RamanToolAdapter:
    def __init__(self) -> None:
        self.pipeline_runner = RamanPipelineRunner()

    def execute(self, tool_name: str, action_name: str, args: dict, context: ToolContext) -> ToolResult:
        if tool_name == "raman_pipeline":
            return self._execute_pipeline(action_name, args, context)
        if tool_name == "raman_model":
            file_path = self._file_path(args, context)
            result = execute_skill(
                "raman_spectroscopy_skill",
                action_name=action_name or "predict_methanol_concentration",
                file_path=file_path,
                metadata=dict(context.metadata or {}),
                include_intermediate=False,
            )
            return ToolResult(
                success=result.success,
                tool_name=tool_name,
                action_name=action_name,
                status="success" if result.success else "failed",
                summary=result.summary,
                data=dict(result.data or {}),
                artifacts=list(result.plots or []),
                error_code="" if result.success else "RAMAN_PIPELINE_FAILED",
                error_message="；".join(result.errors),
            )
        return ToolResult(False, tool_name, action_name, status="failed", error_code="ACTION_NOT_FOUND", error_message=f"Raman 工具不支持动作：{tool_name}.{action_name}")

    def _execute_pipeline(self, action_name: str, args: dict, context: ToolContext) -> ToolResult:
        file_path = self._file_path(args, context)
        if action_name == "run_template_pipeline":
            result = self.pipeline_runner.run(PipelineRequest(file_path=file_path, template_id=str(args.get("template_id") or "basic_preprocessing"), save_history=True))
            return self._from_pipeline_result(action_name, result.model_dump())
        if action_name == "run_custom_pipeline":
            steps = [PipelineStep(**dict(item)) for item in args.get("steps", [])]
            result = self.pipeline_runner.run(PipelineRequest(file_path=file_path, steps=steps, save_history=True))
            return self._from_pipeline_result(action_name, result.model_dump())
        if action_name == "compare_pipelines":
            results = []
            artifacts = []
            success = True
            for item in list(args.get("pipelines") or []):
                request = PipelineRequest(
                    file_path=file_path,
                    template_id=item.get("template_id"),
                    steps=[PipelineStep(**dict(step_payload)) for step_payload in item.get("steps", [])],
                    save_history=False,
                )
                payload = self.pipeline_runner.run(request).model_dump()
                results.append(payload)
                artifacts.extend(payload.get("artifacts") or [])
                success = success and bool(payload.get("success"))
            return ToolResult(success, "raman_pipeline", action_name, summary=f"已完成 {len(results)} 个 Pipeline 对比。", data={"results": results}, artifacts=artifacts, error_code="" if success else "RAMAN_PIPELINE_FAILED")
        if action_name == "list_algorithms":
            from backend.raman_pipeline.algorithm_registry import get_algorithm_registry

            return ToolResult(True, "raman_pipeline", action_name, summary="算法库已获取。", data=get_algorithm_registry().to_dict())
        return ToolResult(False, "raman_pipeline", action_name, status="failed", error_code="ACTION_NOT_FOUND", error_message=f"raman_pipeline 不支持 action：{action_name}")

    def _from_pipeline_result(self, action_name: str, payload: dict) -> ToolResult:
        success = bool(payload.get("success"))
        return ToolResult(
            success=success,
            tool_name="raman_pipeline",
            action_name=action_name,
            status="success" if success else "failed",
            summary=payload.get("message") or "",
            data=payload,
            artifacts=list(payload.get("artifacts") or []),
            events=list(payload.get("steps") or []),
            error_code="" if success else "RAMAN_PIPELINE_FAILED",
            error_message=payload.get("error_message") or "",
            warning="；".join(payload.get("warnings") or []),
        )

    def _file_path(self, args: dict, context: ToolContext) -> str:
        if args.get("file_path"):
            return str(args.get("file_path"))
        if context.active_files:
            item = context.active_files[0]
            return str(item.get("path") or item.get("file_path") or "")
        return ""
