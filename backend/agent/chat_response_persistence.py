from __future__ import annotations

from pathlib import Path
from typing import Callable

from backend.agent.chat_context import ChatExecutionContext


class ChatResponsePersistence:
    TRACE_INTENTS = {
        "web_search",
        "document_processing",
        "csv_analysis",
        "raman_analysis",
        "report_generation",
        "image_understanding",
    }

    def __init__(
        self,
        *,
        workspace_manager,
        append_message: Callable[[str, str, str], object],
        update_session: Callable[[str, str, object], None],
        build_session_analysis_payload: Callable[[dict, str], dict],
        apply_task_state_from_response: Callable[[str, dict], None],
        llm_model_info: Callable[..., dict],
        task_trace_manager,
        project_root: Path,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.append_message = append_message
        self.update_session = update_session
        self.build_session_analysis_payload = build_session_analysis_payload
        self.apply_task_state_from_response = apply_task_state_from_response
        self.llm_model_info = llm_model_info
        self.task_trace_manager = task_trace_manager
        self.project_root = Path(project_root)

    def persist_user_turn(self, context: ChatExecutionContext) -> None:
        if context.persistence_state.get("user_turn_persisted"):
            return
        entry = self.workspace_manager.append_message(
            context.user_id,
            context.conversation_id,
            "user",
            context.effective_message,
            metadata={
                "debug": context.debug,
                "has_file": bool(context.selected_files or context.file_ids),
                "file_ids": list(context.file_ids),
                "knowledge_base_ids": list(context.knowledge_base_ids),
                "context_summary_chars": len((context.workspace_context or {}).get("context_summary") or ""),
                "conversation_id": context.conversation_id,
                "request_id": context.request_id,
                "turn_id": context.turn_id,
            },
        )
        context.user_message_id = str(entry.get("message_id") or "") or None
        self.append_message(context.session_id, "user", context.effective_message)
        context.persistence_state["user_turn_persisted"] = True

    def persist_final_response(self, context: ChatExecutionContext, response_payload: dict) -> dict:
        if context.persistence_state.get("final_response_persisted"):
            return dict(context.persistence_state.get("finalized_response") or {})

        response_payload = dict(response_payload or {})
        assistant_reply = (
            response_payload.get("reply")
            or response_payload.get("llm_explanation")
            or response_payload.get("error_message")
            or "处理完成。"
        )
        task_id = self._maybe_trace_task(context, response_payload, assistant_reply)
        self.append_message(context.session_id, "assistant", assistant_reply)
        finalized = self._finalize_workspace_response(
            context,
            response_payload,
            assistant_reply=assistant_reply,
            task_id=task_id or response_payload.get("task_id"),
        )
        self.apply_task_state_from_response(context.session_id, finalized)
        self._update_session_state(context, finalized)
        context.persistence_state["final_response_persisted"] = True
        context.persistence_state["finalized_response"] = dict(finalized)
        return finalized

    def _maybe_trace_task(self, context: ChatExecutionContext, response_payload: dict, assistant_reply: str) -> str | None:
        if response_payload.get("task_id"):
            return str(response_payload.get("task_id"))
        should_trace = bool(
            response_payload.get("skill_used")
            or response_payload.get("used_skill")
            or response_payload.get("tool_used")
            or response_payload.get("intent") in self.TRACE_INTENTS
        )
        if not should_trace:
            return None

        input_files = list(context.selected_files or [])
        file_path_value = str(context.orchestrator_payload.get("file_path") or "").strip()
        if file_path_value and not input_files:
            input_files = self._workspace_input_files(context.user_id, context.conversation_id, Path(file_path_value))

        task = self.task_trace_manager.create_task(
            user_id=context.user_id,
            conversation_id=context.conversation_id,
            intent=str(response_payload.get("intent") or "agent_task"),
            input_message=context.effective_message,
            input_files=input_files,
        )
        task_id = task["task_id"]
        identify_step = self.task_trace_manager.add_step(task_id, "识别任务类型", detail={"intent": response_payload.get("intent") or "agent_task"})
        self.task_trace_manager.finish_step(identify_step["step_id"], detail={"intent": response_payload.get("intent") or "agent_task"})
        execute_step = self.task_trace_manager.add_step(
            task_id,
            "执行 Agent 路由",
            detail={
                "route": response_payload.get("route"),
                "skill_name": response_payload.get("skill_name"),
                "tool_name": response_payload.get("tool_name"),
            },
        )
        status = "success" if response_payload.get("success") else "failed"
        self.task_trace_manager.finish_step(
            execute_step["step_id"],
            status=status,
            detail={"artifacts": response_payload.get("artifacts") or []},
            error_message=response_payload.get("error_message") if status == "failed" else None,
        )
        if response_payload.get("skill_name"):
            self._record_skill_trace(
                task_id=task_id,
                skill_name=str(response_payload.get("skill_name")),
                ability_name=response_payload.get("skill_action") or response_payload.get("action_name"),
                input_files=input_files,
                response_payload=response_payload,
                raw_result_summary=assistant_reply,
            )
        else:
            self.task_trace_manager.update_task(
                task_id,
                status=status,
                progress=100,
                error_message=response_payload.get("error_message") if status == "failed" else None,
                result_summary={"reply": assistant_reply[:500]},
            )
        response_payload["task_id"] = task_id
        response_payload["task"] = {
            "task_id": task_id,
            "status": status,
            "steps": self.task_trace_manager.get_task_trace(task_id).get("steps", []),
        }
        return task_id

    def _finalize_workspace_response(
        self,
        context: ChatExecutionContext,
        response_payload: dict,
        *,
        assistant_reply: str,
        task_id: str | None = None,
    ) -> dict:
        model_info = dict(response_payload.get("model_info") or response_payload.get("llm_model_info") or {})
        if not model_info:
            model_info = self.llm_model_info(user_id=context.user_id, conversation_id=context.conversation_id)
        if model_info:
            response_payload.setdefault("provider_id", model_info.get("provider"))
            response_payload.setdefault("model_id", model_info.get("model"))
            response_payload.setdefault("model_info", model_info)
        response_payload["conversation_id"] = context.conversation_id
        response_payload["session_id"] = context.session_id
        response_payload.setdefault("used_skill", bool(response_payload.get("skill_name")))
        self.workspace_manager.append_message(
            context.user_id,
            context.conversation_id,
            "assistant",
            assistant_reply,
            metadata={"task_id": task_id, "source": response_payload.get("source"), "request_id": context.request_id, "turn_id": context.turn_id},
        )
        self._update_workspace_summary(context.user_id, context.conversation_id, context.effective_message, assistant_reply)
        response_payload.setdefault("workspace", {})
        response_payload["workspace"].update(
            {
                "user_id": context.user_id,
                "conversation_id": context.conversation_id,
                "session_id": context.session_id,
                "task_id": task_id,
            }
        )
        return response_payload

    def _update_session_state(self, context: ChatExecutionContext, finalized: dict) -> None:
        session_patch = {"last_analysis": self.build_session_analysis_payload(finalized, context.session_id)}
        file_path_value = str(context.orchestrator_payload.get("file_path") or "").strip()
        if file_path_value:
            try:
                session_patch["last_file"] = str(Path(file_path_value).relative_to(self.project_root))
            except Exception:
                session_patch["last_file"] = file_path_value
        if context.selected_files:
            session_patch["last_files"] = context.selected_files[-20:]
        if finalized.get("report"):
            session_patch["last_report"] = finalized.get("report")
        for key, value in session_patch.items():
            self.update_session(context.session_id, key, value)

    def _update_workspace_summary(self, user_id: str, conversation_id: str, user_message: str, assistant_reply: str) -> None:
        existing = self.workspace_manager.read_context_summary(user_id, conversation_id).strip()
        recent = f"- 用户：{str(user_message or '')[:160]}\n- 助手：{str(assistant_reply or '')[:240]}"
        summary = (existing + "\n\n" + recent).strip() if existing else recent
        self.workspace_manager.update_context_summary(user_id, conversation_id, summary[-4000:])

    def _workspace_input_files(self, user_id: str, conversation_id: str, save_path: Path | None = None) -> list[dict]:
        active_files = self.workspace_manager.read_active_files(user_id, conversation_id)
        if save_path is None:
            return active_files[-5:]
        save_name = save_path.name
        matched = [item for item in active_files if item.get("filename") == save_name or str(item.get("path") or "").endswith(save_name)]
        return matched or [{"filename": save_name, "path": str(save_path)}]

    def _workspace_output_files(self, response_payload: dict) -> list[dict]:
        output_files: list[dict] = []
        for key in ("saved_file",):
            item = self._workspace_path_payload(response_payload.get(key))
            if item:
                output_files.append(item)
        report = response_payload.get("report") or {}
        if isinstance(report, dict):
            for key in ("report_path", "report_markdown_path", "report_html_path"):
                item = self._workspace_path_payload(report.get(key))
                if item:
                    output_files.append(item)
        web_urls = response_payload.get("web_urls") or {}
        if isinstance(web_urls, dict):
            figures = web_urls.get("figures") or {}
            if isinstance(figures, dict):
                for value in figures.values():
                    item = self._workspace_path_payload(value)
                    if item:
                        output_files.append(item)
        return output_files

    @staticmethod
    def _workspace_path_payload(path: str | Path | None) -> dict | None:
        if not path:
            return None
        raw = str(path)
        return {"filename": Path(raw).name, "path": raw}

    def _record_skill_trace(
        self,
        *,
        task_id: str,
        skill_name: str,
        ability_name: str | None,
        input_files: list[dict] | None,
        response_payload: dict,
        raw_result_summary: str | None = None,
    ) -> dict:
        select_step = self.task_trace_manager.add_step(
            task_id,
            "选择 Skill",
            detail={"skill_name": skill_name, "ability_name": ability_name},
        )
        self.task_trace_manager.finish_step(select_step["step_id"], detail={"skill_name": skill_name, "ability_name": ability_name})
        run_step = self.task_trace_manager.add_step(
            task_id,
            "执行 Skill",
            detail={"skill_name": skill_name, "ability_name": ability_name},
        )
        status = "success" if response_payload.get("success") else "failed"
        error_message = response_payload.get("error_message") or response_payload.get("llm_error")
        output_files = self._workspace_output_files(response_payload)
        self.task_trace_manager.finish_step(
            run_step["step_id"],
            status=status,
            detail={"output_files": output_files},
            error_message=error_message,
        )
        return self.task_trace_manager.record_skill_run(
            task_id=task_id,
            skill_name=skill_name,
            ability_name=ability_name,
            input_files=input_files or [],
            output_files=output_files,
            status=status,
            error_message=error_message,
            raw_result_summary=raw_result_summary or response_payload.get("reply") or response_payload.get("llm_explanation"),
        )
