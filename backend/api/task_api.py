from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.security.ownership_guard import ownership_guard
from backend.security.resource_scope import ResourceScope
from backend.tasks import get_task_manager
from backend.tasks.task_events import format_task_sse
from backend.tasks.task_schema import TaskCreateRequest


router = APIRouter(prefix="/api/tasks", tags=["tasks-v2"])


def _scope(current_user: dict) -> ResourceScope:
    return ResourceScope.from_auth_context(current_user)


class CreateTaskPayload(BaseModel):
    task_type: str
    payload: dict[str, Any] = {}
    project_id: str | None = None
    conversation_id: str | None = None
    idempotency_key: str | None = None
    max_attempts: int = 1
    parent_task_id: str | None = None


@router.post("")
def create_task(payload: CreateTaskPayload, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    task = get_task_manager().create_task(
        TaskCreateRequest(
            task_type=payload.task_type,
            payload=payload.payload or {},
            user_id=current_user["user_id"],
            project_id=payload.project_id,
            conversation_id=payload.conversation_id,
            idempotency_key=payload.idempotency_key,
            max_attempts=payload.max_attempts,
            parent_task_id=payload.parent_task_id,
        )
    )
    return {"success": True, "task": task, "task_id": task.get("task_id")}


@router.get("/{task_id}/events")
async def task_events(
    task_id: str,
    after_sequence: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    current_user: dict = Depends(get_request_user_context),
):
    manager = get_task_manager()
    task = ownership_guard.require_task_owner(task_id, _scope(current_user))

    async def generate():
        emitted_sequence = int(after_sequence or 0)
        if last_event_id:
            emitted_sequence = max(emitted_sequence, manager.repository.get_event_sequence(task_id, last_event_id))
        idle_rounds = 0
        while idle_rounds < 120:
            events = manager.task_events_after(task_id, after_sequence=emitted_sequence)
            for event in events:
                emitted_sequence = max(emitted_sequence, int(event.get("sequence") or 0))
                yield format_task_sse(event)
            current = manager.get_task(task_id) or {}
            if str(current.get("status") or "") in {"succeeded", "completed", "failed", "cancelled", "dead_letter"}:
                return
            idle_rounds += 1
            if idle_rounds % 10 == 0:
                yield format_task_sse({"event_id": f"heartbeat-{task_id}-{idle_rounds}", "event_type": "heartbeat", "event": "heartbeat", "task_id": task_id, "sequence": emitted_sequence, "content": "heartbeat", "data": {}})
            await asyncio.sleep(0.5)
        yield format_task_sse({"event_type": "heartbeat", "event": "heartbeat", "task_id": task_id, "sequence": emitted_sequence, "content": "任务事件流空闲超时。", "data": {}})

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    manager = get_task_manager()
    ownership_guard.require_task_owner(task_id, _scope(current_user))
    updated = manager.cancel_task(task_id)
    return {"success": True, "task": updated}


@router.post("/{task_id}/retry")
def retry_task(task_id: str, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    manager = get_task_manager()
    task = ownership_guard.require_task_owner(task_id, _scope(current_user))
    if str(task.get("status") or "") not in {"failed", "dead_letter", "cancelled"}:
        raise HTTPException(status_code=400, detail={"error_code": "TASK_RETRY_NOT_ALLOWED", "error_message": "只有 failed/dead_letter/cancelled 任务可以手动重试。"})
    manager.repository.update(task_id, status="pending", progress=0, cancel_requested=0, current_step="等待重试", error_message=None)
    manager.emit(task_id, "task_retrying", "任务已重新排队。", {"manual": True})
    payload = task.get("payload") or {}
    retry_request = TaskCreateRequest(
        task_type=str(task.get("task_type") or ""),
        payload=payload,
        user_id=str(task.get("user_id") or current_user["user_id"]),
        project_id=task.get("project_id"),
        conversation_id=task.get("conversation_id"),
        max_attempts=max(1, int(task.get("max_attempts") or 1)),
        parent_task_id=task.get("parent_task_id"),
        trace_id=task.get("trace_id"),
    )
    manager.queue.submit(task_id, lambda: manager._run_task(task_id, retry_request))
    return {"success": True, "task": manager.get_task(task_id)}


@router.get("/{task_id}/artifacts")
def task_artifacts(task_id: str, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    manager = get_task_manager()
    task = ownership_guard.require_task_owner(task_id, _scope(current_user))
    return {"success": True, "task_id": task_id, "artifacts": task.get("artifacts") or []}
