"""项目管理接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.services.project_service import ProjectService
from backend.services.report_registry_service import ReportRegistryService
from backend.services.task_trace_manager import TaskTraceManager
from backend.services.workspace_manager import WorkspaceManager


router = APIRouter(prefix="/api/projects", tags=["projects"])
workspace_manager = WorkspaceManager()
task_trace_manager = TaskTraceManager(workspace_manager=workspace_manager)
report_registry = ReportRegistryService()
project_service = ProjectService(file_catalog=workspace_manager.file_catalog, task_trace_manager=task_trace_manager, report_service=report_registry)


class ProjectPayload(BaseModel):
    name: str
    description: str | None = None


class AttachFilePayload(BaseModel):
    file_id: str


@router.get("")
def list_projects(current_user: dict = Depends(get_request_user_context)) -> dict:
    projects = project_service.list_projects(current_user["user_id"])
    return {"success": True, "projects": projects, "total": len(projects)}


@router.post("")
def create_project(payload: ProjectPayload, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        project = project_service.create_project(current_user["user_id"], payload.name, payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "error_code": "PROJECT_CREATE_FAILED", "error_message": str(exc), "suggestion": "请补充有效项目名称。"}) from exc
    return {"success": True, "project": project}


@router.get("/{project_id}")
def get_project(project_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    project = project_service.get_project(project_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    if project is None:
        raise HTTPException(status_code=404, detail={"message": "项目不存在。", "error_code": "PROJECT_NOT_FOUND", "error_message": "项目不存在。", "suggestion": "请刷新项目列表后重试。"})
    return {"success": True, "project": project}


@router.patch("/{project_id}")
def update_project(project_id: str, payload: ProjectPayload, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        project = project_service.update_project(project_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"], name=payload.name, description=payload.description)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc), "error_code": "PROJECT_NOT_FOUND", "error_message": str(exc), "suggestion": "请确认项目是否仍存在。"}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"message": str(exc), "error_code": "PROJECT_FORBIDDEN", "error_message": str(exc), "suggestion": "请切换到项目所有者账号后重试。"}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "error_code": "PROJECT_UPDATE_FAILED", "error_message": str(exc), "suggestion": "请检查输入字段。"}) from exc
    return {"success": True, "project": project}


@router.delete("/{project_id}")
def delete_project(project_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        project = project_service.archive_project(project_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc), "error_code": "PROJECT_NOT_FOUND", "error_message": str(exc), "suggestion": "请刷新项目列表后重试。"}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"message": str(exc), "error_code": "PROJECT_FORBIDDEN", "error_message": str(exc), "suggestion": "请使用项目所有者账号操作。"}) from exc
    return {"success": True, "project": project}


@router.get("/{project_id}/files")
def list_project_files(project_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        files = project_service.list_project_files(project_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc), "error_code": "PROJECT_NOT_FOUND", "error_message": str(exc), "suggestion": "请刷新项目列表后重试。"}) from exc
    return {"success": True, "files": files, "total": len(files)}


@router.get("/{project_id}/tasks")
def list_project_tasks(project_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        tasks = project_service.list_project_tasks(project_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc), "error_code": "PROJECT_NOT_FOUND", "error_message": str(exc), "suggestion": "请刷新项目列表后重试。"}) from exc
    return {"success": True, "tasks": tasks, "total": len(tasks)}


@router.get("/{project_id}/reports")
def list_project_reports(project_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        reports = project_service.list_project_reports(project_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc), "error_code": "PROJECT_NOT_FOUND", "error_message": str(exc), "suggestion": "请刷新项目列表后重试。"}) from exc
    return {"success": True, "reports": reports, "total": len(reports)}


@router.post("/{project_id}/attach-file")
def attach_file(project_id: str, payload: AttachFilePayload, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        result = project_service.attach_file(project_id, payload.file_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail={"message": str(exc), "error_code": "PROJECT_OR_FILE_NOT_FOUND", "error_message": str(exc), "suggestion": "请确认项目和文件仍存在。"}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"message": str(exc), "error_code": "PROJECT_ATTACH_FORBIDDEN", "error_message": str(exc), "suggestion": "请确认你是否拥有该项目和文件。"}) from exc
    return {"success": True, **result}
