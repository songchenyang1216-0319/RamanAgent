from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


TASK_STATUSES = {"pending", "running", "succeeded", "failed", "cancelled"}
TASK_EVENTS = {
    "task_created",
    "task_started",
    "task_progress",
    "tool_start",
    "tool_progress",
    "artifact_created",
    "task_succeeded",
    "task_failed",
    "task_cancelled",
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


@dataclass
class TaskEvent:
    event_id: str
    task_id: str
    event: str
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
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

