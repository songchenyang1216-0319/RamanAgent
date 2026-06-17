"""Executor for validated enhanced plans."""

from __future__ import annotations

from typing import Any

from backend.agent.types import NormalizedMessage
from backend.schemas.agent_response import AgentResponse
from backend.skills.registry import execute_skill
from backend.tools.tool_runner import ToolRunner
from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
from backend.raman_pipeline.pipeline_schema import PipelineRequest, PipelineStep
from backend.tool_runtime import ToolContext, ToolRuntime

from .plan_types import LLMPlan, PlanStep


class PlanExecutor:
    def __init__(self, pipeline_runner: RamanPipelineRunner | None = None) -> None:
        self.pipeline_runner = pipeline_runner or RamanPipelineRunner()
        self.tool_runner = ToolRunner()
        self.tool_runtime = ToolRuntime()

    def execute(self, plan: LLMPlan, normalized: NormalizedMessage) -> AgentResponse:
        results: list[dict[str, Any]] = []
        artifacts: list[Any] = []
        errors: list[str] = []
        citations: list[dict[str, Any]] = []
        context = ToolContext.from_normalized(
            normalized,
            source="plan_executor",
            metadata={
                **dict(normalized.metadata or {}),
                "message": normalized.message,
                "knowledge_base_ids": list(normalized.knowledge_base_ids or []),
                "rag_scope": normalized.rag_scope,
            },
        )
        for step in plan.steps:
            args = dict(step.args or {})
            args.setdefault("message", normalized.message)
            if normalized.file_path:
                args.setdefault("file_path", normalized.file_path)
            if normalized.file_ids:
                args.setdefault("file_ids", list(normalized.file_ids or []))
            if normalized.knowledge_base_ids:
                args.setdefault("knowledge_base_ids", list(normalized.knowledge_base_ids or []))
            if normalized.rag_scope:
                args.setdefault("rag_scope", normalized.rag_scope)
            runtime_result = self.tool_runtime.execute(step.tool_name, step.action_name, args, context)
            result = runtime_result.to_dict()
            results.append(result)
            artifacts.extend(result.get("artifacts") or [])
            citations.extend(result.get("citations") or [])
            if result.get("requires_confirmation"):
                errors.append(str(result.get("summary") or result.get("warning") or "该操作需要确认后才能执行。"))
                break
            if not result.get("success"):
                errors.append(str(result.get("error_message") or result.get("summary") or "步骤执行失败。"))
                break

        success = not errors
        reply = self._build_reply(plan, results, success, errors)
        return AgentResponse(
            success=success,
            reply=reply,
            intent=plan.intent,
            route=plan.plan_type,
            tool_used=True,
            tool_name=plan.steps[0].tool_name if plan.steps else None,
            skill_used=any(step.tool_name in {"raman_model", "web_search", "document_tool", "report_tool"} for step in plan.steps),
            skill_name=self._skill_name_for(plan.steps[0].tool_name) if plan.steps else None,
            action_name=plan.steps[0].action_name if plan.steps else None,
            artifacts=artifacts,
            data={"plan": plan.to_dict(), "step_results": results, "citations": citations},
            error_message="；".join(errors) if errors else None,
            conversation_id=normalized.conversation_id,
            session_id=normalized.session_id,
            source="enhanced_planning",
        )

    def _execute_step(self, step: PlanStep, normalized: NormalizedMessage) -> dict[str, Any]:
        if step.tool_name == "raman_pipeline":
            return self._execute_raman_pipeline(step, normalized)
        if step.tool_name == "raman_model":
            action = step.action_name or "predict_methanol_concentration"
            result = execute_skill(
                "raman_spectroscopy_skill",
                action_name=action,
                file_path=normalized.file_path or "",
                metadata=normalized.metadata or {},
                include_intermediate=False,
            )
            return {
                "success": result.success,
                "tool_name": step.tool_name,
                "action_name": action,
                "summary": result.summary,
                "data": result.data,
                "artifacts": list(result.plots or []),
                "error_message": "；".join(result.errors),
            }
        if step.tool_name == "web_search":
            result = execute_skill("web-search", action_name="answer_with_sources", query=normalized.message, message=normalized.message)
            return {
                "success": result.success,
                "tool_name": step.tool_name,
                "action_name": step.action_name,
                "summary": result.summary,
                "data": result.data,
                "artifacts": list(result.plots or []),
                "error_message": "；".join(result.errors),
            }
        if step.tool_name == "document_tool":
            result = execute_skill(
                "document-reader",
                action_name=step.action_name,
                file_path=normalized.file_path or "",
                message=normalized.message,
            )
            return {
                "success": result.success,
                "tool_name": step.tool_name,
                "action_name": step.action_name,
                "summary": result.summary,
                "data": result.data,
                "artifacts": list(result.plots or []),
                "error_message": "；".join(result.errors),
            }
        if step.tool_name == "file_tool":
            tool_result = self.tool_runner.run("file_info_tool", normalized)
            return {
                "success": tool_result.success,
                "tool_name": step.tool_name,
                "action_name": step.action_name,
                "summary": tool_result.summary,
                "data": tool_result.data,
                "artifacts": [],
                "error_message": tool_result.error_message,
            }
        if step.tool_name == "rag":
            from backend.services.rag import RAGService

            result = RAGService().answer_with_rag(
                normalized.message,
                normalized.user_id,
                normalized.conversation_id,
                file_ids=list(normalized.file_ids or []),
                knowledge_base_ids=list(normalized.knowledge_base_ids or []),
                rag_scope=normalized.rag_scope or "conversation",
            ).to_dict()
            return {
                "success": bool(result.get("success")),
                "tool_name": step.tool_name,
                "action_name": step.action_name,
                "summary": result.get("answer") or result.get("reply") or "",
                "data": result,
                "artifacts": [],
                "error_message": result.get("error_message") or "",
            }
        if step.tool_name == "report_tool":
            result = execute_skill("report-generator", action_name=step.action_name, message=normalized.message)
            return {
                "success": result.success,
                "tool_name": step.tool_name,
                "action_name": step.action_name,
                "summary": result.summary,
                "data": result.data,
                "artifacts": list(result.plots or []),
                "error_message": "；".join(result.errors),
            }
        if step.tool_name == "model_tool":
            from backend.services.llm_registry_service import LLMRegistryService

            service = LLMRegistryService()
            if step.action_name == "get_current_model":
                data = service.get_current_model()
            elif step.action_name == "list_models":
                data = service.list_models()
            else:
                data = {"success": False, "error_message": f"model_tool 不支持 action：{step.action_name}"}
            return {
                "success": bool(data.get("success", True)),
                "tool_name": step.tool_name,
                "action_name": step.action_name,
                "summary": data.get("message") or "模型信息已获取。",
                "data": data,
                "artifacts": [],
                "error_message": data.get("error_message") or "",
            }
        if step.tool_name == "skill_tool":
            from backend.skills.registry import list_skills

            if step.action_name == "list_skills":
                data = list_skills(include_actions=True)
                return {
                    "success": True,
                    "tool_name": step.tool_name,
                    "action_name": step.action_name,
                    "summary": f"当前共有 {data.get('total', 0)} 个 Skill。",
                    "data": data,
                    "artifacts": [],
                    "error_message": "",
                }
        if step.tool_name == "task_tool":
            from backend.tasks import get_task_manager

            task_id = str((step.args or {}).get("task_id") or "")
            if step.action_name == "get_task" and task_id:
                data = get_task_manager().get_task(task_id) or {}
                return {
                    "success": bool(data),
                    "tool_name": step.tool_name,
                    "action_name": step.action_name,
                    "summary": "任务详情已获取。" if data else "任务不存在。",
                    "data": data,
                    "artifacts": data.get("artifacts") or [],
                    "error_message": "" if data else "任务不存在。",
                }
        return {
            "success": False,
            "tool_name": step.tool_name,
            "action_name": step.action_name,
            "summary": "",
            "data": {},
            "artifacts": [],
            "error_message": f"PlanExecutor 未实现工具：{step.tool_name}",
        }

    def _execute_raman_pipeline(self, step: PlanStep, normalized: NormalizedMessage) -> dict[str, Any]:
        args = dict(step.args or {})
        if step.action_name == "run_template_pipeline":
            result = self.pipeline_runner.run(
                PipelineRequest(
                    file_path=normalized.file_path,
                    template_id=str(args.get("template_id") or "basic_preprocessing"),
                    save_history=True,
                )
            )
            return self._pipeline_result(step, result.model_dump())
        if step.action_name == "run_custom_pipeline":
            result = self.pipeline_runner.run(
                PipelineRequest(
                    file_path=normalized.file_path,
                    steps=[PipelineStep(**dict(item)) for item in args.get("steps", [])],
                    save_history=True,
                )
            )
            return self._pipeline_result(step, result.model_dump())
        if step.action_name == "compare_pipelines":
            pipelines = list(args.get("pipelines") or [])
            results = []
            artifacts = []
            success = True
            for item in pipelines:
                request = PipelineRequest(
                    file_path=normalized.file_path,
                    template_id=item.get("template_id"),
                    steps=[PipelineStep(**dict(step_payload)) for step_payload in item.get("steps", [])],
                    save_history=False,
                )
                pipeline_result = self.pipeline_runner.run(request).model_dump()
                results.append(pipeline_result)
                artifacts.extend(pipeline_result.get("artifacts") or [])
                success = success and bool(pipeline_result.get("success"))
            return {
                "success": success,
                "tool_name": step.tool_name,
                "action_name": step.action_name,
                "summary": f"已完成 {len(results)} 个 Pipeline 对比。",
                "data": {"results": results},
                "artifacts": artifacts,
                "error_message": "；".join(str(item.get("error_message")) for item in results if item.get("error_message")),
            }
        if step.action_name == "list_algorithms":
            from backend.raman_pipeline.algorithm_registry import get_algorithm_registry

            return {"success": True, "tool_name": step.tool_name, "action_name": step.action_name, "summary": "算法库已获取。", "data": get_algorithm_registry().to_dict(), "artifacts": [], "error_message": ""}
        return {
            "success": False,
            "tool_name": step.tool_name,
            "action_name": step.action_name,
            "summary": "",
            "data": {},
            "artifacts": [],
            "error_message": f"raman_pipeline 不支持 action：{step.action_name}",
        }

    def _pipeline_result(self, step: PlanStep, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": bool(result.get("success")),
            "tool_name": step.tool_name,
            "action_name": step.action_name,
            "summary": result.get("message") or "",
            "data": result,
            "artifacts": result.get("artifacts") or [],
            "error_message": result.get("error_message") or "",
        }

    def _build_reply(self, plan: LLMPlan, results: list[dict[str, Any]], success: bool, errors: list[str]) -> str:
        if not success:
            return "增强规划执行失败：" + "；".join(errors)
        if plan.plan_type == "raman_pipeline":
            last = results[-1] if results else {}
            data = last.get("data") or {}
            if isinstance(data, dict) and data.get("final_spectrum"):
                final = data.get("final_spectrum") or {}
                return f"Raman Pipeline 已完成，共输出 {final.get('points', 0)} 个光谱点，生成 {len(data.get('artifacts') or [])} 个产物。"
            return last.get("summary") or "Raman Pipeline 已完成。"
        if plan.plan_type == "hybrid":
            summaries = [str(item.get("summary") or "").strip() for item in results if str(item.get("summary") or "").strip()]
            return "；".join(summaries) or "混合计划已执行完成。"
        return results[-1].get("summary") if results else "计划已执行完成。"

    def _skill_name_for(self, tool_name: str) -> str | None:
        return {
            "raman_model": "raman_spectroscopy_skill",
            "web_search": "web-search",
            "document_tool": "document-reader",
            "report_tool": "report-generator",
        }.get(tool_name)
