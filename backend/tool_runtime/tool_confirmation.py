from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from backend.agent.planning.tool_schema import ActionSpec, ToolSpec
from backend.tool_runtime.tool_context import ToolContext


CONFIRMATION_STORE: dict[str, dict[str, Any]] = {}


@dataclass
class ConfirmationRequest:
    confirmation_id: str
    user_id: str
    conversation_id: str
    task_id: str
    tool_name: str
    action_name: str
    danger_level: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    expires_at: str = ""
    status: str = "pending"
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "confirmation_id": self.confirmation_id,
            "user_id": self.user_id,
            "conversation_id": self.conversation_id,
            "task_id": self.task_id,
            "tool_name": self.tool_name,
            "action_name": self.action_name,
            "danger_level": self.danger_level,
            "message": self.message,
            "details": self.details,
            "expires_at": self.expires_at,
            "status": self.status,
            "created_at": self.created_at,
        }


def needs_confirmation(tool: ToolSpec, action: ActionSpec, args: dict[str, Any]) -> bool:
    if bool(args.get("confirmed")) or bool(args.get("confirmation_approved")):
        return False
    confirmation_id = str(args.get("confirmation_id") or "").strip()
    if confirmation_id:
        item = get_confirmation(confirmation_id)
        if item and item.get("status") == "approved":
            args["confirmation_approved"] = True
            return False
    danger = str(action.danger_level or tool.danger_level or "low").lower()
    if danger in {"high", "critical"}:
        return True
    return bool(action.requires_confirmation)


def create_confirmation(tool: ToolSpec, action: ActionSpec, args: dict[str, Any], context: ToolContext) -> ConfirmationRequest:
    now = datetime.utcnow()
    message = (
        action.confirmation_message
        or f"即将执行高风险操作：{tool.display_name}/{action.display_name or action.action_name}。请确认是否继续。"
    )
    request = ConfirmationRequest(
        confirmation_id=uuid4().hex,
        user_id=context.user_id,
        conversation_id=context.conversation_id,
        task_id=context.task_id,
        tool_name=tool.tool_name,
        action_name=action.action_name,
        danger_level=str(action.danger_level or tool.danger_level or "medium"),
        message=message,
        details={"args": _safe_args(args), "source": context.source},
        expires_at=(now + timedelta(minutes=30)).isoformat(timespec="seconds"),
        created_at=now.isoformat(timespec="seconds"),
    )
    CONFIRMATION_STORE[request.confirmation_id] = request.to_dict()
    return request


def get_confirmation(confirmation_id: str) -> dict[str, Any] | None:
    return CONFIRMATION_STORE.get(str(confirmation_id))


def list_confirmations(user_id: str | None = None) -> list[dict[str, Any]]:
    items = list(CONFIRMATION_STORE.values())
    if user_id:
        items = [item for item in items if item.get("user_id") == user_id]
    return sorted(items, key=lambda item: item.get("created_at") or "", reverse=True)


def update_confirmation_status(confirmation_id: str, status: str) -> dict[str, Any] | None:
    item = CONFIRMATION_STORE.get(str(confirmation_id))
    if not item:
        return None
    item["status"] = status
    return item


def _safe_args(args: dict[str, Any]) -> dict[str, Any]:
    safe = {}
    for key, value in dict(args or {}).items():
        lowered = str(key).lower()
        if any(marker in lowered for marker in ("key", "secret", "token", "password")):
            safe[key] = "[REDACTED]"
        else:
            text = str(value)
            safe[key] = text[:500] + ("..." if len(text) > 500 else "")
    return safe
