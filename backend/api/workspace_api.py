"""Workspace, conversation, and task trace APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth_dependencies import get_request_user_context
from backend.services.task_trace_manager import TaskTraceManager
from backend.services.workspace_manager import DEFAULT_USER_ID, WorkspaceManager


router = APIRouter(tags=["workspace"])
workspace_manager = WorkspaceManager()
task_trace_manager = TaskTraceManager(workspace_manager=workspace_manager)


@router.get("/api/workspaces/{conversation_id}/files")
def list_workspace_files(conversation_id: str, user_id: str = Query(default=DEFAULT_USER_ID)) -> dict:
    workspace = workspace_manager.create_workspace(user_id, conversation_id)
    files = workspace_manager.list_files(workspace["user_id"], workspace["conversation_id"])
    return {
        "success": True,
        "user_id": workspace["user_id"],
        "conversation_id": workspace["conversation_id"],
        **files,
    }


@router.get("/api/workspaces/{conversation_id}/context")
def get_workspace_context(conversation_id: str, user_id: str = Query(default=DEFAULT_USER_ID)) -> dict:
    context = workspace_manager.read_workspace_context(user_id, conversation_id)
    return {
        "success": True,
        **context,
    }


@router.get("/api/tasks/{task_id}")
def get_task_trace(task_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        trace = task_trace_manager.get_task_trace(task_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    task = trace.get("task") or {}
    return {
        "success": True,
        **task,
        **trace,
    }


@router.get("/api/tasks")
def list_tasks(
    user_id: str = Query(default=DEFAULT_USER_ID),
    workspace_id: str | None = Query(default=None),
    current_user: dict = Depends(get_request_user_context),
) -> dict:
    effective_user_id = current_user["user_id"] if current_user.get("authenticated") and not current_user.get("is_admin") else user_id
    if current_user.get("authenticated") and current_user.get("is_admin") and user_id in {"", DEFAULT_USER_ID}:
        effective_user_id = None
    tasks = task_trace_manager.list_tasks(user_id=effective_user_id, conversation_id=workspace_id)
    return {
        "success": True,
        "tasks": tasks,
        "total": len(tasks),
    }


@router.get("/api/tasks/{task_id}/logs")
def get_task_logs(task_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        logs = task_trace_manager.get_task_logs(task_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"success": True, **logs}


@router.get("/api/tasks/{task_id}/result")
def get_task_result(task_id: str, current_user: dict = Depends(get_request_user_context)) -> dict:
    try:
        result = task_trace_manager.get_task_result(task_id, user_id=current_user["user_id"], is_admin=current_user["is_admin"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"success": True, **result}


@router.get("/api/conversations/{conversation_id}/tasks")
def list_conversation_tasks(conversation_id: str, user_id: str = Query(default=DEFAULT_USER_ID)) -> dict:
    workspace = workspace_manager.create_workspace(user_id, conversation_id)
    return {
        "success": True,
        "user_id": workspace["user_id"],
        "conversation_id": workspace["conversation_id"],
        "tasks": task_trace_manager.list_conversation_tasks(workspace["user_id"], workspace["conversation_id"]),
    }


@router.get("/api/workspaces/{conversation_id}/messages")
def list_workspace_messages(
    conversation_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict:
    workspace = workspace_manager.create_workspace(user_id, conversation_id)
    return {
        "success": True,
        "user_id": workspace["user_id"],
        "conversation_id": workspace["conversation_id"],
        "messages": workspace_manager.get_recent_messages(workspace["user_id"], workspace["conversation_id"], limit=limit),
    }
