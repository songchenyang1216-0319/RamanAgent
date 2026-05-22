"""Agent HTTP 接口。"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.agent.agent_service import RamanAgentService
from backend.agent.session_store import append_message, create_session, update_session
from backend.api.methanol_api import build_figure_web_urls, build_report_web_urls
from backend.services.model_registry_service import ModelRegistryService
from backend.services.history_service import save_analysis_history
from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT, ensure_dirs


router = APIRouter(prefix="/api/agent", tags=["agent"])
service = RamanAgentService()
model_registry_service = ModelRegistryService()
UPLOAD_DIR = OUTPUT_DIR / "uploads"


class AgentChatRequest(BaseModel):
    """Agent 聊天请求。"""

    message: str
    debug: bool = False
    session_id: str | None = None


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
    return {
        "session_id": session_id,
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
    }


def _sanitize_csv_filename(file_name: str) -> str:
    """清理上传文件名，避免路径穿越和危险字符。"""
    safe_name = Path(file_name or "").name
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5._-]+", "_", Path(safe_name).stem).strip("._-")
    if not stem:
        stem = "uploaded"
    return f"{stem}.csv"


async def _save_uploaded_csv(file: UploadFile) -> Path:
    """保存 Agent 上传的 CSV 到 outputs/uploads。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供上传文件名。")
    if Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="只允许上传 .csv 文件。")

    ensure_dirs()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_csv_filename(file.filename)
    target_path = UPLOAD_DIR / f"{Path(safe_name).stem}_{uuid4().hex[:8]}.csv"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空。")
    target_path.write_bytes(content)
    return target_path


@router.get("/tools")
def get_tools() -> dict:
    """返回当前可用工具。"""
    return {"success": True, "available_tools": service.list_tools()}


@router.post("/chat")
def chat(request: AgentChatRequest) -> dict:
    """返回 Agent 的结构化建议或工具执行结果。"""
    session_id = _ensure_session_id(request.session_id)
    append_message(session_id, "user", request.message)
    response = service.chat(request.message, debug=request.debug, session_id=session_id)
    response["session_id"] = session_id
    append_message(session_id, "assistant", response.get("reply", ""))
    return response


@router.post("/analyze-file")
async def analyze_file(
    file: UploadFile = File(...),
    message: str = Form(default="请分析这个 Raman CSV 文件"),
    session_id: str | None = Form(default=None),
    sample_name: str | None = Form(default=None),
    sample_type: str | None = Form(default=None),
    operator: str | None = Form(default=None),
    instrument: str | None = Form(default=None),
    laser_power: str | None = Form(default=None),
    integration_time: str | None = Form(default=None),
    remarks: str | None = Form(default=None),
) -> dict:
    """上传 CSV 后，通过 Agent 工具链完成预测、解释和报告生成。"""
    resolved_session_id = _ensure_session_id(session_id)
    save_path = await _save_uploaded_csv(file)
    experiment_metadata = {
        "sample_name": sample_name,
        "sample_type": sample_type,
        "operator": operator,
        "instrument": instrument,
        "laser_power": laser_power,
        "integration_time": integration_time,
        "remarks": remarks,
    }
    current_model_response = model_registry_service.get_current_model()
    artifact_check_response = model_registry_service.check_model_artifacts()
    model_info = {}
    if current_model_response.get("success"):
        model_info = dict(current_model_response.get("data") or {})
        model_info["artifact_check"] = {
            "success": artifact_check_response.get("success", False),
            "missing_files": (artifact_check_response.get("data") or {}).get("missing_files", []),
            "existing_files": (artifact_check_response.get("data") or {}).get("existing_files", []),
        }

    prediction_tool_result = service.run_tool(
        "predict_methanol",
        {"file_path": str(save_path), "debug": False},
    )
    result = prediction_tool_result.get("result")
    valid_result = (
        isinstance(result, dict)
        and result.get("final_prediction") is not None
        and result.get("svr_prediction") is not None
        and result.get("rf_prediction") is not None
    )
    if not prediction_tool_result.get("success") or not valid_result:
        return {
            "success": False,
            "session_id": resolved_session_id,
            "message": "文件已上传，但预测失败",
            "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
            "error_message": prediction_tool_result.get("error_message", "预测服务没有返回有效结果"),
            "result": None,
            "warnings": prediction_tool_result.get("warnings", []),
            "raw_keys": prediction_tool_result.get("raw_keys", []),
            "llm_explanation": "预测结果无效，暂不生成大模型解释。",
            "report": None,
            "web_urls": {"figures": {}, "report_view": "", "report_download": ""},
        }

    result = dict(result)
    result.pop("professional_analysis", None)
    warnings = list(result.get("warnings", []))
    professional_analysis = {}
    professional_response = service.run_tool(
        "professional_spectral_analysis",
        {"csv_path": str(save_path), "prediction_result": result},
    )
    if professional_response.get("success"):
        professional_analysis = professional_response
    else:
        warnings.append("预测已完成，但专业光谱分析部分失败。")
        warnings.append(professional_response.get("error_message", "专业光谱分析失败。"))

    explanation_response = service.run_tool(
        "explain_result",
        {
            "result": result,
            "professional_analysis": professional_analysis,
            "model_info": model_info,
            "experiment_metadata": experiment_metadata,
        },
    )
    llm_explanation = explanation_response.get("explanation", "预测结果无效，暂不生成大模型解释。")

    report = None
    if result:
        report_response = service.run_tool(
            "generate_report",
            {
                "result": result,
                "llm_explanation": llm_explanation,
                "professional_analysis": professional_analysis,
                "model_info": model_info,
                "experiment_metadata": experiment_metadata,
            },
        )
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
            warnings.append(report_response.get("error_message", "报告生成失败。"))

    figure_paths = result.get("figure_paths", {}) or {}
    if not figure_paths:
        warnings.append("预测完成，但未返回图像路径")
    web_urls = {
        "figures": build_figure_web_urls(figure_paths),
        **build_report_web_urls(report or {}),
    }
    response_payload = {
        "success": True,
        "session_id": resolved_session_id,
        "message": message,
        "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
        "result": result,
        "professional_analysis": professional_analysis,
        "model_info": model_info,
        "experiment_metadata": experiment_metadata,
        "llm_explanation": llm_explanation,
        "llm_error": explanation_response.get("error_message"),
        "report": report,
        "web_urls": web_urls,
        "warnings": warnings,
    }
    try:
        history_payload = {
            "saved_file": response_payload["saved_file"],
            "result": prediction_tool_result.get("raw_result", {}),
            "llm_explanation": llm_explanation,
            "report": report or {},
            "web_urls": web_urls,
            "professional_analysis": professional_analysis,
            "model_info": model_info,
            "experiment_metadata": experiment_metadata,
        }
        response_payload["history"] = save_analysis_history(history_payload)
    except Exception as exc:
        response_payload["history_error"] = str(exc)

    session_analysis = _build_session_analysis_payload(response_payload, resolved_session_id)
    update_session(resolved_session_id, "last_analysis", session_analysis)
    update_session(resolved_session_id, "last_file", response_payload.get("saved_file"))
    update_session(resolved_session_id, "last_report", response_payload.get("report"))
    return response_payload
