from __future__ import annotations

from typing import Any

from backend.security.audit import record_audit_log


class AuditService:
    def record(self, *, user_id: str, action: str, resource_type: str = "", resource_id: str = "", detail: dict[str, Any] | None = None) -> dict[str, Any]:
        return record_audit_log(
            user_id=user_id,
            action=action,
            resource_type=resource_type or None,
            resource_id=resource_id or None,
            detail=detail or {},
        )
