from __future__ import annotations

from typing import Any

from backend.repositories.audit_log_repository import AuditLogRepository
from backend.tool_runtime.tool_context import ToolContext


SENSITIVE_KEYS = ("api_key", "secret", "token", "password", "authorization", ".env")


def sanitize_detail(detail: dict[str, Any]) -> dict[str, Any]:
    def clean(value: Any, key: str = "") -> Any:
        lowered = key.lower()
        if any(marker in lowered for marker in SENSITIVE_KEYS):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {str(k): clean(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [clean(item, key) for item in value[:50]]
        text = str(value)
        if len(text) > 2000:
            return text[:2000] + "...[truncated]"
        return value

    return clean(detail)


def record_tool_audit(
    *,
    context: ToolContext,
    action: str,
    resource_id: str,
    detail: dict[str, Any],
) -> str:
    item = AuditLogRepository().record(
        user_id=context.user_id,
        action=action,
        resource_type="tool",
        resource_id=resource_id,
        ip_address=context.ip_address or None,
        user_agent=context.user_agent or None,
        detail=sanitize_detail(detail),
    )
    return str(item.get("audit_id") or "")
