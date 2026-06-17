"""报告中心接口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.services.file_service import FileCatalogService
from backend.services.project_service import ProjectService
from backend.services.report_export_service import ReportExportService
from backend.services.report_registry_service import ReportRegistryService
from backend.services.task_trace_manager import TaskTraceManager
from backend.services.workspace_manager import WorkspaceManager
from backend.tasks import get_task_manager
from backend.tasks.task_schema import TaskCreateRequest


router = APIRouter(prefix="/api/reports", tags=["reports"])
workspace_manager = WorkspaceManager()
task_trace_manager = TaskTraceManager(workspace_manager=workspace_manager)
file_catalog = FileCatalogService()
report_registry = ReportRegistryService(file_catalog=file_catalog)
project_service = ProjectService(file_catalog=file_catalog, task_trace_manager=task_trace_manager, report_service=report_registry)
report_export_service = ReportExportService(file_catalog=file_catalog, task_trace_manager=task_trace_manager, project_service=project_service, report_registry=report_registry)


class ReportExportPayload(BaseModel):
    task_id: str | None = None
    file_id: str | None = None
    project_id: str | None = None
    title: str | None = None
    formats: list[str] = ["markdown"]


@router.get("")
def list_reports(project_id: str | None = Query(default=None), current_user: dict = Depends(get_request_user_context)) -> dict:
    reports = report_registry.list_reports(current_user["user_id"], project_id=project_id, is_admin=current_user["is_admin"])
    return {"success": True, "reports": reports, "total": len(reports)}


@router.get("/{report_id}")
def get_report(report_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    report = report_registry.get_report(report_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    if report is None:
        raise HTTPException(status_code=404, detail={"message": "报告不存在。", "error_code": "REPORT_NOT_FOUND", "error_message": "报告不存在。", "suggestion": "请刷新报告列表后重试。"})
    return {"success": True, "report": report}


@router.post("/export")
def export_report(
    payload: ReportExportPayload,
    async_task: bool = Query(default=False),
    current_user: dict = Depends(get_request_user_context),
) -> dict:
    if async_task:
        task = get_task_manager().create_task(
            TaskCreateRequest(
                task_type="report_export",
                payload={
                    "task_id": payload.task_id,
                    "file_id": payload.file_id,
                    "project_id": payload.project_id,
                    "formats": payload.formats,
                    "title": payload.title,
                    "is_admin": current_user["is_admin"],
                },
                user_id=current_user["user_id"],
                project_id=payload.project_id,
            )
        )
        return {"success": True, "async_task": True, "task_id": task.get("task_id"), "task": task}
    try:
        return report_export_service.export_report(
            user_id=current_user["user_id"],
            is_admin=current_user["is_admin"],
            task_id=payload.task_id,
            file_id=payload.file_id,
            project_id=payload.project_id,
            formats=payload.formats,
            title=payload.title,
        )
    except (KeyError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc), "error_code": "REPORT_EXPORT_SOURCE_NOT_FOUND", "error_message": str(exc), "suggestion": "请确认关联文件、任务、项目是否有效且归属于当前用户。"}) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "error_code": "REPORT_EXPORT_FAILED", "error_message": str(exc), "suggestion": "请检查文件格式和导出参数后重试。"}) from exc


@router.get("/{report_id}/download")
def download_report(report_id: str, format: str = Query(default="markdown"), current_user: dict = Depends(get_request_user_context)):
    report = report_registry.get_report(report_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    if report is None:
        raise HTTPException(status_code=404, detail={"message": "报告不存在。", "error_code": "REPORT_NOT_FOUND", "error_message": "报告不存在。", "suggestion": "请刷新报告列表后重试。"})
    path = report_registry.resolve_report_path(report, format)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail={"message": f"当前报告不存在 {format} 导出文件。", "error_code": "REPORT_FORMAT_NOT_READY", "error_message": f"当前报告不存在 {format} 导出文件。", "suggestion": "请重新导出该格式，或先下载 markdown/html 版本。"})
    media_type = "application/octet-stream"
    if path.suffix.lower() == ".md":
        media_type = "text/markdown; charset=utf-8"
    elif path.suffix.lower() == ".json":
        media_type = "application/json"
    elif path.suffix.lower() == ".html":
        media_type = "text/html; charset=utf-8"
    elif path.suffix.lower() == ".docx":
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return FileResponse(path=path, filename=path.name, media_type=media_type)


@router.delete("/{report_id}")
def delete_report(report_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        report = report_registry.delete_report(report_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc), "error_code": "REPORT_NOT_FOUND", "error_message": str(exc), "suggestion": "请刷新报告列表后重试。"}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"message": str(exc), "error_code": "REPORT_FORBIDDEN", "error_message": str(exc), "suggestion": "请确认该报告是否属于当前用户。"}) from exc
    return {"success": True, "report": report}
