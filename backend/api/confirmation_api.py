from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.security.audit import record_audit_log
from backend.tool_runtime.tool_confirmation import get_confirmation, list_confirmations, update_confirmation_status


router = APIRouter(prefix="/api/agent/confirmations", tags=["agent-confirmations"])


class ConfirmationDecisionPayload(BaseModel):
    note: str = ""


@router.get("")
def list_agent_confirmations(
    status: str | None = None,
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    user_id = None if current_user.get("is_admin") else current_user.get("user_id")
    items = list_confirmations(user_id=user_id)
    if status:
        items = [item for item in items if item.get("status") == status]
    return {"success": True, "confirmations": items, "total": len(items)}


@router.get("/{confirmation_id}")
def get_agent_confirmation(
    confirmation_id: str,
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    item = _require_confirmation(confirmation_id, current_user)
    return {"success": True, "confirmation": item}


@router.post("/{confirmation_id}/approve")
def approve_agent_confirmation(
    confirmation_id: str,
    payload: ConfirmationDecisionPayload,
    request: Request,
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    item = _require_confirmation(confirmation_id, current_user)
    if item.get("status") == "rejected":
        raise HTTPException(status_code=409, detail={"error_code": "CONFIRMATION_REJECTED", "error_message": "该确认请求已被拒绝，不能再次批准。"})
    updated = update_confirmation_status(confirmation_id, "approved")
    record_audit_log(
        user_id=current_user.get("user_id"),
        action="tool.confirmation.approve",
        resource_type="confirmation",
        resource_id=confirmation_id,
        request=request,
        detail={"tool_name": item.get("tool_name"), "action_name": item.get("action_name"), "note": payload.note},
    )
    return {"success": True, "confirmation": updated}


@router.post("/{confirmation_id}/reject")
def reject_agent_confirmation(
    confirmation_id: str,
    payload: ConfirmationDecisionPayload,
    request: Request,
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    item = _require_confirmation(confirmation_id, current_user)
    if item.get("status") == "approved":
        raise HTTPException(status_code=409, detail={"error_code": "CONFIRMATION_APPROVED", "error_message": "该确认请求已被批准，不能再次拒绝。"})
    updated = update_confirmation_status(confirmation_id, "rejected")
    record_audit_log(
        user_id=current_user.get("user_id"),
        action="tool.confirmation.reject",
        resource_type="confirmation",
        resource_id=confirmation_id,
        request=request,
        detail={"tool_name": item.get("tool_name"), "action_name": item.get("action_name"), "note": payload.note},
    )
    return {"success": True, "confirmation": updated}


def _require_confirmation(confirmation_id: str, current_user: dict) -> dict[str, Any]:
    item = get_confirmation(confirmation_id)
    if not item:
        raise HTTPException(status_code=404, detail={"error_code": "CONFIRMATION_NOT_FOUND", "error_message": f"确认请求不存在：{confirmation_id}"})
    if not current_user.get("is_admin") and item.get("user_id") != current_user.get("user_id"):
        raise HTTPException(status_code=403, detail={"error_code": "PERMISSION_DENIED", "error_message": "无权访问该确认请求。"})
    return item
