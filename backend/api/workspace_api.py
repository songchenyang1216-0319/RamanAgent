"""Workspace, conversation, and task trace APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

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
def get_task_trace(task_id: str) -> dict:
    try:
        trace = task_trace_manager.get_task_trace(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "success": True,
        **trace,
    }


@router.get("/api/conversations/{conversation_id}/tasks")
def list_conversation_tasks(conversation_id: str, user_id: str = Query(default=DEFAULT_USER_ID)) -> dict:
    workspace = workspace_manager.create_workspace(user_id, conversation_id)
    return {
        "success": True,
        "user_id": workspace["user_id"],
        "conversation_id": workspace["conversation_id"],
        "tasks": task_trace_manager.list_conversation_tasks(workspace["user_id"], workspace["conversation_id"]),
    }


@router.get("/api/conversations/{conversation_id}/messages")
def list_conversation_messages(
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
