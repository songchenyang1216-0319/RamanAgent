from __future__ import annotations

import json
from typing import Any


def format_task_sse(event: dict[str, Any]) -> str:
    event_name = str(event.get("event") or "task_progress")
    return f"event: {event_name}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

