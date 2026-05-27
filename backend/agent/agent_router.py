"""Agent HTTP 接口。"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from backend.agent.agent_service import RamanAgentService
from backend.agent.tools.report_tool import explain_result_tool, generate_report_tool
from backend.agent.tools.spectral_tools.spectral_summary_tool import analyze_spectrum_professionally
from backend.agent.session_store import (
    append_message,
    build_task_state_response,
    clear_session_memory,
    create_session,
    get_session,
    get_task_state,
    update_session,
    update_task_state,
)
from backend.skills.registry import (
    execute_skill,
    get_action,
    get_skill,
    list_skills,
    match_uploaded_skill,
    set_action_enabled,
    set_skill_enabled,
)
from backend.skills.data_analysis_skill import (
    DATA_ANALYSIS_MESSAGE_KEYWORDS,
    RAMAN_MESSAGE_KEYWORDS,
    detect_raman_table_signal,
    infer_data_analysis_action,
    is_supported_table_suffix,
)
from backend.skills.upload_service import delete_uploaded_skill, list_uploaded_skills, save_uploaded_skill
from backend.services.history_service import save_analysis_history
from backend.api.methanol_api import build_figure_web_urls, build_report_web_urls
from backend.services.model_registry_service import ModelRegistryService
from backend.services.llm_service import LLMService
from backend.services.methanol_service import reset_predictor_cache
from backend.services.task_trace_manager import TaskTraceManager
from backend.services.user_memory_manager import UserMemoryManager
from backend.services.workspace_manager import DEFAULT_USER_ID, WorkspaceManager
from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT, ensure_dirs


router = APIRouter(prefix="/api/agent", tags=["agent"])
service = RamanAgentService()
model_registry_service = ModelRegistryService()
workspace_manager = WorkspaceManager()
user_memory_manager = UserMemoryManager()
task_trace_manager = TaskTraceManager(workspace_manager=workspace_manager)
UPLOAD_DIR = OUTPUT_DIR / "uploads"
logger = logging.getLogger(__name__)
IMAGE_FILE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
TABLE_FILE_SUFFIXES = {".csv", ".xlsx", ".xls"}
DATA_ANALYSIS_MISSING_MESSAGE = "当前识别为普通表格数据，但 data-analysis-skill 未启用。你可以在 Skill 管理中启用表格数据分析 Skill。"
IMAGE_ROUTER_MISSING_MESSAGE = "当前已识别为图片文件，但还没有安装图片处理 Skill。你可以上传 image-router-skill，或后续启用视觉模型能力。"
RAMAN_SKILL_DISABLED_MESSAGE = "当前识别为 Raman / 光谱数据请求，但 Raman 光谱分析 Skill 未启用。"


def _llm_model_info(
    user_id: str | None = None,
    conversation_id: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
) -> dict:
    """返回当前生成回复所使用的大模型信息。"""
    try:
        return LLMService(
            user_id=user_id,
            conversation_id=conversation_id,
            provider_id=provider_id,
            model_id=model_id,
        ).get_current_model_info()
    except Exception:
        return {}


def _normalize_skill_key(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _is_image_file_suffix(file_suffix: str | None) -> bool:
    return str(file_suffix or "").lower() in IMAGE_FILE_SUFFIXES


def _is_table_file_suffix(file_suffix: str | None) -> bool:
    return str(file_suffix or "").lower() in TABLE_FILE_SUFFIXES


class AgentChatRequest(BaseModel):
    """Agent 聊天请求。"""

    message: str
    debug: bool = False
    conversation_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None
    provider_id: str | None = None
    model_id: str | None = None


class ToggleEnabledRequest(BaseModel):
    """Skill/Action 启用状态变更请求。"""

    enabled: bool


class SwitchModelRequest(BaseModel):
    """切换当前模型请求。"""

    model_name: str


def _ensure_session_id(session_id: str | None = None) -> str:
    """确保本次请求拥有可用的 session_id。"""
    session = create_session(session_id)
    return str(session["session_id"])


def _build_session_analysis_payload(
    response_payload: dict,
    session_id: str,
) -> dict:
    """构造会话中存储的最近一次分析结果。"""
    result = dict(response_payload.get("result") or {})
    result.pop("intermediate", None)
    first_message = {}
    messages = response_payload.get("messages") or []
    if isinstance(messages, list) and messages:
        first_message = dict(messages[0] or {})
    return {
        "session_id": session_id,
        "message": response_payload.get("message"),
        "reply": response_payload.get("reply") or response_payload.get("llm_explanation"),
        "saved_file": response_payload.get("saved_file"),
        "result": result,
        "professional_analysis": dict(response_payload.get("professional_analysis") or {}),
        "model_info": dict(response_payload.get("model_info") or {}),
        "experiment_metadata": dict(response_payload.get("experiment_metadata") or {}),
        "llm_explanation": response_payload.get("llm_explanation"),
        "llm_error": response_payload.get("llm_error"),
        "report": dict(response_payload.get("report") or {}) if response_payload.get("report") else None,
        "web_urls": dict(response_payload.get("web_urls") or {}),
        "warnings": list(response_payload.get("warnings") or []),
        "skill_name": response_payload.get("skill_name"),
        "action_name": response_payload.get("action_name"),
        "result_kind": response_payload.get("result_kind") or first_message.get("result_kind"),
        "analysis": dict(first_message.get("analysis") or response_payload.get("analysis") or {}),
        "data": dict(response_payload.get("data") or {}),
        "errors": list(response_payload.get("errors") or []),
    }


def _as_bool(value) -> bool:
    """把表单或 JSON 中的布尔值安全转换为 bool。"""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_uploaded_filename(file_name: str) -> str:
    """清理上传文件名，避免路径穿越和危险字符。"""
    safe_name = Path(file_name or "").name
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5._-]+", "_", Path(safe_name).stem).strip("._-")
    if not stem:
        stem = "uploaded"
    suffix = Path(safe_name).suffix.lower()
    if suffix and len(suffix) <= 16:
        return f"{stem}{suffix}"
    return stem


async def _save_uploaded_attachment(
    file: UploadFile,
    user_id: str | None = None,
    conversation_id: str | None = None,
) -> Path:
    """保存 Agent 上传的任意附件；有 workspace 时优先保存到 workspace/uploads。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供上传文件名。")

    if conversation_id:
        try:
            info = await workspace_manager.save_upload_file(user_id or DEFAULT_USER_ID, conversation_id, file)
            return PROJECT_ROOT / info["path"]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    ensure_dirs()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_uploaded_filename(file.filename)
    suffix = Path(safe_name).suffix.lower() or Path(file.filename).suffix.lower() or ".bin"
    target_path = UPLOAD_DIR / f"{Path(safe_name).stem}_{uuid4().hex[:8]}{suffix}"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空。")
    target_path.write_bytes(content)
    return target_path


def _workspace_path_payload(path: str | Path | None) -> dict | None:
    if not path:
        return None
    raw = str(path)
    name = Path(raw).name
    return {
        "filename": name,
        "path": raw,
    }


def _workspace_input_files(user_id: str, conversation_id: str, save_path: Path | None = None) -> list[dict]:
    active_files = workspace_manager.read_active_files(user_id, conversation_id)
    if save_path is None:
        return active_files[-5:]
    save_name = save_path.name
    matched = [item for item in active_files if item.get("filename") == save_name or item.get("path", "").endswith(save_name)]
    return matched or [_workspace_path_payload(save_path) or {}]


def _resolve_referenced_active_file(user_id: str, conversation_id: str, message: str) -> tuple[Path, dict] | None:
    text = str(message or "")
    if not any(marker in text for marker in ("刚才", "上次", "那个文件", "这个文件", "继续")):
        return None
    active_files = workspace_manager.read_active_files(user_id, conversation_id)
    if not active_files:
        return None
    for item in reversed(active_files):
        path = PROJECT_ROOT / str(item.get("path") or "")
        try:
            resolved = path.resolve()
        except Exception:
            continue
        if PROJECT_ROOT.resolve() in resolved.parents and resolved.exists() and resolved.is_file():
            return resolved, item
    return None


def _workspace_output_files(response_payload: dict) -> list[dict]:
    output_files: list[dict] = []
    for key in ("saved_file",):
        item = _workspace_path_payload(response_payload.get(key))
        if item:
            output_files.append(item)
    report = response_payload.get("report") or {}
    if isinstance(report, dict):
        for key in ("report_path", "report_markdown_path", "report_html_path"):
            item = _workspace_path_payload(report.get(key))
            if item:
                output_files.append(item)
    web_urls = response_payload.get("web_urls") or {}
    if isinstance(web_urls, dict):
        for value in (web_urls.get("figures") or {}).values() if isinstance(web_urls.get("figures"), dict) else []:
            item = _workspace_path_payload(value)
            if item:
                output_files.append(item)
    return output_files


def _start_task_trace(
    *,
    user_id: str,
    conversation_id: str,
    intent: str,
    input_message: str,
    input_files: list[dict] | None = None,
) -> tuple[dict, dict]:
    task = task_trace_manager.create_task(
        user_id=user_id,
        conversation_id=conversation_id,
        intent=intent,
        input_message=input_message,
        input_files=input_files or [],
    )
    step = task_trace_manager.add_step(
        task["task_id"],
        "识别任务类型",
        detail={"intent": intent},
    )
    task_trace_manager.finish_step(step["step_id"], detail={"intent": intent})
    return task, step


def _record_skill_trace(
    *,
    task_id: str,
    skill_name: str,
    ability_name: str | None,
    input_files: list[dict] | None,
    response_payload: dict,
    raw_result_summary: str | None = None,
) -> dict:
    select_step = task_trace_manager.add_step(
        task_id,
        "选择 Skill",
        detail={"skill_name": skill_name, "ability_name": ability_name},
    )
    task_trace_manager.finish_step(select_step["step_id"], detail={"skill_name": skill_name, "ability_name": ability_name})
    run_step = task_trace_manager.add_step(
        task_id,
        "执行 Skill",
        detail={"skill_name": skill_name, "ability_name": ability_name},
    )
    status = "success" if response_payload.get("success") else "failed"
    error_message = response_payload.get("error_message") or response_payload.get("llm_error")
    output_files = _workspace_output_files(response_payload)
    task_trace_manager.finish_step(
        run_step["step_id"],
        status=status,
        detail={"output_files": output_files},
        error_message=error_message,
    )
    return task_trace_manager.record_skill_run(
        task_id=task_id,
        skill_name=skill_name,
        ability_name=ability_name,
        input_files=input_files or [],
        output_files=output_files,
        status=status,
        error_message=error_message,
        raw_result_summary=raw_result_summary or response_payload.get("reply") or response_payload.get("llm_explanation"),
    )


def _update_workspace_summary(user_id: str, conversation_id: str, user_message: str, assistant_reply: str) -> None:
    existing = workspace_manager.read_context_summary(user_id, conversation_id).strip()
    recent = f"- 用户：{str(user_message or '')[:160]}\n- 助手：{str(assistant_reply or '')[:240]}"
    summary = (existing + "\n\n" + recent).strip() if existing else recent
    workspace_manager.update_context_summary(user_id, conversation_id, summary[-4000:])


def _finalize_workspace_response(
    response_payload: dict,
    *,
    user_id: str,
    conversation_id: str,
    user_message: str,
    assistant_reply: str,
    task_id: str | None = None,
) -> dict:
    model_info = dict(response_payload.get("model_info") or response_payload.get("llm_model_info") or {})
    if not model_info:
        model_info = _llm_model_info(user_id=user_id, conversation_id=conversation_id)
    if model_info:
        response_payload.setdefault("provider_id", model_info.get("provider"))
        response_payload.setdefault("model_id", model_info.get("model"))
        response_payload.setdefault("model_info", model_info)
    response_payload["conversation_id"] = conversation_id
    response_payload["session_id"] = conversation_id
    response_payload.setdefault("used_skill", bool(response_payload.get("skill_name")))
    workspace_manager.append_message(
        user_id,
        conversation_id,
        "assistant",
        assistant_reply,
        metadata={"task_id": task_id, "source": response_payload.get("source")},
    )
    _update_workspace_summary(user_id, conversation_id, user_message, assistant_reply)
    response_payload.setdefault("workspace", {})
    response_payload["workspace"].update(
        {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "session_id": conversation_id,
            "task_id": task_id,
        }
    )
    return response_payload


def _normalize_prediction_result_for_chat(raw_result: dict) -> dict:
    """把预测结果整理成聊天接口和旧上下文都能理解的字段风格。"""
    result = dict(raw_result or {})
    if "final_prediction" not in result and result.get("fusion_prediction") is not None:
        result["final_prediction"] = result.get("fusion_prediction")
    if "figure_paths" not in result:
        result["figure_paths"] = dict(result.get("figures") or {})
    return result


def _build_chat_messages_payload(
    *,
    session_id: str,
    role_type: str,
    content: str,
    analysis: dict | None = None,
    skill_name: str | None = None,
    action_name: str | None = None,
    result_kind: str | None = None,
    skill_mode: str | None = None,
) -> dict:
    """生成统一的聊天消息数组返回结构。"""
    return {
        "session_id": session_id,
        "messages": [
            {
                "role": "assistant",
                "type": role_type,
                "content": content,
                "skill_name": skill_name,
                "action_name": action_name,
                "result_kind": result_kind,
                "skill_mode": skill_mode,
                "analysis": analysis,
            }
        ],
    }


def _compact_last_analysis(last_analysis: dict | None) -> dict | None:
    """把 last_analysis 压缩成前端调试可展示的简要版本。"""
    if not isinstance(last_analysis, dict) or not last_analysis:
        return None
    result = dict(last_analysis.get("result") or {})
    data = dict(last_analysis.get("data") or {})
    return {
        "skill_name": last_analysis.get("skill_name"),
        "action_name": last_analysis.get("action_name"),
        "saved_file": last_analysis.get("saved_file"),
        "reply": last_analysis.get("reply") or last_analysis.get("llm_explanation"),
        "summary": str(last_analysis.get("llm_explanation") or last_analysis.get("reply") or "")[:240],
        "result_kind": last_analysis.get("result_kind"),
        "final_prediction": result.get("final_prediction"),
        "unit": result.get("unit") or data.get("unit"),
        "report": last_analysis.get("report"),
    }


def _build_session_memory_response(session_id: str) -> dict:
    """返回当前 session 的简要记忆信息。"""
    session = get_session(session_id)
    if session is None:
        return {
            "session_id": session_id,
            "summary": "",
            "last_analysis": None,
            "task_state": None,
            "message_count": 0,
            "updated_at": None,
        }
    task_state = get_task_state(session_id) or {}
    return {
        "session_id": session_id,
        "title": session.get("title"),
        "summary": session.get("summary") or "",
        "last_analysis": _compact_last_analysis(session.get("last_analysis")),
        "task_state": task_state,
        "task_state_view": build_task_state_response(session_id),
        "message_count": int(session.get("message_count") or 0),
        "updated_at": session.get("updated_at"),
        "last_file": session.get("last_file"),
        "last_report": session.get("last_report"),
    }


def _apply_task_state_from_response(session_id: str, response: dict) -> None:
    """根据当前回复结果更新会话任务状态。"""
    if not session_id or not isinstance(response, dict):
        return

    task_state = get_task_state(session_id) or {}
    steps_done = dict(task_state.get("steps_done") or {})
    pipeline = list(task_state.get("pipeline") or [])
    action_name = str(response.get("action_name") or "").strip()
    skill_name = str(response.get("skill_name") or "").strip()
    skill_mode = str(response.get("skill_mode") or "").strip()
    result_kind = str(response.get("result_kind") or "").strip()
    data = dict(response.get("data") or {})
    saved_file = str(response.get("saved_file") or data.get("file_path") or "").strip()
    model_info = dict(response.get("model_info") or {})
    model_version = str(model_info.get("model_version") or data.get("model_version") or "").strip()

    if action_name and action_name not in pipeline:
        pipeline.append(action_name)
    if skill_name and skill_name not in pipeline:
        pipeline.append(skill_name)

    patch: dict[str, object] = {
        "current_task": task_state.get("current_task") or ("document_analysis" if skill_mode == "prompt_only" else "raman_analysis" if skill_name == "raman_spectroscopy_skill" else task_state.get("current_task")),
        "current_file": saved_file or task_state.get("current_file"),
        "selected_skill": skill_name or task_state.get("selected_skill"),
        "selected_action": action_name or task_state.get("selected_action"),
        "selected_model": model_version or task_state.get("selected_model"),
        "pipeline": pipeline,
        "steps_done": steps_done,
    }

    if response.get("success"):
        if skill_mode == "prompt_only":
            steps_done["uploaded"] = True
            steps_done["explained"] = True
        if skill_name == "raman_spectroscopy_skill" and action_name == "predict_methanol_concentration":
            steps_done["uploaded"] = True
            steps_done["preprocessed"] = True
            steps_done["predicted"] = True
            if response.get("llm_explanation") or response.get("reply"):
                steps_done["explained"] = True
            if response.get("report") or data.get("report_path"):
                steps_done["reported"] = True
        if action_name in {"explain_result", "explain_prediction"}:
            steps_done["explained"] = True
        if action_name in {"generate_report", "generate_markdown_report", "generate_experiment_record", "export_report"} or response.get("report"):
            steps_done["reported"] = True
        if action_name == "find_similar_history":
            steps_done["compared_history"] = True
        if action_name in {"predict_methanol_concentration", "run_uploaded_skill"} and skill_name != "raman_spectroscopy_skill":
            steps_done["uploaded"] = True

    if response.get("report"):
        patch["last_report"] = response.get("report")
    if skill_name == "raman_spectroscopy_skill" and action_name == "predict_methanol_concentration":
        result = dict(data.get("result") or response.get("result") or {})
        patch["last_prediction"] = {
            "final_prediction": result.get("final_prediction"),
            "unit": result.get("unit"),
            "sample_file": result.get("sample_file") or saved_file,
            "model_name": model_info.get("model_name") or data.get("model_name"),
            "model_version": model_version,
        }

    patch["steps_done"] = steps_done
    try:
        update_task_state(session_id, patch)
    except Exception:
        logger.exception("更新 session task_state 失败: session_id=%s skill=%s action=%s", session_id, skill_name, action_name)


def _attach_source(payload: dict, source: str, route_info: dict | None = None, debug: bool = False) -> dict:
    payload["source"] = source
    if debug and route_info:
        payload["route_info"] = route_info
    return payload


def _build_analysis_message(response_payload: dict) -> dict:
    """把分析结果整理成聊天消息中的 analysis 结构。"""
    result = dict(response_payload.get("result") or {})
    model_info = dict(response_payload.get("model_info") or {})
    metadata = dict(response_payload.get("experiment_metadata") or {})
    plots = [
        str(url)
        for url in (response_payload.get("web_urls", {}).get("figures", {}) or {}).values()
        if url
    ]
    return {
        "result_kind": "prediction",
        "predicted_value": result.get("final_prediction"),
        "unit": result.get("unit"),
        "model_name": model_info.get("model_name"),
        "model_version": model_info.get("model_version"),
        "summary": response_payload.get("llm_explanation") or response_payload.get("message") or "分析完成。",
        "details": {
            "sample_file": result.get("sample_file"),
            "sample_info": metadata,
            "confidence": result.get("confidence", {}) or {},
            "model_disagreement": result.get("model_disagreement", {}) or {},
            "professional_analysis": response_payload.get("professional_analysis", {}) or {},
            "structured_explanation": (response_payload.get("structured_explanation") or {}),
            "explanation_text": response_payload.get("llm_explanation"),
            "saved_file": response_payload.get("saved_file"),
            "report": response_payload.get("report", {}) or {},
        },
        "plots": plots,
    }


def _build_preprocessing_analysis(skill_result: dict, message: str, save_path: str | None = None) -> dict:
    """构造预处理结果卡片数据。"""
    data = dict(skill_result.get("data") or {})
    plot_items = []
    for item in data.get("plots") or []:
        if isinstance(item, dict) and item.get("url"):
            plot_items.append(item)
    return {
        "result_kind": "preprocessing",
        "summary": skill_result.get("summary") or message,
        "steps": list(data.get("steps") or []),
        "input_file": data.get("input_file") or save_path,
        "output_file": data.get("output_file"),
        "output_file_url": data.get("output_file_url"),
        "plots": plot_items,
        "metrics": dict(data.get("metrics") or {}),
        "warnings": list(data.get("warnings") or []),
    }


def _build_prediction_analysis(skill_result: dict, message: str) -> dict:
    """构造预测结果卡片数据。"""
    data = dict(skill_result.get("data") or {})
    plots = [str(item) for item in (skill_result.get("plots") or []) if item]
    return {
        "result_kind": "prediction",
        "predicted_value": data.get("predicted_value"),
        "unit": data.get("unit"),
        "model_name": data.get("model_name"),
        "model_version": data.get("model_version"),
        "summary": skill_result.get("summary") or message,
        "details": {
            "sample_file": data.get("result", {}).get("sample_file"),
            "confidence": data.get("confidence", {}) or {},
            "model_disagreement": data.get("model_disagreement", {}) or {},
            "pipeline": data.get("pipeline", []) or [],
            "structured_explanation": data.get("structured_explanation", {}) or {},
            "explanation_text": data.get("explanation"),
        },
        "plots": plots,
    }


def _build_model_status_analysis(skill_result: dict) -> dict:
    """构造模型状态卡片数据。"""
    data = dict(skill_result.get("data") or {})
    return {
        "result_kind": "model_status",
        "summary": skill_result.get("summary"),
        "model_name": data.get("model_name"),
        "model_version": data.get("model_version"),
        "health_status": "healthy" if skill_result.get("success") else "warning",
        "model_file_status": "正常" if not data.get("missing_files") else f"缺失 {len(data.get('missing_files') or [])} 个文件",
        "details": {
            "artifact_dir": data.get("artifact_dir"),
            "missing_files": list(data.get("missing_files") or []),
            "existing_files": list(data.get("existing_files") or []),
            "fallback_files": list(data.get("fallback_files") or []),
            "warnings": list(data.get("warnings") or []),
            "loadable": data.get("loadable"),
        },
    }


def _build_report_analysis(skill_result: dict) -> dict:
    """构造报告结果卡片数据。"""
    data = dict(skill_result.get("data") or {})
    return {
        "result_kind": "report",
        "summary": skill_result.get("summary"),
        "report_path": data.get("report_path") or data.get("report_markdown_path"),
        "report_preview": data.get("summary"),
        "export_status": "ready" if skill_result.get("success") else "failed",
        "details": data,
    }


def _build_generic_skill_analysis(skill_result: dict, message: str, extra_details: dict | None = None) -> dict:
    """把任意 SkillResult 整理成聊天 analysis 结构。"""
    data = dict(skill_result.get("data") or {})
    extra_details = dict(extra_details or {})
    return {
        "result_kind": "generic",
        "summary": skill_result.get("summary") or message,
        "details": {
            **extra_details,
            **data,
        },
    }


def _resolve_result_kind(skill_name: str | None, action_name: str | None) -> str:
    if action_name == "run_uploaded_skill":
        return "uploaded_skill"
    if skill_name == "raman_spectroscopy_skill" and action_name in {
        "sg_smoothing",
        "normalization",
        "als_baseline_correction",
        "baseline_subtraction",
        "cdae_denoise",
        "cae_baseline_prediction",
        "resample_wavenumber_axis",
        "full_preprocess_pipeline",
    }:
        return "preprocessing"
    if skill_name == "raman_spectroscopy_skill" and action_name in {
        "predict_methanol_concentration",
        "explain_prediction",
        "get_model_info",
        "check_prediction_input",
    }:
        return "prediction"
    if skill_name == "agent_system_skill" and action_name in {"current_model", "model_health_check"}:
        return "model_status"
    if skill_name == "raman_spectroscopy_skill" and action_name in {
        "generate_summary",
        "generate_markdown_report",
        "generate_experiment_record",
        "export_report",
    }:
        return "report"
    return "generic"


def _resolve_uploaded_skill_mode(skill_name: str | None) -> str:
    skill = get_skill(skill_name or "")
    if skill is None:
        return "executable"
    return str(getattr(skill, "skill_mode", "executable") or "executable")


def _build_skill_analysis_payload(
    skill_name: str,
    action_name: str | None,
    skill_result: dict,
    message: str,
    save_path: str | None = None,
    extra_details: dict | None = None,
) -> dict:
    result_kind = _resolve_result_kind(skill_name, action_name)
    if result_kind == "preprocessing":
        return _build_preprocessing_analysis(skill_result, message=message, save_path=save_path)
    if result_kind == "prediction":
        return _build_prediction_analysis(skill_result, message=message)
    if result_kind == "model_status":
        return _build_model_status_analysis(skill_result)
    if result_kind == "report":
        return _build_report_analysis(skill_result)
    if result_kind == "uploaded_skill":
        return _build_generic_skill_analysis(skill_result, message=skill_result.get("data", {}).get("reply_text") or message, extra_details=extra_details)
    return _build_generic_skill_analysis(skill_result, message=message, extra_details=extra_details)


def _format_skill_list_summary(skills_payload: dict) -> str:
    """把大 Skill 列表压缩成聊天可读摘要。"""
    names = [item.get("display_name") or item.get("name") for item in (skills_payload.get("skills") or [])]
    if not names:
        return "当前还没有可展示的 Skill。"
    uploaded = [item for item in (skills_payload.get("skills") or []) if item.get("source") == "uploaded"]
    return (
        f"当前共发现 {len(names)} 个大 Skill，"
        f"其中上传 Skill {len(uploaded)} 个。"
        + (" 已发现的能力包括：" + "、".join(str(name) for name in names) + "。" if names else "")
    )


def _match_builtin_skill(message: str, has_file: bool = False, file_suffix: str | None = None) -> tuple[str | None, str | None, dict | None]:
    """内置 Skill 的保底映射，避免把普通对话误导到错误模板。"""
    text = str(message or "").strip().lower()
    raw_text = str(message or "").strip()

    if any(keyword in raw_text for keyword in ("有哪些技能", "技能列表", "当前技能", "当前能力", "已安装技能")) or "list skills" in text:
        return "agent_system_skill", "list_skills", {"route": "builtin_skill_rule", "reason": "explicit_skill_inventory"}
    if "当前模型" in raw_text or "检查模型" in raw_text or "模型状态" in raw_text:
        return None, None, {"route": "service_system_info", "reason": "model_query"}
    if "上传帮助" in raw_text:
        return "agent_system_skill", "upload_help", {"route": "builtin_skill_rule", "reason": "upload_help"}
    if "最近实验" in raw_text or "最近记录" in raw_text:
        return "agent_system_skill", "recent_experiments", {"route": "builtin_skill_rule", "reason": "recent_experiments"}
    if "清空会话" in raw_text:
        return "agent_system_skill", "clear_session", {"route": "builtin_skill_rule", "reason": "clear_session"}

    if _looks_like_knowledge_question(raw_text) and not _has_explicit_execution_intent(raw_text):
        return None, None, {"route": "builtin_skill_rule", "reason": "knowledge_question_skip_skill"}

    if any(keyword in raw_text for keyword in ("预处理", "平滑", "去噪", "基线", "归一化")) and (has_file or _has_explicit_execution_intent(raw_text)):
        return "raman_spectroscopy_skill", "full_preprocess_pipeline", {"route": "builtin_skill_rule", "reason": "preprocess"}
    if any(keyword in raw_text for keyword in ("画图", "可视化", "光谱图")) and (has_file or _has_explicit_execution_intent(raw_text)):
        return "raman_spectroscopy_skill", "plot_prediction_result", {"route": "builtin_skill_rule", "reason": "visualization"}
    if any(keyword in raw_text for keyword in ("报告", "生成报告", "实验记录")) and (has_file or _has_explicit_execution_intent(raw_text)):
        return "raman_spectroscopy_skill", "generate_markdown_report", {"route": "builtin_skill_rule", "reason": "report"}
    if has_file and str(file_suffix or "").lower() == ".csv":
        return "raman_spectroscopy_skill", "predict_methanol_concentration", {"route": "builtin_skill_rule", "reason": "file_prediction_default"}
    if any(keyword in raw_text for keyword in ("甲醇", "分析这个光谱", "分析这个拉曼", "预测")) and (has_file or _has_explicit_execution_intent(raw_text)):
        return "raman_spectroscopy_skill", "predict_methanol_concentration", {"route": "builtin_skill_rule", "reason": "prediction"}
    return None, None, None


def _looks_like_knowledge_question(message: str) -> bool:
    """仅询问概念/方法时不要触发 Skill 执行。"""
    raw_text = str(message or "").strip()
    lowered = raw_text.lower()
    knowledge_markers = (
        "有哪些",
        "是什么",
        "什么是",
        "区别",
        "原理",
        "为什么",
        "怎么理解",
        "如何理解",
        "介绍",
        "解释一下",
        "报告怎么写",
        "一般用什么",
        "适合什么",
        "方法",
    )
    return any(marker in raw_text for marker in knowledge_markers) or any(
        marker in lowered for marker in ("what is", "how to", "why", "difference")
    )


def _has_explicit_execution_intent(message: str) -> bool:
    """判断是否明确指向文件、刚才结果或实际执行动作。"""
    raw_text = str(message or "").strip()
    lowered = raw_text.lower()
    execution_markers = (
        "这个文件",
        "刚才",
        "上传",
        "csv",
        "样品",
        "帮我",
        "对这个",
        "把这个",
        "执行",
        "进行",
        "处理",
        "生成刚才",
        "分析这个",
        "继续",
    )
    return any(marker in raw_text for marker in execution_markers) or any(
        marker in lowered for marker in ("this file", "uploaded", "csv", "run", "execute")
    )


def _infer_document_task_type(message: str, file_suffix: str | None = None) -> str:
    """根据用户问题推断文档 skill 的任务类型。"""
    text = str(message or "").strip().lower()
    normalized = str(message or "").strip()
    if any(keyword in normalized for keyword in ("切块", "分块", "rag")):
        return "rag_chunk"
    if any(keyword in normalized for keyword in ("阅读理解", "真题", "考试", "题目")):
        return "exam_reading_extract"
    if any(keyword in normalized for keyword in ("讲稿", "ppt")):
        return "ppt_script"
    if any(keyword in normalized for keyword in ("论文", "精读")):
        return "paper_reading"
    if any(keyword in normalized for keyword in ("翻译", "对照", "总结", "摘要", "整理", "分析")):
        return "extract"
    if str(file_suffix or "").lower() in {".txt", ".md", ".pdf", ".docx", ".pptx"}:
        return "extract"
    if "translate" in text or "summar" in text:
        return "extract"
    return "extract"


def _looks_like_generic_file_task(message: str) -> bool:
    normalized = str(message or "").strip().lower()
    keywords = (
        "文档",
        "文本",
        "总结",
        "摘要",
        "审查",
        "审阅",
        "配置",
        "日志",
        "关键信息",
        "关键点",
        "清单",
        "目录",
        "结构",
        "提取",
        "表格",
        "画像",
        "转换",
        "对比",
        "比较",
        "压缩包",
        "归档",
        "文件处理",
        "inventory",
        "extract",
        "profile",
        "convert",
        "compare",
        "archive",
        "csv",
        "tsv",
        "xlsx",
        "json",
        "yaml",
        "xml",
        "markdown",
        "project",
    )
    return any(keyword in normalized for keyword in keywords)


def _looks_like_data_analysis_task(message: str) -> bool:
    normalized = str(message or "").strip().lower()
    keywords = tuple(str(keyword).strip().lower() for keyword in DATA_ANALYSIS_MESSAGE_KEYWORDS) + (
        "数据分析",
        "字段统计",
        "表格统计",
        "表格分析",
        "数据汇总",
        "表格内容",
        "重复行",
        "重复值",
        "数据质量",
        "缺失值",
        "平均值",
        "最大值",
        "最小值",
        "分类统计",
    )
    return any(keyword in normalized for keyword in keywords)


def _looks_like_raman_file_task(message: str) -> bool:
    normalized = str(message or "").strip().lower()
    keywords = tuple(str(keyword).strip().lower() for keyword in RAMAN_MESSAGE_KEYWORDS)
    return any(keyword in normalized for keyword in keywords)


def _infer_table_skill_route(message: str, file_path: str | Path | None = None, file_suffix: str | None = None) -> tuple[str | None, str | None, dict | None]:
    normalized = str(message or "").strip().lower()
    suffix = str(file_suffix or "").lower()
    if not _is_table_file_suffix(suffix):
        return None, None, None

    if _looks_like_raman_file_task(message):
        return "raman_spectroscopy_skill", "predict_methanol_concentration", {"route": "table_raman_route", "reason": "raman_message_keywords"}

    if _looks_like_data_analysis_task(message):
        if get_skill("data-analysis-skill") is not None:
            return "data-analysis-skill", infer_data_analysis_action(message, default_action="summarize_table"), {"route": "table_data_analysis_route", "reason": "data_analysis_message_keywords"}
        return None, None, {"route": "data_analysis_missing_skill", "reason": "data_analysis_skill_not_enabled"}

    table_signal = detect_raman_table_signal(file_path) if file_path else {"is_raman": False, "reason": "no_file_path", "matched_hints": []}
    if table_signal.get("is_raman"):
        return "raman_spectroscopy_skill", "predict_methanol_concentration", {
            "route": "table_raman_route",
            "reason": f"raman_table_signal:{table_signal.get('reason')}",
        }

    if get_skill("data-analysis-skill") is not None:
        return "data-analysis-skill", infer_data_analysis_action(message, default_action="summarize_table"), {
            "route": "table_data_analysis_route",
            "reason": f"default_table_analysis:{table_signal.get('reason')}",
        }
    return None, None, {"route": "data_analysis_missing_skill", "reason": "data_analysis_skill_not_enabled"}


def _select_skill_route(
    message: str,
    has_file: bool = False,
    file_suffix: str | None = None,
    file_path: str | Path | None = None,
) -> tuple[str | None, str | None, dict | None]:
    file_suffix = str(file_suffix or "").lower()
    if not has_file and _looks_like_knowledge_question(message) and not _has_explicit_execution_intent(message):
        return None, None, {"route": "knowledge_question_skip_skill", "reason": "no_file_no_execution_intent"}
    if has_file and _is_image_file_suffix(file_suffix):
        if get_skill("image-router-skill") is not None:
            return "image-router-skill", "classify_image_type", {"route": "builtin_skill_rule", "reason": f"image_router:{file_suffix}"}
        return None, None, {"route": "image_router_missing_skill", "reason": f"image_suffix:{file_suffix}"}
    if has_file and _is_table_file_suffix(file_suffix):
        return _infer_table_skill_route(message, file_path=file_path, file_suffix=file_suffix)
    uploaded_skill, route_info = match_uploaded_skill(message, file_suffix=file_suffix)
    if uploaded_skill is not None:
        return uploaded_skill.name, "run_uploaded_skill", route_info
    if has_file and file_suffix and not _is_table_file_suffix(file_suffix):
        return None, None, {"route": "no_matching_file_skill", "reason": f"unsupported_suffix:{file_suffix}"}
    return _match_builtin_skill(message, has_file=has_file, file_suffix=file_suffix)


def _build_no_matching_file_skill_response(
    *,
    session_id: str,
    save_path: Path,
    message: str,
    file_suffix: str,
    route_info: dict | None = None,
    debug: bool = False,
) -> dict:
    route = str((route_info or {}).get("route") or "").strip()
    if route == "image_router_missing_skill" or _is_image_file_suffix(file_suffix):
        content = IMAGE_ROUTER_MISSING_MESSAGE
    elif route == "data_analysis_missing_skill" or _is_table_file_suffix(file_suffix):
        content = DATA_ANALYSIS_MISSING_MESSAGE
    else:
        content = f"当前没有匹配到可处理 `{file_suffix or '该类型'}` 文件的 Skill。请上传支持该类型的文档 Skill，或调整现有 Skill 的 manifest 声明。"
    response = _attach_source({
        "success": False,
        "session_id": session_id,
        "reply": content,
        "error_message": content,
        "message": message,
        "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
        "category": "tool",
        **_build_chat_messages_payload(
            session_id=session_id,
            role_type="error",
            content=content,
            analysis=None,
        ),
    }, "fallback", route_info=route_info, debug=debug)
    return response


def _is_service_run_tool_overridden() -> bool:
    """兼容旧测试/旧插件：只有 run_tool 被实例级替换时才走旧工具链。"""
    return getattr(service.run_tool, "__self__", None) is not service


def _analyze_csv_with_service_tools(
    *,
    save_path: Path,
    message: str,
    session_id: str,
    metadata: dict | None = None,
) -> dict:
    """兼容旧版 analyze-file 测试替身的 service 工具链。"""
    metadata = dict(metadata or {})
    saved_file = str(save_path.relative_to(PROJECT_ROOT))
    prediction_output = service.run_tool("predict_methanol", {"file_path": str(save_path), "debug": False})
    result = _normalize_prediction_result_for_chat(prediction_output.get("result", {}) or {})
    if not prediction_output.get("success") or not result:
        content = "预测结果无效，暂不生成大模型解释。"
        return _attach_source({
            "success": False,
            "session_id": session_id,
            "message": message,
            "saved_file": saved_file,
            "result": None,
            "professional_analysis": {},
            "model_info": {},
            "llm_model_info": _llm_model_info(conversation_id=session_id),
            "experiment_metadata": metadata,
            "llm_explanation": content,
            "llm_error": prediction_output.get("error_message"),
            "report": None,
            "web_urls": {"figures": {}, "report_view": "", "report_download": ""},
            "warnings": list(prediction_output.get("warnings") or []),
            "error_message": prediction_output.get("error_message") or content,
            **_build_chat_messages_payload(
                session_id=session_id,
                role_type="error",
                content=content,
                analysis=None,
                skill_name="raman_spectroscopy_skill",
                action_name="predict_methanol_concentration",
                result_kind="prediction",
            ),
        }, "legacy_service_tool")

    raw_result = prediction_output.get("raw_result")
    if isinstance(raw_result, dict) and raw_result:
        result["raw_result"] = raw_result
    professional = service.run_tool(
        "professional_spectral_analysis",
        {"csv_path": str(save_path), "prediction_result": result},
    )
    if not professional.get("success"):
        professional = {}
    model_response = model_registry_service.get_current_model()
    model_info = model_response.get("data", {}) if model_response.get("success") else {}
    explain_result = service.run_tool(
        "explain_result",
        {
            "result": result,
            "professional_analysis": professional,
            "model_info": model_info,
            "experiment_metadata": metadata,
        },
    )
    llm_explanation = explain_result.get("explanation") or "分析完成。"
    report_response = service.run_tool(
        "generate_report",
        {
            "result": result,
            "llm_explanation": llm_explanation,
            "professional_analysis": professional,
            "model_info": model_info,
            "experiment_metadata": metadata,
        },
    )
    report = {
        "report_path": report_response.get("report_path"),
        "report_file": report_response.get("report_file"),
    } if report_response.get("success") else None
    web_urls = {
        "figures": build_figure_web_urls(result.get("figure_paths", {}) or {}),
        **build_report_web_urls(report or {}),
    }
    response_payload = {
        "success": True,
        "session_id": session_id,
        "message": message,
        "saved_file": saved_file,
        "result": result,
        "professional_analysis": professional,
        "model_info": model_info,
        "llm_model_info": _llm_model_info(conversation_id=session_id),
        "experiment_metadata": metadata,
        "llm_explanation": llm_explanation,
        "llm_error": explain_result.get("error_message"),
        "report": report,
        "web_urls": web_urls,
        "warnings": list(prediction_output.get("warnings") or []),
        "skill_name": "raman_spectroscopy_skill",
        "action_name": "predict_methanol_concentration",
        "error_message": None,
    }
    try:
        response_payload["history"] = save_analysis_history(
            {
                "saved_file": saved_file,
                "result": result,
                "llm_explanation": llm_explanation,
                "report": report or {},
                "web_urls": web_urls,
                "professional_analysis": professional,
                "model_info": model_info,
                "experiment_metadata": metadata,
            }
        )
    except Exception as exc:
        response_payload["history_error"] = str(exc)
        response_payload["warnings"].append(str(exc))
    analysis_message = _build_analysis_message(response_payload)
    response_payload.update(
        _build_chat_messages_payload(
            session_id=session_id,
            role_type="analysis",
            content=analysis_message["summary"],
            analysis=analysis_message,
            skill_name="raman_spectroscopy_skill",
            action_name="predict_methanol_concentration",
            result_kind="prediction",
        )
    )
    return _attach_source(response_payload, "legacy_service_tool")


def _analyze_uploaded_file_with_skills(
    *,
    save_path: Path,
    message: str,
    session_id: str,
    metadata: dict | None = None,
    debug: bool = False,
) -> dict:
    """使用 Skill 层驱动表格/CSV 分析，并返回统一的聊天分析结果。"""
    metadata = dict(metadata or {})
    warnings: list[str] = []
    target_skill_name, target_action_name, route_info = _select_skill_route(
        message,
        has_file=True,
        file_suffix=save_path.suffix.lower(),
        file_path=save_path,
    )
    if route_info and route_info.get("route") in {"data_analysis_missing_skill", "image_router_missing_skill"}:
        content = _build_no_matching_file_skill_response(
            session_id=session_id,
            save_path=save_path,
            message=message,
            file_suffix=save_path.suffix.lower(),
            route_info=route_info,
            debug=debug,
        )
        return content
    if target_skill_name is None or target_action_name is None:
        return _build_no_matching_file_skill_response(
            session_id=session_id,
            save_path=save_path,
            message=message,
            file_suffix=save_path.suffix.lower(),
            route_info=route_info,
            debug=debug,
        )

    loader_result = None
    if target_skill_name == "raman_spectroscopy_skill":
        loader_skill = get_skill("raman_spectroscopy_skill")
        if loader_skill is None:
            return {
                "success": False,
                "session_id": session_id,
                "message": message,
                "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
                "error_message": "Skill 注册表未正确初始化，无法执行 Raman 文件分析。",
            }
        loader_result = loader_skill.run(file_path=str(save_path), action_name="inspect_spectrum")
        if not loader_result.success:
            error_message = "；".join(loader_result.errors) or loader_result.summary
            return {
                "success": False,
                "session_id": session_id,
                "message": message,
                "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
                "reply": error_message,
                "skill_name": "raman_spectroscopy_skill",
                "action_name": "inspect_spectrum",
                "error_message": error_message,
                **_build_chat_messages_payload(
                    session_id=session_id,
                    role_type="error",
                    content=error_message,
                    analysis=None,
                    skill_name="raman_spectroscopy_skill",
                    action_name="inspect_spectrum",
                ),
            }

    skill_result = execute_skill(
        target_skill_name,
        action_name=target_action_name,
        file_path=str(save_path),
        metadata=metadata,
        include_intermediate=debug,
        session_id=session_id,
        message=message,
        original_message=message,
    )
    if not skill_result.success:
        error_message = "；".join(skill_result.errors) or skill_result.summary
        if target_skill_name == "data-analysis-skill" and any("子能力" in str(item) and "当前已禁用" in str(item) for item in (skill_result.errors or [])):
            error_message = f"当前表格已识别到需要调用 `{target_action_name}`，但这个子能力目前被禁用了。你可以先在 Skill 管理页面重新启用它。"
        elif target_skill_name == "data-analysis-skill" and any("当前已禁用" in str(item) for item in (skill_result.errors or [])):
            error_message = DATA_ANALYSIS_MISSING_MESSAGE
        elif target_skill_name == "raman_spectroscopy_skill" and any("当前已禁用" in str(item) for item in (skill_result.errors or [])):
            error_message = RAMAN_SKILL_DISABLED_MESSAGE
        return {
            "success": False,
            "session_id": session_id,
            "message": message,
            "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
            "reply": error_message,
            "skill_name": target_skill_name,
            "action_name": target_action_name,
            "error_message": error_message,
            **_build_chat_messages_payload(
                session_id=session_id,
                role_type="error",
                content=error_message,
                analysis=None,
                skill_name=target_skill_name,
                action_name=target_action_name,
                result_kind=_resolve_result_kind(target_skill_name, target_action_name),
            ),
        }

    model_health = execute_skill("agent_system_skill", action_name="model_health_check")
    model_info = dict(model_health.data or {})
    if model_health.errors:
        warnings.extend(model_health.errors)

    response_payload = {
        "success": True,
        "session_id": session_id,
        "message": message or "请分析这个甲醇拉曼光谱",
        "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
        "skill_name": target_skill_name,
        "action_name": target_action_name,
        "model_info": model_info,
        "llm_model_info": _llm_model_info(conversation_id=session_id),
        "experiment_metadata": metadata,
        "warnings": list(dict.fromkeys(warnings)),
        "skill_results": {
            target_skill_name: skill_result.to_dict(),
            "agent_system_skill": model_health.to_dict(),
        },
    }
    if loader_result is not None:
        response_payload["skill_results"]["raman_spectroscopy_skill.loader"] = loader_result.to_dict()

    # 甲醇分析仍然走完整旧链路，保证当前上传分析体验稳定。
    if target_skill_name == "raman_spectroscopy_skill" and target_action_name == "predict_methanol_concentration":
        result = _normalize_prediction_result_for_chat(skill_result.data.get("result", {}) or {})
        if not result:
            error_message = "预测 Skill 未返回有效结果。"
            return {
                "success": False,
                "session_id": session_id,
                "message": message,
                "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
                "reply": error_message,
                "skill_name": target_skill_name,
                "action_name": target_action_name,
                "error_message": error_message,
                "llm_model_info": _llm_model_info(conversation_id=session_id),
                **_build_chat_messages_payload(
                    session_id=session_id,
                    role_type="error",
                    content=error_message,
                    analysis=None,
                    skill_name=target_skill_name,
                    action_name=target_action_name,
                    result_kind="prediction",
                ),
            }

        professional_analysis = analyze_spectrum_professionally(save_path, result)
        if not professional_analysis.get("success"):
            warnings.append(professional_analysis.get("error_message") or "专业光谱分析失败。")
            professional_analysis = {}

        explain_result = explain_result_tool(
            result=result,
            professional_analysis=professional_analysis,
            model_info=model_info,
            experiment_metadata=metadata,
        )
        llm_explanation = explain_result.get("explanation") or "分析完成。"
        structured_explanation = explain_result.get("structured_explanation") or {}
        llm_error = explain_result.get("error_message")
        if llm_error and explain_result.get("success") is False:
            warnings.append(llm_error)

        report_response = generate_report_tool(
            result=result,
            llm_explanation=llm_explanation,
            professional_analysis=professional_analysis,
            model_info=model_info,
            experiment_metadata=metadata,
        )
        report = None
        if report_response.get("success"):
            report = {
                "report_id": report_response.get("report_id"),
                "created_at": report_response.get("created_at"),
                "summary": report_response.get("summary"),
                "report_path": report_response.get("report_path"),
                "report_file": report_response.get("report_file"),
                "report_markdown_path": report_response.get("report_markdown_path"),
                "report_markdown_file": report_response.get("report_markdown_file"),
                "report_html_path": report_response.get("report_html_path"),
                "report_html_file": report_response.get("report_html_file"),
            }
        else:
            warnings.append(report_response.get("error_message") or "报告生成失败。")

        web_urls = {
            "figures": build_figure_web_urls(result.get("figure_paths", {}) or {}),
            **build_report_web_urls(report or {}),
        }
        response_payload.update(
            {
                "result": result,
                "professional_analysis": professional_analysis,
                "llm_explanation": llm_explanation,
                "structured_explanation": structured_explanation,
                "llm_error": llm_error,
                "report": report,
                "web_urls": web_urls,
                "warnings": list(dict.fromkeys(warnings)),
                "route_info": route_info,
                "llm_model_info": _llm_model_info(conversation_id=session_id),
            }
        )
        try:
            response_payload["history"] = save_analysis_history(
                {
                    "saved_file": response_payload["saved_file"],
                    "result": result,
                    "llm_explanation": llm_explanation,
                    "report": report or {},
                    "web_urls": web_urls,
                    "professional_analysis": professional_analysis,
                    "model_info": model_info,
                    "experiment_metadata": metadata,
                }
            )
        except Exception as exc:
            response_payload["history_error"] = str(exc)
            warnings.append(str(exc))

        analysis_message = _build_analysis_message(response_payload)
        response_payload.update(
            _build_chat_messages_payload(
                session_id=session_id,
                role_type="analysis",
                content=analysis_message["summary"],
                analysis=analysis_message,
                skill_name=target_skill_name,
                action_name=target_action_name,
                result_kind="prediction",
            )
        )
        return _attach_source(response_payload, "skill_execution", route_info=route_info, debug=debug)

    skill_payload = skill_result.to_dict()
    generic_reply = str(
        skill_result.data.get("analysis_markdown")
        or skill_result.data.get("reply_text")
        or skill_result.summary
        or "表格分析完成。"
    )
    tool_info = dict(skill_result.data.get("tool_info") or {})
    if target_skill_name == "data-analysis-skill":
        tool_info.setdefault("source", "skill_execution")
        tool_info.setdefault("skill", target_skill_name)
        tool_info.setdefault("action", target_action_name)
        tool_info.setdefault("filename", save_path.name)
        tool_info.setdefault("rows", skill_result.data.get("metadata", {}).get("rows", ""))
        tool_info.setdefault("columns", skill_result.data.get("metadata", {}).get("columns", ""))
        tool_info.setdefault("sheet_name", skill_result.data.get("metadata", {}).get("sheet_name", ""))
        tool_info.setdefault("success", bool(skill_result.success))
        tool_info.setdefault("error", "；".join(skill_result.errors) if skill_result.errors else "")
        tool_info.setdefault("mode", "data_analysis")
    response_payload.update(
        {
            "result": skill_payload.get("data", {}),
            "professional_analysis": {},
            "reply": generic_reply,
            "llm_explanation": generic_reply,
            "llm_error": None,
            "report": None,
            "web_urls": {"figures": {}, "report_view": "", "report_download": ""},
            "warnings": list(dict.fromkeys(warnings + list(skill_result.errors))),
            "route_info": route_info,
            "tool_info": tool_info,
        }
    )
    analysis_message = _build_skill_analysis_payload(
        target_skill_name,
        target_action_name,
        skill_payload,
        message=generic_reply,
        save_path=response_payload["saved_file"],
        extra_details={"sample_info": metadata},
    )
    response_payload = {
        **response_payload,
        **_build_chat_messages_payload(
            session_id=session_id,
            role_type="text" if target_skill_name == "data-analysis-skill" else "analysis",
            content=generic_reply if target_skill_name == "data-analysis-skill" else analysis_message["summary"],
            analysis=analysis_message,
            skill_name=target_skill_name,
            action_name=target_action_name,
            result_kind=analysis_message.get("result_kind"),
        ),
    }
    return _attach_source(response_payload, "skill_execution", route_info=route_info, debug=debug)


@router.get("/skills")
def get_skills() -> dict:
    """返回当前对外展示的大 Skill 列表。"""
    try:
        return list_skills(include_actions=True)
    except Exception as exc:
        return {
            "total": 0,
            "enabled_count": 0,
            "available_count": 0,
            "skills": [],
            "error": f"Skill registry 初始化失败：{exc}",
        }


@router.post("/skills/upload")
async def upload_skill_zip(file: UploadFile = File(...)) -> dict:
    """上传 Skill zip 压缩包。"""
    filename = file.filename or ""
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持上传 .zip 格式的 Skill 压缩包。")
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="上传文件为空。")
        return save_uploaded_skill(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skill 上传失败：{exc}") from exc


@router.delete("/skills/{skill_name}")
def delete_skill(skill_name: str) -> dict:
    """删除一个已上传的 Skill。"""
    uploaded_items = list_uploaded_skills()
    normalized_target = _normalize_skill_key(skill_name)
    has_uploaded_record = any(
        str(item.get("source") or "") == "uploaded"
        and normalized_target
        and normalized_target
        in {
            _normalize_skill_key(item.get("name")),
            _normalize_skill_key(item.get("skill_name")),
            _normalize_skill_key(item.get("display_name")),
        }
        for item in uploaded_items
    )
    matched_skill = get_skill(skill_name)
    if matched_skill is not None and str(getattr(matched_skill, "source", "")) != "uploaded" and not has_uploaded_record:
        raise HTTPException(status_code=400, detail="仅支持删除已上传的 Skill，内置 Skill 不能删除。")
    try:
        return delete_uploaded_skill(skill_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skill 删除失败：{exc}") from exc


@router.patch("/skills/{skill_name}/enabled")
def patch_skill_enabled(skill_name: str, payload: ToggleEnabledRequest) -> dict:
    """启用或禁用大 Skill。"""
    if get_skill(skill_name) is None:
        raise HTTPException(status_code=404, detail=f"未找到 Skill: {skill_name}")
    try:
        return set_skill_enabled(skill_name, payload.enabled)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/skills/{skill_name}/actions/{action_name}/enabled")
def patch_action_enabled(skill_name: str, action_name: str, payload: ToggleEnabledRequest) -> dict:
    """启用或禁用子 action。"""
    if get_skill(skill_name) is None:
        raise HTTPException(status_code=404, detail=f"未找到 Skill: {skill_name}")
    if get_action(skill_name, action_name) is None:
        raise HTTPException(status_code=404, detail=f"未找到子能力: {skill_name}/{action_name}")
    try:
        return set_action_enabled(skill_name, action_name, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tools")
def get_tools() -> dict:
    """返回当前可用工具。"""
    return {
        "success": True,
        "available_tools": service.list_tools(),
        "available_skills": list_skills(include_actions=True),
    }


@router.get("/models")
def get_agent_models() -> dict:
    """返回当前 Agent 可选模型列表。"""
    result = model_registry_service.list_models_for_agent()
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error_message"])
    return result["data"]


@router.patch("/models/current")
def switch_agent_model(payload: SwitchModelRequest) -> dict:
    """切换当前 Agent 模型。"""
    result = model_registry_service.switch_current_model_for_agent(payload.model_name)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error_message"])
    reset_predictor_cache()
    return {
        "success": True,
        "current_model": result["current_model"],
        "message": result["message"],
        "warnings": result.get("warnings") or [],
    }


@router.post("/session/new")
def create_new_session() -> dict:
    """创建一个新的会话。"""
    session = create_session()
    return {
        "success": True,
        "session_id": session["session_id"],
    }


@router.get("/session/{session_id}")
def get_session_memory(session_id: str) -> dict:
    """读取当前会话的持久化记忆。"""
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="未找到对应的会话。")
    payload = _build_session_memory_response(session_id)
    payload["success"] = True
    return payload


@router.post("/session/{session_id}/clear")
def clear_session(session_id: str) -> dict:
    """清空当前会话的记忆内容。"""
    try:
        session = clear_session_memory(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = _build_session_memory_response(str(session.get("session_id") or session_id))
    payload["success"] = True
    payload["message"] = "当前会话记忆已清空。"
    return payload


@router.post("/chat")
async def chat(request: Request) -> dict:
    """统一聊天入口，支持 JSON 聊天和 FormData 文件分析。"""
    content_type = (request.headers.get("content-type") or "").lower()
    message = ""
    conversation_id = None
    user_id = DEFAULT_USER_ID
    debug = False
    uploaded_file = None
    metadata: dict[str, str | None] = {}
    provider_id: str | None = None
    model_id: str | None = None

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        message = str(form.get("message") or "").strip()
        conversation_id = str(form.get("conversation_id") or form.get("session_id") or "").strip() or None
        user_id = str(form.get("user_id") or DEFAULT_USER_ID).strip() or DEFAULT_USER_ID
        provider_id = str(form.get("provider_id") or "").strip() or None
        model_id = str(form.get("model_id") or "").strip() or None
        debug = _as_bool(form.get("debug"))
        uploaded_file = form.get("file")
        metadata = {
            "sample_name": str(form.get("sample_name") or "").strip() or None,
            "sample_type": str(form.get("sample_type") or "").strip() or None,
            "operator": str(form.get("operator") or "").strip() or None,
            "instrument": str(form.get("instrument") or "").strip() or None,
            "laser_power": str(form.get("laser_power") or "").strip() or None,
            "integration_time": str(form.get("integration_time") or "").strip() or None,
            "remarks": str(form.get("remark") or form.get("remarks") or "").strip() or None,
        }
    else:
        payload = await request.json()
        message = str(payload.get("message") or "").strip()
        conversation_id = payload.get("conversation_id") or payload.get("session_id")
        user_id = str(payload.get("user_id") or DEFAULT_USER_ID).strip() or DEFAULT_USER_ID
        provider_id = str(payload.get("provider_id") or "").strip() or None
        model_id = str(payload.get("model_id") or "").strip() or None
        debug = bool(payload.get("debug", False))

    resolved_session_id = _ensure_session_id(str(conversation_id).strip() if conversation_id else None)
    resolved_conversation_id = resolved_session_id
    workspace = workspace_manager.create_workspace(user_id, resolved_session_id)
    resolved_user_id = workspace["user_id"]
    effective_message = message or "请分析这个文件"
    user_memory = user_memory_manager.get_user_memory(resolved_user_id)
    workspace_manager.update_memory_snapshot(resolved_user_id, resolved_session_id, user_memory)
    workspace_context = workspace_manager.read_workspace_context(resolved_user_id, resolved_session_id)
    workspace_manager.append_message(
        resolved_user_id,
        resolved_session_id,
        "user",
        effective_message,
        metadata={
            "debug": debug,
            "has_file": uploaded_file is not None and bool(getattr(uploaded_file, "filename", "")),
            "context_summary_chars": len(workspace_context.get("context_summary") or ""),
            "conversation_id": resolved_conversation_id,
        },
    )
    append_message(resolved_session_id, "user", effective_message)

    if uploaded_file is not None and getattr(uploaded_file, "filename", ""):
        save_path = await _save_uploaded_attachment(uploaded_file, user_id=resolved_user_id, conversation_id=resolved_session_id)
        input_files = _workspace_input_files(resolved_user_id, resolved_session_id, save_path)
        if not _is_table_file_suffix(save_path.suffix.lower()):
            matched_skill, matched_action, route_info = _select_skill_route(
                effective_message,
                has_file=True,
                file_suffix=save_path.suffix.lower(),
                file_path=save_path,
            )
            if matched_skill is not None and matched_action is not None:
                task, _ = _start_task_trace(
                    user_id=resolved_user_id,
                    conversation_id=resolved_session_id,
                    intent=matched_action,
                    input_message=effective_message,
                    input_files=input_files,
                )
                task_type = _infer_document_task_type(effective_message, file_suffix=save_path.suffix.lower())
                matched_skill_mode = _resolve_uploaded_skill_mode(matched_skill)
                runner_name = "using_prompt_only_runner" if matched_skill_mode == "prompt_only" else "using_executable_runner"
                started = time.perf_counter()
                logger.info(
                    "Attachment skill route matched: skill=%s skill_mode=%s action=%s route=%s reason=%s runner=%s file_suffix=%s task_type=%s",
                    matched_skill,
                    matched_skill_mode,
                    matched_action,
                    (route_info or {}).get("route"),
                    (route_info or {}).get("reason"),
                    runner_name,
                    save_path.suffix.lower(),
                    task_type,
                )
                skill_result = execute_skill(
                    matched_skill,
                    action_name=matched_action,
                    file_path=str(save_path),
                    task_type=task_type,
                    session_id=resolved_session_id,
                    message=effective_message,
                    original_message=effective_message,
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
                result_kind = "prompt_only_skill" if matched_skill_mode == "prompt_only" else _resolve_result_kind(matched_skill, resolved_action_name)
                analysis_payload = _build_skill_analysis_payload(
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
                response = _attach_source({
                    "success": skill_result.success,
                    "session_id": resolved_session_id,
                    "reply": reply,
                    "error_message": None if skill_result.success else "；".join(skill_result.errors) or reply,
                    "intent": "IMAGE_ANALYSIS" if is_image_skill else matched_action,
                    "category": "tool",
                    "skill_name": matched_skill,
                    "action_name": resolved_action_name,
                    "skill_mode": matched_skill_mode,
                    "data": skill_result.data,
                    "errors": skill_result.errors,
                    "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
                    "tool_info": tool_info,
                    "task_id": task["task_id"],
                    **_build_chat_messages_payload(
                        session_id=resolved_session_id,
                        role_type="text" if is_image_skill or matched_skill_mode == "prompt_only" else ("analysis" if result_kind == "uploaded_skill" else "text"),
                        content=reply,
                        analysis=analysis_payload if (matched_skill_mode == "prompt_only" or result_kind == "uploaded_skill") and not is_image_skill else None,
                        skill_name=matched_skill,
                        action_name=resolved_action_name,
                        result_kind=result_kind,
                        skill_mode=matched_skill_mode,
                    ),
                }, "skill_execution", route_info=route_info, debug=debug)
                _record_skill_trace(
                    task_id=task["task_id"],
                    skill_name=matched_skill,
                    ability_name=resolved_action_name,
                    input_files=input_files,
                    response_payload=response,
                    raw_result_summary=reply,
                )
                user_memory_manager.add_recent_skill(resolved_user_id, matched_skill)
                append_message(resolved_session_id, "assistant", reply)
                session_analysis = _build_session_analysis_payload(response, resolved_session_id)
                update_session(resolved_session_id, "last_analysis", session_analysis)
                update_session(resolved_session_id, "last_file", response.get("saved_file"))
                update_session(resolved_session_id, "last_report", response.get("report"))
                _apply_task_state_from_response(resolved_session_id, response)
                logger.info(
                    "Attachment skill executed: skill=%s action=%s success=%s elapsed_ms=%.2f summary=%s",
                    matched_skill,
                    resolved_action_name,
                    skill_result.success,
                    (time.perf_counter() - started) * 1000,
                    (skill_result.summary or "")[:160],
                )
                return _finalize_workspace_response(
                    response,
                    user_id=resolved_user_id,
                    conversation_id=resolved_session_id,
                    user_message=effective_message,
                    assistant_reply=reply,
                    task_id=task["task_id"],
                )
            response = _build_no_matching_file_skill_response(
                session_id=resolved_session_id,
                save_path=save_path,
                message=effective_message,
                file_suffix=save_path.suffix.lower(),
                route_info=route_info,
                debug=debug,
            )
            append_message(resolved_session_id, "assistant", response.get("reply", ""))
            session_analysis = _build_session_analysis_payload(response, resolved_session_id)
            update_session(resolved_session_id, "last_analysis", session_analysis)
            update_session(resolved_session_id, "last_file", response.get("saved_file"))
            update_session(resolved_session_id, "last_report", response.get("report"))
            _apply_task_state_from_response(resolved_session_id, response)
            workspace_manager.append_error(resolved_user_id, resolved_session_id, response.get("error_message") or response.get("reply"))
            return _finalize_workspace_response(
                response,
                user_id=resolved_user_id,
                conversation_id=resolved_session_id,
                user_message=effective_message,
                assistant_reply=response.get("reply", ""),
            )
        started = time.perf_counter()
        task, _ = _start_task_trace(
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            intent="table_file_analysis",
            input_message=effective_message,
            input_files=input_files,
        )
        response = _analyze_uploaded_file_with_skills(
            save_path=save_path,
            message=effective_message,
            session_id=resolved_session_id,
            metadata=metadata,
            debug=debug,
        )
        response["task_id"] = task["task_id"]
        _record_skill_trace(
            task_id=task["task_id"],
            skill_name=response.get("skill_name") or "raman_spectroscopy_skill",
            ability_name=response.get("action_name") or "predict_methanol_concentration",
            input_files=input_files,
            response_payload=response,
            raw_result_summary=response.get("llm_explanation") or response.get("reply"),
        )
        user_memory_manager.add_recent_skill(resolved_user_id, response.get("skill_name") or "raman_spectroscopy_skill")
        logger.info(
            "File skill route completed: success=%s source=%s elapsed_ms=%.2f route=%s",
            response.get("success"),
            response.get("source"),
            (time.perf_counter() - started) * 1000,
            (response.get("route_info") or {}).get("reason"),
        )
        if response.get("success"):
            session_analysis = _build_session_analysis_payload(response, resolved_session_id)
            update_session(resolved_session_id, "last_analysis", session_analysis)
            update_session(resolved_session_id, "last_file", response.get("saved_file"))
            update_session(resolved_session_id, "last_report", response.get("report"))
            append_message(resolved_session_id, "assistant", response.get("llm_explanation", "分析完成。"))
            _apply_task_state_from_response(resolved_session_id, response)
            return _finalize_workspace_response(
                response,
                user_id=resolved_user_id,
                conversation_id=resolved_session_id,
                user_message=effective_message,
                assistant_reply=response.get("llm_explanation", "分析完成。"),
                task_id=task["task_id"],
            )
        else:
            append_message(resolved_session_id, "assistant", response.get("error_message", "分析失败。"))
            workspace_manager.append_error(resolved_user_id, resolved_session_id, response.get("error_message", "分析失败。"))
        return _finalize_workspace_response(
            response,
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            user_message=effective_message,
            assistant_reply=response.get("error_message", "分析失败。"),
            task_id=task["task_id"],
        )

    referenced_active_file = _resolve_referenced_active_file(resolved_user_id, resolved_session_id, effective_message)
    if referenced_active_file is not None:
        save_path, active_file_info = referenced_active_file
        input_files = [active_file_info]
        task, _ = _start_task_trace(
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            intent="continue_active_file_analysis",
            input_message=effective_message,
            input_files=input_files,
        )
        if save_path.suffix.lower() == ".csv":
            response = _analyze_uploaded_file_with_skills(
                save_path=save_path,
                message=effective_message,
                session_id=resolved_session_id,
                metadata=metadata,
                debug=debug,
            )
        else:
            matched_skill, matched_action, route_info = _select_skill_route(
                effective_message,
                has_file=True,
                file_suffix=save_path.suffix.lower(),
            )
            if matched_skill is None or matched_action is None:
                response = _build_no_matching_file_skill_response(
                    session_id=resolved_session_id,
                    save_path=save_path,
                    message=effective_message,
                    file_suffix=save_path.suffix.lower(),
                    route_info=route_info,
                    debug=debug,
                )
            else:
                matched_skill_mode = _resolve_uploaded_skill_mode(matched_skill)
                task_type = _infer_document_task_type(effective_message, file_suffix=save_path.suffix.lower())
                skill_result = execute_skill(
                    matched_skill,
                    action_name=matched_action,
                    file_path=str(save_path),
                    task_type=task_type,
                    session_id=resolved_session_id,
                    message=effective_message,
                    original_message=effective_message,
                )
                reply = str(skill_result.data.get("reply_text") or skill_result.summary or "文件 Skill 执行完成。")
                result_kind = "prompt_only_skill" if matched_skill_mode == "prompt_only" else _resolve_result_kind(matched_skill, matched_action)
                response = _attach_source({
                    "success": skill_result.success,
                    "session_id": resolved_session_id,
                    "reply": reply,
                    "error_message": None if skill_result.success else "；".join(skill_result.errors) or reply,
                    "intent": matched_action,
                    "category": "tool",
                    "skill_name": matched_skill,
                    "action_name": matched_action,
                    "skill_mode": matched_skill_mode,
                    "data": skill_result.data,
                    "errors": skill_result.errors,
                    **_build_chat_messages_payload(
                        session_id=resolved_session_id,
                        role_type="text" if matched_skill_mode == "prompt_only" else "analysis",
                        content=reply,
                        analysis=_build_skill_analysis_payload(matched_skill, matched_action, skill_result.to_dict(), message=reply, save_path=str(save_path)),
                        skill_name=matched_skill,
                        action_name=matched_action,
                        result_kind=result_kind,
                        skill_mode=matched_skill_mode,
                    ),
                }, "skill_execution", route_info=route_info, debug=debug)
        response["task_id"] = task["task_id"]
        _record_skill_trace(
            task_id=task["task_id"],
            skill_name=response.get("skill_name") or "raman_spectroscopy_skill",
            ability_name=response.get("action_name") or response.get("intent"),
            input_files=input_files,
            response_payload=response,
            raw_result_summary=response.get("reply") or response.get("llm_explanation"),
        )
        if response.get("skill_name"):
            user_memory_manager.add_recent_skill(resolved_user_id, response.get("skill_name"))
        assistant_reply = response.get("reply") or response.get("llm_explanation") or response.get("error_message") or "处理完成。"
        append_message(resolved_session_id, "assistant", assistant_reply)
        _apply_task_state_from_response(resolved_session_id, response)
        return _finalize_workspace_response(
            response,
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            user_message=effective_message,
            assistant_reply=assistant_reply,
            task_id=task["task_id"],
        )

    matched_skill, matched_action, route_info = _select_skill_route(effective_message, has_file=False)
    if matched_skill is not None and matched_action is not None:
        task, _ = _start_task_trace(
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            intent=matched_action,
            input_message=effective_message,
            input_files=_workspace_input_files(resolved_user_id, resolved_session_id),
        )
        started = time.perf_counter()
        matched_skill_mode = _resolve_uploaded_skill_mode(matched_skill)
        runner_name = "using_prompt_only_runner" if matched_skill_mode == "prompt_only" else "using_executable_runner"
        logger.info(
            "Skill route matched: skill=%s skill_mode=%s action=%s route=%s reason=%s runner=%s",
            matched_skill,
            matched_skill_mode,
            matched_action,
            (route_info or {}).get("route"),
            (route_info or {}).get("reason"),
            runner_name,
        )
        if matched_skill == "raman_spectroscopy_skill":
            content = "这个请求需要先上传 CSV 文件。请点击输入框左侧的 + 选择文件后再发送。"
            response = _attach_source({
                "success": True,
                "session_id": resolved_session_id,
                "reply": content,
                "intent": matched_action,
                "category": "tool",
                "skill_name": matched_skill,
                "action_name": matched_action,
                **_build_chat_messages_payload(
                    session_id=resolved_session_id,
                    role_type="text",
                    content=content,
                    analysis=None,
                    skill_name=matched_skill,
                    action_name=matched_action,
                ),
            }, "fallback", route_info=route_info, debug=debug)
            response["task_id"] = task["task_id"]
            _record_skill_trace(
                task_id=task["task_id"],
                skill_name=matched_skill,
                ability_name=matched_action,
                input_files=_workspace_input_files(resolved_user_id, resolved_session_id),
                response_payload=response,
                raw_result_summary=content,
            )
            append_message(resolved_session_id, "assistant", content)
            _apply_task_state_from_response(resolved_session_id, response)
            return _finalize_workspace_response(
                response,
                user_id=resolved_user_id,
                conversation_id=resolved_session_id,
                user_message=effective_message,
                assistant_reply=content,
                task_id=task["task_id"],
            )

        if matched_skill == "raman_spectroscopy_skill" and matched_action in {
            "generate_summary",
            "generate_markdown_report",
            "generate_experiment_record",
            "export_report",
        }:
            content = "生成报告通常需要先有一次有效分析结果。你可以先上传 CSV 文件完成分析。"
            response = _attach_source({
                "success": True,
                "session_id": resolved_session_id,
                "reply": content,
                "intent": matched_action,
                "category": "tool",
                "skill_name": matched_skill,
                "action_name": matched_action,
                **_build_chat_messages_payload(
                    session_id=resolved_session_id,
                    role_type="text",
                    content=content,
                    analysis=None,
                    skill_name=matched_skill,
                    action_name=matched_action,
                    result_kind="report",
                ),
            }, "fallback", route_info=route_info, debug=debug)
            response["task_id"] = task["task_id"]
            _record_skill_trace(
                task_id=task["task_id"],
                skill_name=matched_skill,
                ability_name=matched_action,
                input_files=_workspace_input_files(resolved_user_id, resolved_session_id),
                response_payload=response,
                raw_result_summary=content,
            )
            append_message(resolved_session_id, "assistant", content)
            _apply_task_state_from_response(resolved_session_id, response)
            return _finalize_workspace_response(
                response,
                user_id=resolved_user_id,
                conversation_id=resolved_session_id,
                user_message=effective_message,
                assistant_reply=content,
                task_id=task["task_id"],
            )

        skill_result = execute_skill(
            matched_skill,
            action_name=matched_action,
            session_id=resolved_session_id,
            message=effective_message,
            original_message=effective_message,
        )
        if matched_skill == "agent_system_skill" and matched_action == "list_skills":
            skill_list_payload = skill_result.data if isinstance(skill_result.data, dict) else list_skills(include_actions=True)
            skill_summary = _format_skill_list_summary(skill_list_payload)
            response = _attach_source({
                "success": skill_result.success,
                "session_id": resolved_session_id,
                "reply": skill_summary,
                "intent": matched_action,
                "category": "tool",
                "skill_name": matched_skill,
                "action_name": matched_action,
                "data": skill_list_payload,
                **_build_chat_messages_payload(
                    session_id=resolved_session_id,
                    role_type="text",
                    content=skill_summary,
                    analysis=None,
                    skill_name=matched_skill,
                    action_name=matched_action,
                ),
            }, "skill_execution", route_info=route_info, debug=debug)
            response["task_id"] = task["task_id"]
            _record_skill_trace(
                task_id=task["task_id"],
                skill_name=matched_skill,
                ability_name=matched_action,
                input_files=_workspace_input_files(resolved_user_id, resolved_session_id),
                response_payload=response,
                raw_result_summary=skill_summary,
            )
            user_memory_manager.add_recent_skill(resolved_user_id, matched_skill)
            append_message(resolved_session_id, "assistant", skill_summary)
            _apply_task_state_from_response(resolved_session_id, response)
            logger.info("Skill executed: skill=%s action=%s success=%s elapsed_ms=%.2f", matched_skill, matched_action, skill_result.success, (time.perf_counter() - started) * 1000)
            return _finalize_workspace_response(
                response,
                user_id=resolved_user_id,
                conversation_id=resolved_session_id,
                user_message=effective_message,
                assistant_reply=skill_summary,
                task_id=task["task_id"],
            )

        if skill_result.success:
            reply = str(skill_result.data.get("reply_text") or skill_result.summary)
        else:
            reply = "；".join(skill_result.errors) or skill_result.summary
        result_kind = "prompt_only_skill" if matched_skill_mode == "prompt_only" else _resolve_result_kind(matched_skill, matched_action)
        analysis_payload = _build_skill_analysis_payload(
            matched_skill,
            matched_action,
            skill_result.to_dict(),
            message=reply,
        )
        response = _attach_source({
            "success": skill_result.success,
            "session_id": resolved_session_id,
            "reply": reply,
            "error_message": None if skill_result.success else "；".join(skill_result.errors) or reply,
            "intent": matched_action,
            "category": "tool",
            "skill_name": matched_skill,
            "action_name": matched_action,
            "skill_mode": matched_skill_mode,
            "data": skill_result.data,
            "errors": skill_result.errors,
            "task_id": task["task_id"],
            **_build_chat_messages_payload(
                session_id=resolved_session_id,
                role_type="text" if matched_skill_mode == "prompt_only" else ("analysis" if result_kind in {"preprocessing", "prediction", "model_status", "report", "generic", "uploaded_skill"} else "text"),
                content=reply,
                analysis=analysis_payload if matched_skill_mode == "prompt_only" or result_kind in {"preprocessing", "prediction", "model_status", "report", "generic", "uploaded_skill"} else None,
                skill_name=matched_skill,
                action_name=matched_action,
                result_kind=result_kind,
                skill_mode=matched_skill_mode,
            ),
        }, "skill_execution", route_info=route_info, debug=debug)
        _record_skill_trace(
            task_id=task["task_id"],
            skill_name=matched_skill,
            ability_name=matched_action,
            input_files=_workspace_input_files(resolved_user_id, resolved_session_id),
            response_payload=response,
            raw_result_summary=reply,
        )
        user_memory_manager.add_recent_skill(resolved_user_id, matched_skill)
        logger.info(
            "Skill executed: skill=%s action=%s success=%s elapsed_ms=%.2f summary=%s",
            matched_skill,
            matched_action,
            skill_result.success,
            (time.perf_counter() - started) * 1000,
            (skill_result.summary or "")[:160],
        )
        append_message(resolved_session_id, "assistant", reply)
        _apply_task_state_from_response(resolved_session_id, response)
        return _finalize_workspace_response(
            response,
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            user_message=effective_message,
            assistant_reply=reply,
            task_id=task["task_id"],
        )

    structured_response = service.chat(
        effective_message,
        extra_params={
            "provider_id": provider_id,
            "model_id": model_id,
            "user_id": resolved_user_id,
            "conversation_id": resolved_session_id,
        },
        debug=debug,
        session_id=resolved_session_id,
    )
    if structured_response.get("intent") == "web_search" or structured_response.get("skill_name") == "web-search":
        web_search_data = dict(structured_response.get("data") or {})
        search_task = task_trace_manager.create_task(
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            intent="web_search",
            input_message=effective_message,
            input_files=[],
        )
        identify_step = task_trace_manager.add_step(
            search_task["task_id"],
            "识别为联网搜索任务",
            detail={"query": effective_message},
        )
        task_trace_manager.finish_step(
            identify_step["step_id"],
            detail={"query": effective_message, "used_provider": web_search_data.get("used_provider")},
        )
        select_step = task_trace_manager.add_step(
            search_task["task_id"],
            "选择 Skill",
            detail={"skill_name": "web-search", "ability_name": "search"},
        )
        task_trace_manager.finish_step(
            select_step["step_id"],
            detail={"skill_name": "web-search", "ability_name": "search"},
        )
        execute_step = task_trace_manager.add_step(
            search_task["task_id"],
            "执行 Skill",
            detail={"skill_name": "web-search", "ability_name": "search", "used_provider": web_search_data.get("used_provider")},
        )
        task_trace_manager.finish_step(
            execute_step["step_id"],
            status="success" if structured_response.get("success") else "failed",
            detail={
                "skill_name": "web-search",
                "ability_name": "search",
                "used_provider": web_search_data.get("used_provider"),
                "result_count": len(web_search_data.get("items") or []),
            },
            error_message=structured_response.get("error_message"),
        )
        task_trace_manager.record_skill_run(
            task_id=search_task["task_id"],
            skill_name="web-search",
            ability_name="search",
            input_files=[],
            output_files=[],
            status="success" if structured_response.get("success") else "failed",
            error_message=structured_response.get("error_message"),
            raw_result_summary=str(structured_response.get("reply") or "")[:1000],
        )
        structured_response["task_id"] = search_task["task_id"]
    structured_response["session_id"] = resolved_session_id
    structured_response.setdefault(
        "llm_model_info",
        _llm_model_info(
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            provider_id=provider_id,
            model_id=model_id,
        ),
    )
    if structured_response.get("intent") == "system_info_query" and structured_response.get("tool_used") == "get_current_model":
        structured_response["intent"] = "get_current_model"
    structured_response.update(
        _build_chat_messages_payload(
            session_id=resolved_session_id,
            role_type="text",
            content=structured_response.get("reply", ""),
            analysis=None,
        )
    )
    response_source = (
        "skill_execution"
        if structured_response.get("skill_name") == "web-search"
        else ("llm_response" if structured_response.get("category") == "general_chat" else ("tool_execution" if structured_response.get("tool_used") else "fallback"))
    )
    _attach_source(structured_response, response_source, debug=debug)
    logger.info(
        "Fallback route completed: source=%s intent=%s category=%s",
        structured_response.get("source"),
        structured_response.get("intent"),
        structured_response.get("category"),
    )
    append_message(resolved_session_id, "assistant", structured_response.get("reply", ""))
    _apply_task_state_from_response(resolved_session_id, structured_response)
    return _finalize_workspace_response(
        structured_response,
        user_id=resolved_user_id,
        conversation_id=resolved_session_id,
        user_message=effective_message,
        assistant_reply=structured_response.get("reply", ""),
    )


@router.post("/analyze-file")
async def analyze_file(
    file: UploadFile = File(...),
    message: str = Form(default="请分析这个文件"),
    conversation_id: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
    sample_name: str | None = Form(default=None),
    sample_type: str | None = Form(default=None),
    operator: str | None = Form(default=None),
    instrument: str | None = Form(default=None),
    laser_power: str | None = Form(default=None),
    integration_time: str | None = Form(default=None),
    remarks: str | None = Form(default=None),
) -> dict:
    """上传文件后，通过 Agent 工具链完成分析。表格文件会在 Raman 与普通数据分析之间自动分流。"""
    resolved_session_id = _ensure_session_id(conversation_id or session_id)
    save_path = await _save_uploaded_attachment(file)
    experiment_metadata = {
        "sample_name": sample_name,
        "sample_type": sample_type,
        "operator": operator,
        "instrument": instrument,
        "laser_power": laser_power,
        "integration_time": integration_time,
        "remarks": remarks,
    }
    if not _is_table_file_suffix(save_path.suffix.lower()):
        matched_skill, matched_action, route_info = _select_skill_route(
            message,
            has_file=True,
            file_suffix=save_path.suffix.lower(),
            file_path=save_path,
        )
        if matched_skill is not None and matched_action is not None:
            task_type = _infer_document_task_type(message, file_suffix=save_path.suffix.lower())
            matched_skill_mode = _resolve_uploaded_skill_mode(matched_skill)
            runner_name = "using_prompt_only_runner" if matched_skill_mode == "prompt_only" else "using_executable_runner"
            started = time.perf_counter()
            logger.info(
                "Analyze-file attachment skill route matched: skill=%s skill_mode=%s action=%s route=%s reason=%s runner=%s file_suffix=%s task_type=%s",
                matched_skill,
                matched_skill_mode,
                matched_action,
                (route_info or {}).get("route"),
                (route_info or {}).get("reason"),
                runner_name,
                save_path.suffix.lower(),
                task_type,
            )
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
            result_kind = "prompt_only_skill" if matched_skill_mode == "prompt_only" else _resolve_result_kind(matched_skill, resolved_action_name)
            analysis_payload = _build_skill_analysis_payload(
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
                "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
                "result": None,
                "professional_analysis": {},
                "model_info": {},
                "llm_model_info": _llm_model_info(conversation_id=resolved_session_id),
                "experiment_metadata": experiment_metadata,
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
                _build_chat_messages_payload(
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
            _attach_source(response_payload, "skill_execution", route_info=route_info, debug=False)
            append_message(resolved_session_id, "assistant", reply)
            session_analysis = _build_session_analysis_payload(response_payload, resolved_session_id)
            update_session(resolved_session_id, "last_analysis", session_analysis)
            update_session(resolved_session_id, "last_file", response_payload.get("saved_file"))
            update_session(resolved_session_id, "last_report", response_payload.get("report"))
            _apply_task_state_from_response(resolved_session_id, response_payload)
            logger.info(
                "Analyze-file attachment skill executed: skill=%s action=%s success=%s elapsed_ms=%.2f summary=%s",
                matched_skill,
                resolved_action_name,
                skill_result.success,
                (time.perf_counter() - started) * 1000,
                (skill_result.summary or "")[:160],
            )
            return response_payload
        response_payload = _build_no_matching_file_skill_response(
            session_id=resolved_session_id,
            save_path=save_path,
            message=message,
            file_suffix=save_path.suffix.lower(),
            route_info=route_info,
            debug=False,
        )
        append_message(resolved_session_id, "assistant", response_payload.get("reply", ""))
        session_analysis = _build_session_analysis_payload(response_payload, resolved_session_id)
        update_session(resolved_session_id, "last_analysis", session_analysis)
        update_session(resolved_session_id, "last_file", response_payload.get("saved_file"))
        update_session(resolved_session_id, "last_report", response_payload.get("report"))
        _apply_task_state_from_response(resolved_session_id, response_payload)
        return response_payload
    _csv_route_skill, _csv_route_action, csv_route_info = _select_skill_route(
        message,
        has_file=True,
        file_suffix=save_path.suffix.lower(),
        file_path=save_path,
    )
    if csv_route_info and csv_route_info.get("route") in {"data_analysis_missing_skill", "image_router_missing_skill"}:
        response_payload = _build_no_matching_file_skill_response(
            session_id=resolved_session_id,
            save_path=save_path,
            message=message,
            file_suffix=save_path.suffix.lower(),
            route_info=csv_route_info,
            debug=False,
        )
        append_message(resolved_session_id, "assistant", response_payload.get("reply", ""))
        session_analysis = _build_session_analysis_payload(response_payload, resolved_session_id)
        update_session(resolved_session_id, "last_analysis", session_analysis)
        update_session(resolved_session_id, "last_file", response_payload.get("saved_file"))
        update_session(resolved_session_id, "last_report", response_payload.get("report"))
        _apply_task_state_from_response(resolved_session_id, response_payload)
        return response_payload
    if _csv_route_skill != "raman_spectroscopy_skill":
        response_payload = _analyze_uploaded_file_with_skills(
            save_path=save_path,
            message=message,
            session_id=resolved_session_id,
            metadata=experiment_metadata,
            debug=False,
        )
        append_message(resolved_session_id, "assistant", response_payload.get("reply") or response_payload.get("llm_explanation") or "")
        session_analysis = _build_session_analysis_payload(response_payload, resolved_session_id)
        update_session(resolved_session_id, "last_analysis", session_analysis)
        update_session(resolved_session_id, "last_file", response_payload.get("saved_file"))
        update_session(resolved_session_id, "last_report", response_payload.get("report"))
        _apply_task_state_from_response(resolved_session_id, response_payload)
        return response_payload
    if _is_service_run_tool_overridden():
        response_payload = _analyze_csv_with_service_tools(
            save_path=save_path,
            message=message,
            session_id=resolved_session_id,
            metadata=experiment_metadata,
        )
        append_message(resolved_session_id, "assistant", response_payload.get("reply") or response_payload.get("llm_explanation") or "")
        session_analysis = _build_session_analysis_payload(response_payload, resolved_session_id)
        update_session(resolved_session_id, "last_analysis", session_analysis)
        update_session(resolved_session_id, "last_file", response_payload.get("saved_file"))
        update_session(resolved_session_id, "last_report", response_payload.get("report"))
        _apply_task_state_from_response(resolved_session_id, response_payload)
        return response_payload
    started = time.perf_counter()
    skill_result = execute_skill(
        "raman_spectroscopy_skill",
        action_name="predict_methanol_concentration",
        file_path=str(save_path),
        session_id=resolved_session_id,
        message=message,
        original_message=message,
        experiment_metadata=experiment_metadata,
    )
    reply = str(skill_result.data.get("reply_text") or skill_result.summary or "光谱分析已完成。")
    result_kind = _resolve_result_kind("raman_spectroscopy_skill", "predict_methanol_concentration")
    analysis_payload = _build_skill_analysis_payload(
        "raman_spectroscopy_skill",
        "predict_methanol_concentration",
        skill_result.to_dict(),
        message=reply,
        save_path=str(save_path),
    )
    response_payload = {
        "success": skill_result.success,
        "session_id": resolved_session_id,
        "message": message,
        "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
        "result": skill_result.data.get("result"),
        "professional_analysis": skill_result.data.get("professional_analysis") or {},
        "model_info": skill_result.data.get("model_info") or {},
        "llm_model_info": _llm_model_info(conversation_id=resolved_session_id),
        "experiment_metadata": experiment_metadata,
        "llm_explanation": reply,
        "llm_error": None if skill_result.success else reply,
        "report": skill_result.data.get("report"),
        "web_urls": skill_result.data.get("web_urls") or {"figures": {}, "report_view": "", "report_download": ""},
        "warnings": list(skill_result.data.get("warnings") or getattr(skill_result, "warnings", []) or []),
        "skill_name": "raman_spectroscopy_skill",
        "action_name": "predict_methanol_concentration",
        "error_message": None if skill_result.success else reply,
        "data": skill_result.data,
        "errors": skill_result.errors,
    }
    response_payload.update(
        _build_chat_messages_payload(
            session_id=resolved_session_id,
            role_type="analysis" if result_kind in {"prediction", "report", "generic"} else "text",
            content=reply,
            analysis=analysis_payload if result_kind in {"prediction", "report", "generic"} else None,
            skill_name="raman_spectroscopy_skill",
            action_name="predict_methanol_concentration",
            result_kind=result_kind,
        )
    )
    _attach_source(
        response_payload,
        "skill_execution",
        route_info={"route": "builtin_skill_rule", "reason": "csv_raman_skill"},
        debug=False,
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
                "experiment_metadata": experiment_metadata,
            }
            response_payload["history"] = save_analysis_history(history_payload)
        except Exception as exc:
            response_payload["history_error"] = str(exc)
    append_message(resolved_session_id, "assistant", reply)
    session_analysis = _build_session_analysis_payload(response_payload, resolved_session_id)
    update_session(resolved_session_id, "last_analysis", session_analysis)
    update_session(resolved_session_id, "last_file", response_payload.get("saved_file"))
    update_session(resolved_session_id, "last_report", response_payload.get("report"))
    _apply_task_state_from_response(resolved_session_id, response_payload)
    logger.info(
        "Analyze-file csv skill executed: skill=%s action=%s success=%s elapsed_ms=%.2f summary=%s",
        "raman_spectroscopy_skill",
        "predict_methanol_concentration",
        skill_result.success,
        (time.perf_counter() - started) * 1000,
        (skill_result.summary or "")[:160],
    )
    return response_payload
