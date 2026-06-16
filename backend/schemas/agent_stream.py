from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentStreamEvent:
    event: str
    conversation_id: str | None = None
    session_id: str | None = None
    message_id: str | None = None
    task_id: str | None = None
    sequence: int = 0
    timestamp: str = field(default_factory=utc_now_iso)
    content: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["visible"] = bool(self.visible)
        payload["sequence"] = int(self.sequence)
        return payload
