from __future__ import annotations

from typing import Any

from fastapi import Request

from backend.repositories.audit_log_repository import AuditLogRepository


def record_audit_log(
    *,
    user_id: str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request: Request | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ip_address = None
    user_agent = None
    if request is not None:
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
    return AuditLogRepository().record(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        detail=detail or {},
    )

