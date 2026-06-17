from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.tasks import get_task_manager
from backend.tasks.task_events import format_task_sse
from backend.tasks.task_schema import TaskCreateRequest


router = APIRouter(prefix="/api/tasks", tags=["tasks-v2"])


class CreateTaskPayload(BaseModel):
    task_type: str
    payload: dict[str, Any] = {}
    project_id: str | None = None
    conversation_id: str | None = None


@router.post("")
def create_task(payload: CreateTaskPayload, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    task = get_task_manager().create_task(
        TaskCreateRequest(
            task_type=payload.task_type,
            payload=payload.payload or {},
            user_id=current_user["user_id"],
            project_id=payload.project_id,
            conversation_id=payload.conversation_id,
        )
    )
    return {"success": True, "task": task, "task_id": task.get("task_id")}


@router.get("/{task_id}/events")
async def task_events(task_id: str, current_user: dict = Depends(get_request_user_context)):
    manager = get_task_manager()
    task = manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND", "error_message": "任务不存在。"})
    if not current_user.get("is_admin") and str(task.get("user_id") or "") != str(current_user["user_id"]):
        raise HTTPException(status_code=403, detail={"error_code": "TASK_FORBIDDEN", "error_message": "无权访问该任务。"})

    async def generate():
        emitted = 0
        idle_rounds = 0
        while idle_rounds < 120:
            events = manager.task_events(task_id)
            for event in events[emitted:]:
                emitted += 1
                yield format_task_sse(event)
            current = manager.get_task(task_id) or {}
            if str(current.get("status") or "") in {"succeeded", "failed", "cancelled"} and emitted >= len(events):
                yield format_task_sse({"event": "done", "task_id": task_id, "content": "任务事件流已结束。", "data": {"status": current.get("status")}})
                return
            idle_rounds += 1
            await asyncio.sleep(0.5)
        yield format_task_sse({"event": "done", "task_id": task_id, "content": "任务事件流已超时关闭。", "data": {}})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    manager = get_task_manager()
    task = manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND", "error_message": "任务不存在。"})
    if not current_user.get("is_admin") and str(task.get("user_id") or "") != str(current_user["user_id"]):
        raise HTTPException(status_code=403, detail={"error_code": "TASK_FORBIDDEN", "error_message": "无权取消该任务。"})
    updated = manager.cancel_task(task_id)
    return {"success": True, "task": updated}


@router.get("/{task_id}/artifacts")
def task_artifacts(task_id: str, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    manager = get_task_manager()
    task = manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND", "error_message": "任务不存在。"})
    if not current_user.get("is_admin") and str(task.get("user_id") or "") != str(current_user["user_id"]):
        raise HTTPException(status_code=403, detail={"error_code": "TASK_FORBIDDEN", "error_message": "无权访问该任务产物。"})
    return {"success": True, "task_id": task_id, "artifacts": task.get("artifacts") or []}

