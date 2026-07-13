from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


TASK_STATUSES = {"pending", "running", "succeeded", "failed", "cancelled"}
TASK_EVENTS = {
    "task_created",
    "task_queued",
    "task_started",
    "task_progress",
    "context_loading",
    "intent_resolved",
    "plan_created",
    "plan_validated",
    "tool_start",
    "tool_started",
    "tool_progress",
    "tool_completed",
    "rag_retrieving",
    "rag_reranking",
    "model_delta",
    "artifact_created",
    "task_retrying",
    "task_succeeded",
    "task_failed",
    "task_cancelled",
    "final",
    "done",
    "heartbeat",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class TaskCreateRequest:
    task_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    idempotency_key: str | None = None
    max_attempts: int = 1
    parent_task_id: str | None = None
    trace_id: str | None = None


@dataclass
class TaskEvent:
    event_id: str
    task_id: str
    event: str
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    sequence: int | None = None
    conversation_id: str | None = None
    message_id: str | None = None
    trace_id: str | None = None
    created_at: str = field(default_factory=now_iso)

    @classmethod
    def create(cls, task_id: str, event: str, content: str = "", data: dict[str, Any] | None = None) -> "TaskEvent":
        return cls(
            event_id=uuid4().hex,
            task_id=task_id,
            event=event if event in TASK_EVENTS else "task_progress",
            content=content,
            data=dict(data or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
