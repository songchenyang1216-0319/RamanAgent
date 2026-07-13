from __future__ import annotations

import json
from typing import Any


def format_task_sse(event: dict[str, Any]) -> str:
    event_name = str(event.get("event_type") or event.get("event") or "task_progress")
    event_id = str(event.get("event_id") or "")
    event_id_line = f"id: {event_id}\n" if event_id else ""
    return f"{event_id_line}event: {event_name}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
