from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from backend.api.auth_dependencies import get_request_user_context
from backend.api.deprecation import apply_deprecation_headers
from backend.schemas.file_analysis import FileAnalysisRequest
from backend.services.file_analysis_service import (
    AgentFileAnalysisError,
    AgentFileNotFoundError,
    FileAnalysisService,
    FilePermissionDeniedError,
    UnsupportedFileTypeError,
)
from backend.services.workspace_manager import DEFAULT_USER_ID


agent_router = APIRouter(prefix="/api/agent", tags=["Legacy Compatibility"])
files_router = APIRouter(prefix="/api/files", tags=["File Analysis"])
service = FileAnalysisService()


def _metadata_from_form(
    *,
    sample_name: str | None,
    sample_type: str | None,
    operator: str | None,
    instrument: str | None,
    laser_power: str | None,
    integration_time: str | None,
    remarks: str | None,
) -> dict:
    return {
        "sample_name": sample_name,
        "sample_type": sample_type,
        "operator": operator,
        "instrument": instrument,
        "laser_power": laser_power,
        "integration_time": integration_time,
        "remarks": remarks,
    }


@agent_router.post("/analyze-file")
async def analyze_file_legacy(
    response: Response,
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
    user_id: str = Form(default=DEFAULT_USER_ID),
) -> dict:
    apply_deprecation_headers(response, legacy_path="/api/agent/analyze-file", successor_path="/api/files/analyze")
    payload = FileAnalysisRequest(
        user_id=user_id,
        conversation_id=conversation_id,
        session_id=session_id,
        message=message,
        metadata=_metadata_from_form(
            sample_name=sample_name,
            sample_type=sample_type,
            operator=operator,
            instrument=instrument,
            laser_power=laser_power,
            integration_time=integration_time,
            remarks=remarks,
        ),
    )
    return await _run_upload_analysis(file=file, payload=payload)


@files_router.post("/analyze")
async def analyze_file(
    payload: FileAnalysisRequest,
    current_user: dict = Depends(get_request_user_context),
) -> dict:
    effective_user_id = current_user["user_id"] if current_user.get("authenticated") else (payload.user_id or DEFAULT_USER_ID)
    payload.user_id = effective_user_id
    try:
        return await service.analyze(request=payload, is_admin=current_user.get("is_admin", False))
    except Exception as exc:
        raise _to_http_exception(exc) from exc


async def _run_upload_analysis(*, file: UploadFile, payload: FileAnalysisRequest) -> dict:
    try:
        return await service.analyze_upload(file=file, request=payload)
    except Exception as exc:
        raise _to_http_exception(exc) from exc


def _to_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, AgentFileNotFoundError):
        return HTTPException(status_code=404, detail={"success": False, "message": "文件不存在。", "error_code": "FILE_NOT_FOUND", "error_message": str(exc)})
    if isinstance(exc, FilePermissionDeniedError):
        return HTTPException(status_code=403, detail={"success": False, "message": "无权访问该文件。", "error_code": "FILE_ACCESS_DENIED", "error_message": "无权访问该文件。"})
    if isinstance(exc, UnsupportedFileTypeError):
        return HTTPException(status_code=415, detail={"success": False, "message": "不支持的文件类型。", "error_code": "UNSUPPORTED_FILE_TYPE", "error_message": str(exc)})
    if isinstance(exc, AgentFileAnalysisError):
        return HTTPException(status_code=422, detail={"success": False, "message": "文件分析失败。", "error_code": "FILE_ANALYSIS_FAILED", "error_message": str(exc)})
    if isinstance(exc, HTTPException):
        return exc
    return HTTPException(status_code=500, detail={"success": False, "message": "文件分析失败。", "error_code": "FILE_ANALYSIS_INTERNAL_ERROR", "error_message": str(exc)})
