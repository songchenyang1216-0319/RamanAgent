from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from backend.schemas.file_analysis import FileAnalysisRequest
from backend.services.file_service import FileCatalogService
from backend.services.workspace_manager import DEFAULT_USER_ID
from raman_core.methanol.config import PROJECT_ROOT


logger = logging.getLogger(__name__)


class AgentFileNotFoundError(Exception):
    pass


class FilePermissionDeniedError(Exception):
    pass


class UnsupportedFileTypeError(Exception):
    pass


class AgentFileAnalysisError(Exception):
    pass


class FileAnalysisService:
    def __init__(self, *, file_catalog: FileCatalogService | None = None) -> None:
        self.file_catalog = file_catalog or FileCatalogService()

    async def analyze_upload(
        self,
        *,
        file: UploadFile,
        request: FileAnalysisRequest,
    ) -> dict[str, Any]:
        from backend.agent import agent_router as legacy

        resolved_session_id = legacy._ensure_session_id(request.conversation_id or request.session_id)
        save_path = await legacy._save_uploaded_attachment(
            file,
            user_id=request.user_id or DEFAULT_USER_ID,
            conversation_id=resolved_session_id,
        )
        return self._analyze_path(
            save_path=save_path,
            request=request,
            resolved_session_id=resolved_session_id,
            files=[],
        )

    async def analyze(self, *, request: FileAnalysisRequest, is_admin: bool = False) -> dict[str, Any]:
        from backend.agent import agent_router as legacy

        file_ids = self._normalize_file_ids(request)
        if not file_ids:
            raise AgentFileNotFoundError("缺少 file_id 或 file_ids。")
        effective_user_id = request.user_id or DEFAULT_USER_ID
        resolved_session_id = legacy._ensure_session_id(request.conversation_id or request.session_id)
        files = []
        for file_id in file_ids:
            item = self.file_catalog.get_file_for_user(file_id, user_id=effective_user_id, is_admin=is_admin)
            if item is None:
                raise AgentFileNotFoundError("文件不存在。")
            files.append(item)
        first_file = files[0]
        save_path = self._resolve_file_path(first_file)
        result = self._analyze_path(
            save_path=save_path,
            request=request,
            resolved_session_id=resolved_session_id,
            files=files,
        )
        result.setdefault("files", files)
        result.setdefault("file_ids", file_ids)
        result.setdefault("file_id", file_ids[0])
        return result

    def _analyze_path(
        self,
        *,
        save_path: Path,
        request: FileAnalysisRequest,
        resolved_session_id: str,
        files: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from backend.agent import agent_router as legacy
        from backend.skills.registry import execute_skill
        from backend.services.history_service import save_analysis_history

        message = request.message or "请分析这个文件"
        metadata = dict(request.metadata or {})
        file_suffix = save_path.suffix.lower()
        if not save_path.exists() or not save_path.is_file():
            raise AgentFileNotFoundError("文件已被删除或移动。")

        if not legacy._is_table_file_suffix(file_suffix):
            response_payload = self._analyze_non_table_file(
                legacy=legacy,
                save_path=save_path,
                message=message,
                metadata=metadata,
                resolved_session_id=resolved_session_id,
            )
            return self._finalize_response(legacy, response_payload, resolved_session_id, files)

        csv_route_skill, _csv_route_action, csv_route_info = legacy._select_skill_route(
            message,
            has_file=True,
            file_suffix=file_suffix,
            file_path=save_path,
        )
        if csv_route_info and csv_route_info.get("route") in {"data_analysis_missing_skill", "image_router_missing_skill"}:
            response_payload = legacy._build_no_matching_file_skill_response(
                session_id=resolved_session_id,
                save_path=save_path,
                message=message,
                file_suffix=file_suffix,
                route_info=csv_route_info,
                debug=request.debug,
            )
            return self._finalize_response(legacy, response_payload, resolved_session_id, files)

        if legacy._is_service_run_tool_overridden():
            response_payload = legacy._analyze_csv_with_service_tools(
                save_path=save_path,
                message=message,
                session_id=resolved_session_id,
                metadata=metadata,
            )
            return self._finalize_response(legacy, response_payload, resolved_session_id, files)

        if request.skill_name or request.action_name:
            skill_name = request.skill_name or csv_route_skill or "raman_spectroscopy_skill"
            action_name = request.action_name or "predict_methanol_concentration"
        elif csv_route_skill != "raman_spectroscopy_skill":
            response_payload = legacy._analyze_uploaded_file_with_skills(
                save_path=save_path,
                message=message,
                session_id=resolved_session_id,
                metadata=metadata,
                debug=request.debug,
            )
            return self._finalize_response(legacy, response_payload, resolved_session_id, files)
        else:
            skill_name = "raman_spectroscopy_skill"
            action_name = "predict_methanol_concentration"

        started = time.perf_counter()
        skill_result = execute_skill(
            skill_name,
            action_name=action_name,
            file_path=str(save_path),
            session_id=resolved_session_id,
            message=message,
            original_message=message,
            experiment_metadata=metadata,
        )
        reply = str(skill_result.data.get("reply_text") or skill_result.summary or "光谱分析已完成。")
        result_kind = legacy._resolve_result_kind(skill_name, action_name)
        analysis_payload = legacy._build_skill_analysis_payload(
            skill_name,
            action_name,
            skill_result.to_dict(),
            message=reply,
            save_path=str(save_path),
        )
        response_payload = {
            "success": skill_result.success,
            "session_id": resolved_session_id,
            "message": message,
            "saved_file": self._project_relative(save_path),
            "result": skill_result.data.get("result"),
            "professional_analysis": skill_result.data.get("professional_analysis") or {},
            "model_info": skill_result.data.get("model_info") or {},
            "llm_model_info": legacy._llm_model_info(conversation_id=resolved_session_id),
            "experiment_metadata": metadata,
            "llm_explanation": reply,
            "llm_error": None if skill_result.success else reply,
            "report": skill_result.data.get("report"),
            "web_urls": skill_result.data.get("web_urls") or {"figures": {}, "report_view": "", "report_download": ""},
            "warnings": list(skill_result.data.get("warnings") or getattr(skill_result, "warnings", []) or []),
            "skill_name": skill_name,
            "action_name": action_name,
            "error_message": None if skill_result.success else reply,
            "data": skill_result.data,
            "errors": skill_result.errors,
        }
        response_payload.update(
            legacy._build_chat_messages_payload(
                session_id=resolved_session_id,
                role_type="analysis" if result_kind in {"prediction", "report", "generic"} else "text",
                content=reply,
                analysis=analysis_payload if result_kind in {"prediction", "report", "generic"} else None,
                skill_name=skill_name,
                action_name=action_name,
                result_kind=result_kind,
            )
        )
        legacy._attach_source(
            response_payload,
            "skill_execution",
            route_info={"route": "builtin_skill_rule", "reason": "csv_raman_skill"},
            debug=request.debug,
        )
        if skill_result.success:
            try:
                history_payload = {
                    "saved_file": response_payload["saved_file"],
                    "result": skill_result.data.get("result") or {},
                    "llm_explanation": reply,
                    "report": response_payload.get("report") or {},
                    "web_urls": response_payload.get("web_urls") or {},
                    "professional_analysis": response_payload.get("professional_analysis") or {},
                    "model_info": response_payload.get("model_info") or {},
                    "experiment_metadata": metadata,
                }
                response_payload["history"] = save_analysis_history(history_payload)
            except Exception as exc:
                response_payload["history_error"] = str(exc)
        logger.info(
            "Analyze-file skill executed: skill=%s action=%s success=%s elapsed_ms=%.2f summary=%s",
            skill_name,
            action_name,
            skill_result.success,
            (time.perf_counter() - started) * 1000,
            (skill_result.summary or "")[:160],
        )
        return self._finalize_response(legacy, response_payload, resolved_session_id, files)

    def _analyze_non_table_file(
        self,
        *,
        legacy,
        save_path: Path,
        message: str,
        metadata: dict[str, Any],
        resolved_session_id: str,
    ) -> dict[str, Any]:
        from backend.skills.registry import execute_skill

        matched_skill, matched_action, route_info = legacy._select_skill_route(
            message,
            has_file=True,
            file_suffix=save_path.suffix.lower(),
            file_path=save_path,
        )
        if matched_skill is None or matched_action is None:
            return legacy._build_no_matching_file_skill_response(
                session_id=resolved_session_id,
                save_path=save_path,
                message=message,
                file_suffix=save_path.suffix.lower(),
                route_info=route_info,
                debug=False,
            )

        task_type = legacy._infer_document_task_type(message, file_suffix=save_path.suffix.lower())
        matched_skill_mode = legacy._resolve_uploaded_skill_mode(matched_skill)
        started = time.perf_counter()
        skill_result = execute_skill(
            matched_skill,
            action_name=matched_action,
            file_path=str(save_path),
            task_type=task_type,
            session_id=resolved_session_id,
            message=message,
            original_message=message,
        )
        resolved_action_name = str(skill_result.action_name or skill_result.data.get("action") or matched_action or "").strip() or matched_action
        is_image_skill = matched_skill == "image-router-skill"
        reply = str(
            skill_result.data.get("analysis_markdown")
            or skill_result.data.get("reply_text")
            or skill_result.summary
            or ("图片分析完成。" if is_image_skill else "文档 Skill 执行完成。")
        )
        if is_image_skill and not skill_result.success and any("当前已禁用" in str(item) for item in (skill_result.errors or [])):
            reply = "当前已识别为图片文件，但 image-router-skill 当前被禁用。你可以在 Skill 管理页面重新启用它。"
        result_kind = "prompt_only_skill" if matched_skill_mode == "prompt_only" else legacy._resolve_result_kind(matched_skill, resolved_action_name)
        analysis_payload = legacy._build_skill_analysis_payload(
            matched_skill,
            resolved_action_name,
            skill_result.to_dict(),
            message=reply,
            save_path=str(save_path),
        )
        tool_info = dict(skill_result.data.get("tool_info") or {})
        if is_image_skill:
            tool_info.setdefault("filename", save_path.name)
            tool_info.setdefault("mode", "image_router")
            tool_info.setdefault("source", "skill_execution")
            tool_info.setdefault("skill", matched_skill)
            tool_info.setdefault("action", resolved_action_name)
            tool_info.setdefault("success", bool(skill_result.success))
            tool_info.setdefault("image_type", str(skill_result.data.get("image_type") or "UNKNOWN_IMAGE"))
        response_payload = {
            "success": skill_result.success,
            "session_id": resolved_session_id,
            "message": message,
            "saved_file": self._project_relative(save_path),
            "result": None,
            "professional_analysis": {},
            "model_info": {},
            "llm_model_info": legacy._llm_model_info(conversation_id=resolved_session_id),
            "experiment_metadata": metadata,
            "llm_explanation": reply,
            "llm_error": None,
            "report": None,
            "web_urls": {"figures": {}, "report_view": "", "report_download": ""},
            "warnings": [],
            "attachment_info": {},
            "skill_name": matched_skill,
            "action_name": resolved_action_name,
            "skill_mode": matched_skill_mode,
            "error_message": None if skill_result.success else "；".join(skill_result.errors) or reply,
            "data": skill_result.data,
            "errors": skill_result.errors,
            "intent": "IMAGE_ANALYSIS" if is_image_skill else matched_action,
            "tool_info": tool_info,
        }
        response_payload.update(
            legacy._build_chat_messages_payload(
                session_id=resolved_session_id,
                role_type="text" if is_image_skill or matched_skill_mode == "prompt_only" else ("analysis" if result_kind == "uploaded_skill" else "text"),
                content=reply,
                analysis=analysis_payload if (matched_skill_mode == "prompt_only" or result_kind == "uploaded_skill") and not is_image_skill else None,
                skill_name=matched_skill,
                action_name=resolved_action_name,
                result_kind=result_kind,
                skill_mode=matched_skill_mode,
            )
        )
        legacy._attach_source(response_payload, "skill_execution", route_info=route_info, debug=False)
        logger.info(
            "Analyze-file attachment skill executed: skill=%s action=%s success=%s elapsed_ms=%.2f summary=%s",
            matched_skill,
            resolved_action_name,
            skill_result.success,
            (time.perf_counter() - started) * 1000,
            (skill_result.summary or "")[:160],
        )
        return response_payload

    def _finalize_response(self, legacy, response_payload: dict[str, Any], session_id: str, files: list[dict[str, Any]]) -> dict[str, Any]:
        assistant_reply = response_payload.get("reply") or response_payload.get("llm_explanation") or response_payload.get("error_message") or ""
        legacy.append_message(session_id, "assistant", assistant_reply)
        session_analysis = legacy._build_session_analysis_payload(response_payload, session_id)
        legacy.update_session(session_id, "last_analysis", session_analysis)
        legacy.update_session(session_id, "last_file", response_payload.get("saved_file"))
        legacy.update_session(session_id, "last_report", response_payload.get("report"))
        legacy._apply_task_state_from_response(session_id, response_payload)
        if files:
            response_payload.setdefault("files", files)
            response_payload.setdefault("file_ids", [str(item.get("file_id")) for item in files if item.get("file_id")])
            if files[0].get("file_id"):
                response_payload.setdefault("file_id", str(files[0].get("file_id")))
        response_payload.setdefault("conversation_id", session_id)
        response_payload.setdefault("session_id", session_id)
        return response_payload

    def _resolve_file_path(self, file_item: dict[str, Any]) -> Path:
        raw_path = str(file_item.get("path") or "").strip()
        if not raw_path:
            raise AgentFileNotFoundError("文件不存在。")
        path = (PROJECT_ROOT / raw_path).resolve()
        project_root = PROJECT_ROOT.resolve()
        if path != project_root and project_root not in path.parents:
            raise FilePermissionDeniedError("文件路径不合法。")
        if not path.exists() or not path.is_file():
            raise AgentFileNotFoundError("文件已被删除或移动。")
        return path

    @staticmethod
    def _normalize_file_ids(request: FileAnalysisRequest) -> list[str]:
        raw = list(request.file_ids or [])
        if request.file_id:
            raw.insert(0, request.file_id)
        result = []
        seen = set()
        for item in raw:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    @staticmethod
    def _project_relative(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
        except ValueError:
            return str(path)
