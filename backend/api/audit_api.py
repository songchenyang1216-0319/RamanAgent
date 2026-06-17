from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.api.auth_dependencies import require_admin
from backend.repositories.audit_log_repository import AuditLogRepository


router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


@router.get("")
def list_audit_logs(
    user_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(require_admin),
) -> dict[str, Any]:
    logs = AuditLogRepository().list(user_id=user_id, limit=limit)
    return {"success": True, "logs": logs, "total": len(logs)}


@router.get("/{audit_id}")
def get_audit_log(audit_id: str, current_user: dict = Depends(require_admin)) -> dict[str, Any]:
    item = AuditLogRepository().get(audit_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"error_code": "AUDIT_LOG_NOT_FOUND", "error_message": "审计日志不存在。"})
    return {"success": True, "audit_log": item}

