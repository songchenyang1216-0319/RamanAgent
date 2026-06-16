from __future__ import annotations

import json
import re
from typing import Any, Iterable

from backend.schemas.agent_stream import AgentStreamEvent


STREAM_EVENT_NAMES = {
    "start",
    "status",
    "planner",
    "tool_start",
    "tool_progress",
    "tool_result",
    "delta",
    "final",
    "error",
    "done",
}


class StreamEventBuilder:
    def __init__(
        self,
        *,
        conversation_id: str | None = None,
        session_id: str | None = None,
        message_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.session_id = session_id
        self.message_id = message_id
        self.task_id = task_id
        self.sequence = 0

    def event(
        self,
        event: str,
        *,
        content: str = "",
        data: dict[str, Any] | None = None,
        visible: bool = True,
    ) -> AgentStreamEvent:
        self.sequence += 1
        return AgentStreamEvent(
            event=event if event in STREAM_EVENT_NAMES else "status",
            conversation_id=self.conversation_id,
            session_id=self.session_id,
            message_id=self.message_id,
            task_id=self.task_id,
            sequence=self.sequence,
            content=content,
            data=dict(data or {}),
            visible=visible,
        )


def format_sse(event: AgentStreamEvent | dict[str, Any]) -> str:
    payload = event.to_dict() if isinstance(event, AgentStreamEvent) else dict(event)
    event_name = str(payload.get("event") or "status")
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def split_text_for_stream(text: str, *, min_chars: int = 2, max_chars: int = 8) -> Iterable[str]:
    source = str(text or "")
    if not source:
        return
    token_pattern = re.compile(r"[\u4e00-\u9fff]{1,8}|[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)?|\s+|[^\s]", re.UNICODE)
    buffer = ""
    for match in token_pattern.finditer(source):
        token = match.group(0)
        if not buffer:
            buffer = token
        elif len(buffer) + len(token) <= max_chars and not token.isspace():
            buffer += token
        else:
            if buffer:
                yield buffer
            buffer = token
        if len(buffer) >= max_chars or (len(buffer) >= min_chars and buffer[-1:] in "，。！？；、,.!?;\n"):
            yield buffer
            buffer = ""
    if buffer:
        yield buffer


def compact_response_for_stream(response: dict[str, Any]) -> dict[str, Any]:
    """Return a response payload that is safe to send inside a final SSE event."""
    payload = dict(response or {})
    debug = payload.get("debug")
    if not debug:
        payload["debug"] = {}
    return payload
