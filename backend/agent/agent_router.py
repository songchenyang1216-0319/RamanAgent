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
from backend.skills.upload_service import delete_uploaded_skill, list_uploaded_skills, save_uploaded_skill
from backend.services.history_service import save_analysis_history
from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT, ensure_dirs


router = APIRouter(prefix="/api/agent", tags=["agent"])
service = RamanAgentService()
UPLOAD_DIR = OUTPUT_DIR / "uploads"
logger = logging.getLogger(__name__)


def _normalize_skill_key(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


class AgentChatRequest(BaseModel):
    """Agent 聊天请求。"""

    message: str
    debug: bool = False
    session_id: str | None = None


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


async def _save_uploaded_attachment(file: UploadFile) -> Path:
    """保存 Agent 上传的任意附件到 outputs/uploads。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供上传文件名。")

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
    if "当前模型" in raw_text:
        return "agent_system_skill", "current_model", {"route": "builtin_skill_rule", "reason": "current_model"}
    if "检查模型" in raw_text or "模型状态" in raw_text:
        return "agent_system_skill", "model_health_check", {"route": "builtin_skill_rule", "reason": "model_health"}
    if "上传帮助" in raw_text:
        return "agent_system_skill", "upload_help", {"route": "builtin_skill_rule", "reason": "upload_help"}
    if "最近实验" in raw_text or "最近记录" in raw_text:
        return "agent_system_skill", "recent_experiments", {"route": "builtin_skill_rule", "reason": "recent_experiments"}
    if "清空会话" in raw_text:
        return "agent_system_skill", "clear_session", {"route": "builtin_skill_rule", "reason": "clear_session"}
    if any(keyword in raw_text for keyword in ("预处理", "平滑", "去噪", "基线", "归一化")):
        return "raman_spectroscopy_skill", "full_preprocess_pipeline", {"route": "builtin_skill_rule", "reason": "preprocess"}
    if any(keyword in raw_text for keyword in ("画图", "可视化", "光谱图")):
        return "raman_spectroscopy_skill", "plot_prediction_result", {"route": "builtin_skill_rule", "reason": "visualization"}
    if any(keyword in raw_text for keyword in ("报告", "生成报告", "实验记录")):
        return "raman_spectroscopy_skill", "generate_markdown_report", {"route": "builtin_skill_rule", "reason": "report"}
    if has_file and str(file_suffix or "").lower() == ".csv":
        return "raman_spectroscopy_skill", "predict_methanol_concentration", {"route": "builtin_skill_rule", "reason": "file_prediction_default"}
    if any(keyword in raw_text for keyword in ("甲醇", "分析这个光谱", "分析这个拉曼", "预测")):
        return "raman_spectroscopy_skill", "predict_methanol_concentration", {"route": "builtin_skill_rule", "reason": "prediction"}
    return None, None, None


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


def _looks_like_raman_file_task(message: str) -> bool:
    normalized = str(message or "").strip().lower()
    keywords = (
        "光谱",
        "拉曼",
        "raman",
        "甲醇",
        "预测",
        "峰位",
        "基线",
        "去噪",
        "归一化",
        "浓度",
    )
    return any(keyword in normalized for keyword in keywords)


def _select_skill_route(message: str, has_file: bool = False, file_suffix: str | None = None) -> tuple[str | None, str | None, dict | None]:
    file_suffix = str(file_suffix or "").lower()
    if has_file and file_suffix == ".csv":
        if _looks_like_raman_file_task(message):
            return _match_builtin_skill(message, has_file=has_file, file_suffix=file_suffix)
        if not _looks_like_generic_file_task(message):
            return _match_builtin_skill(message, has_file=has_file, file_suffix=file_suffix)
    uploaded_skill, route_info = match_uploaded_skill(message, file_suffix=file_suffix)
    if uploaded_skill is not None:
        return uploaded_skill.name, "run_uploaded_skill", route_info
    if has_file and file_suffix and file_suffix != ".csv":
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


def _analyze_uploaded_file_with_skills(
    *,
    save_path: Path,
    message: str,
    session_id: str,
    metadata: dict | None = None,
    debug: bool = False,
) -> dict:
    """使用 Skill 层驱动 CSV 分析，并返回统一的聊天分析结果。"""
    metadata = dict(metadata or {})
    warnings: list[str] = []
    loader_skill = get_skill("raman_spectroscopy_skill")
    if loader_skill is None:
        return {
            "success": False,
            "session_id": session_id,
            "message": message,
            "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
            "error_message": "Skill 注册表未正确初始化，无法执行文件分析。",
        }

    target_skill_name, target_action_name, route_info = _select_skill_route(message, has_file=True, file_suffix=save_path.suffix.lower())
    if target_skill_name is None or target_action_name is None:
        target_skill_name = "raman_spectroscopy_skill"
        target_action_name = "predict_methanol_concentration"
        route_info = {"route": "builtin_skill_rule", "reason": "fallback_prediction"}

    loader_result = loader_skill.run(file_path=str(save_path), action_name="inspect_spectrum")
    if not loader_result.success:
        error_message = "；".join(loader_result.errors) or loader_result.summary
        return {
            "success": False,
            "session_id": session_id,
            "message": message,
            "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
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
        return {
            "success": False,
            "session_id": session_id,
            "message": message,
            "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
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
        "model_info": model_info,
        "experiment_metadata": metadata,
        "warnings": list(dict.fromkeys(warnings)),
        "skill_results": {
            "raman_spectroscopy_skill.loader": loader_result.to_dict(),
            target_skill_name: skill_result.to_dict(),
            "agent_system_skill": model_health.to_dict(),
        },
    }

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
                "error_message": error_message,
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
    response_payload.update(
        {
            "result": skill_payload.get("data", {}),
            "professional_analysis": {},
            "llm_explanation": skill_result.summary,
            "llm_error": None,
            "report": None,
            "web_urls": {"figures": {}, "report_view": "", "report_download": ""},
            "warnings": list(dict.fromkeys(warnings + list(skill_result.errors))),
            "route_info": route_info,
        }
    )
    analysis_message = _build_skill_analysis_payload(
        target_skill_name,
        target_action_name,
        skill_payload,
        message=skill_result.summary,
        save_path=response_payload["saved_file"],
        extra_details={"sample_info": metadata},
    )
    response_payload = {
        **response_payload,
        **_build_chat_messages_payload(
            session_id=session_id,
            role_type="analysis",
            content=analysis_message["summary"],
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
    session_id = None
    debug = False
    uploaded_file = None
    metadata: dict[str, str | None] = {}

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        message = str(form.get("message") or "").strip()
        session_id = str(form.get("session_id") or "").strip() or None
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
        session_id = payload.get("session_id")
        debug = bool(payload.get("debug", False))

    resolved_session_id = _ensure_session_id(session_id)
    effective_message = message or "请分析这个文件"
    append_message(resolved_session_id, "user", effective_message)

    if uploaded_file is not None and getattr(uploaded_file, "filename", ""):
        save_path = await _save_uploaded_attachment(uploaded_file)
        if save_path.suffix.lower() != ".csv":
            matched_skill, matched_action, route_info = _select_skill_route(
                effective_message,
                has_file=True,
                file_suffix=save_path.suffix.lower(),
            )
            if matched_skill is not None and matched_action is not None:
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
                reply = str(skill_result.data.get("reply_text") or skill_result.summary or "文档 Skill 执行完成。")
                result_kind = "prompt_only_skill" if matched_skill_mode == "prompt_only" else _resolve_result_kind(matched_skill, matched_action)
                analysis_payload = _build_skill_analysis_payload(
                    matched_skill,
                    matched_action,
                    skill_result.to_dict(),
                    message=reply,
                    save_path=str(save_path),
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
                    **_build_chat_messages_payload(
                        session_id=resolved_session_id,
                        role_type="text" if matched_skill_mode == "prompt_only" else ("analysis" if result_kind == "uploaded_skill" else "text"),
                        content=reply,
                        analysis=analysis_payload if matched_skill_mode == "prompt_only" or result_kind == "uploaded_skill" else None,
                        skill_name=matched_skill,
                        action_name=matched_action,
                        result_kind=result_kind,
                        skill_mode=matched_skill_mode,
                    ),
                }, "skill_execution", route_info=route_info, debug=debug)
                append_message(resolved_session_id, "assistant", reply)
                session_analysis = _build_session_analysis_payload(response, resolved_session_id)
                update_session(resolved_session_id, "last_analysis", session_analysis)
                update_session(resolved_session_id, "last_file", response.get("saved_file"))
                update_session(resolved_session_id, "last_report", response.get("report"))
                _apply_task_state_from_response(resolved_session_id, response)
                logger.info(
                    "Attachment skill executed: skill=%s action=%s success=%s elapsed_ms=%.2f summary=%s",
                    matched_skill,
                    matched_action,
                    skill_result.success,
                    (time.perf_counter() - started) * 1000,
                    (skill_result.summary or "")[:160],
                )
                return response
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
            return response
        started = time.perf_counter()
        response = _analyze_uploaded_file_with_skills(
            save_path=save_path,
            message=effective_message,
            session_id=resolved_session_id,
            metadata=metadata,
            debug=debug,
        )
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
        else:
            append_message(resolved_session_id, "assistant", response.get("error_message", "分析失败。"))
        return response

    matched_skill, matched_action, route_info = _select_skill_route(effective_message, has_file=False)
    if matched_skill is not None and matched_action is not None:
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
            append_message(resolved_session_id, "assistant", content)
            _apply_task_state_from_response(resolved_session_id, response)
            return response

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
            append_message(resolved_session_id, "assistant", content)
            _apply_task_state_from_response(resolved_session_id, response)
            return response

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
            append_message(resolved_session_id, "assistant", skill_summary)
            _apply_task_state_from_response(resolved_session_id, response)
            logger.info("Skill executed: skill=%s action=%s success=%s elapsed_ms=%.2f", matched_skill, matched_action, skill_result.success, (time.perf_counter() - started) * 1000)
            return response

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
        return response

    structured_response = service.chat(effective_message, debug=debug, session_id=resolved_session_id)
    structured_response["session_id"] = resolved_session_id
    structured_response.update(
        _build_chat_messages_payload(
            session_id=resolved_session_id,
            role_type="text",
            content=structured_response.get("reply", ""),
            analysis=None,
        )
    )
    _attach_source(structured_response, "llm_response" if structured_response.get("category") == "general_chat" else "fallback", debug=debug)
    logger.info(
        "Fallback route completed: source=%s intent=%s category=%s",
        structured_response.get("source"),
        structured_response.get("intent"),
        structured_response.get("category"),
    )
    append_message(resolved_session_id, "assistant", structured_response.get("reply", ""))
    _apply_task_state_from_response(resolved_session_id, structured_response)
    return structured_response


@router.post("/analyze-file")
async def analyze_file(
    file: UploadFile = File(...),
    message: str = Form(default="请分析这个文件"),
    session_id: str | None = Form(default=None),
    sample_name: str | None = Form(default=None),
    sample_type: str | None = Form(default=None),
    operator: str | None = Form(default=None),
    instrument: str | None = Form(default=None),
    laser_power: str | None = Form(default=None),
    integration_time: str | None = Form(default=None),
    remarks: str | None = Form(default=None),
) -> dict:
    """上传文件后，通过 Agent 工具链完成分析。CSV 走光谱分析，其它文件走通用文本分析。"""
    resolved_session_id = _ensure_session_id(session_id)
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
    if save_path.suffix.lower() != ".csv":
        matched_skill, matched_action, route_info = _select_skill_route(
            message,
            has_file=True,
            file_suffix=save_path.suffix.lower(),
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
            reply = str(skill_result.data.get("reply_text") or skill_result.summary or "文档 Skill 执行完成。")
            result_kind = "prompt_only_skill" if matched_skill_mode == "prompt_only" else _resolve_result_kind(matched_skill, matched_action)
            analysis_payload = _build_skill_analysis_payload(
                matched_skill,
                matched_action,
                skill_result.to_dict(),
                message=reply,
                save_path=str(save_path),
            )
            response_payload = {
                "success": skill_result.success,
                "session_id": resolved_session_id,
                "message": message,
                "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
                "result": None,
                "professional_analysis": {},
                "model_info": {},
                "experiment_metadata": experiment_metadata,
                "llm_explanation": reply,
                "llm_error": None,
                "report": None,
                "web_urls": {"figures": {}, "report_view": "", "report_download": ""},
                "warnings": [],
                "attachment_info": {},
                "skill_name": matched_skill,
                "action_name": matched_action,
                "skill_mode": matched_skill_mode,
                "error_message": None if skill_result.success else "；".join(skill_result.errors) or reply,
                "data": skill_result.data,
                "errors": skill_result.errors,
            }
            response_payload.update(
                _build_chat_messages_payload(
                    session_id=resolved_session_id,
                    role_type="text" if matched_skill_mode == "prompt_only" else ("analysis" if result_kind == "uploaded_skill" else "text"),
                    content=reply,
                    analysis=analysis_payload if matched_skill_mode == "prompt_only" or result_kind == "uploaded_skill" else None,
                    skill_name=matched_skill,
                    action_name=matched_action,
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
                matched_action,
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
        "experiment_metadata": experiment_metadata,
        "llm_explanation": reply,
        "llm_error": None if skill_result.success else reply,
        "report": skill_result.data.get("report"),
        "web_urls": skill_result.data.get("web_urls") or {"figures": {}, "report_view": "", "report_download": ""},
        "warnings": list(skill_result.data.get("warnings") or skill_result.warnings or []),
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
