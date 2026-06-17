from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.planning.plan_types import LLMPlan
from backend.agent.planning.plan_validator import PlanValidator
from backend.agent.planning.tool_catalog import ToolCatalog
from backend.api.auth_dependencies import get_request_user_context
from backend.tool_runtime import ToolContext, ToolRuntime


router = APIRouter(prefix="/api/tools", tags=["tools"])
catalog = ToolCatalog()
tool_runtime = ToolRuntime(catalog=catalog)


class ToolActionPayload(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    file_path: str | None = None
    conversation_id: str | None = None
    debug: bool = False
    confirmed: bool = False


@router.get("")
def list_tools() -> dict[str, Any]:
    payload = catalog.to_dict()
    return {"success": True, **payload, "total": len(payload.get("tools") or {})}


@router.get("/{tool_name}")
def get_tool(tool_name: str) -> dict[str, Any]:
    tool = catalog.get(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail={"error_code": "TOOL_NOT_FOUND", "error_message": f"工具不存在：{tool_name}"})
    return {"success": True, "tool": tool.to_dict()}


@router.get("/{tool_name}/actions")
def list_tool_actions(tool_name: str) -> dict[str, Any]:
    tool = catalog.get(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail={"error_code": "TOOL_NOT_FOUND", "error_message": f"工具不存在：{tool_name}"})
    return {"success": True, "tool_name": tool_name, "actions": [action.to_dict() for action in tool.actions.values()]}


@router.post("/{tool_name}/{action_name}/validate")
def validate_tool_action(tool_name: str, action_name: str, payload: ToolActionPayload, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    validation = _validate(tool_name, action_name, payload, current_user)
    return {"success": validation.valid, "validation": validation.to_dict()}


@router.post("/{tool_name}/{action_name}/execute")
def execute_tool_action(
    tool_name: str,
    action_name: str,
    payload: ToolActionPayload,
    request: Request,
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    _require_action(tool_name, action_name)
    args = dict(payload.args or {})
    if payload.confirmed:
        args["confirmed"] = True
    context = _tool_context(payload, current_user, request)
    result = tool_runtime.execute(tool_name, action_name, args, context)
    return {"success": result.success, "response": result.to_dict()}


def _validate(tool_name: str, action_name: str, payload: ToolActionPayload, current_user: dict):
    tool, action = _require_action(tool_name, action_name)
    args = dict(payload.args or {})
    if payload.confirmed:
        args["confirmed"] = True
    plan = LLMPlan.from_dict(
        {
            "plan_type": "tool" if tool_name not in {"raman_pipeline", "rag"} else tool_name,
            "intent": f"{tool_name}.{action_name}",
            "confidence": 1.0,
            "requires_file": bool(action.requires_file),
            "requires_confirmation": bool(action.requires_confirmation),
            "reason": "Tool API direct execution",
            "steps": [{"step_id": "step_001", "tool_name": tool_name, "action_name": action_name, "args": args}],
        }
    )
    return PlanValidator(catalog=catalog).validate(plan, _normalized(payload, current_user))


def _require_action(tool_name: str, action_name: str):
    tool = catalog.get(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail={"error_code": "TOOL_NOT_FOUND", "error_message": f"工具不存在：{tool_name}"})
    action = tool.get_action(action_name)
    if action is None:
        raise HTTPException(status_code=404, detail={"error_code": "ACTION_NOT_FOUND", "error_message": f"工具动作不存在：{tool_name}.{action_name}"})
    return tool, action


def _tool_context(payload: ToolActionPayload, current_user: dict, request: Request) -> ToolContext:
    normalized = _normalized(payload, current_user)
    permissions = list(current_user.get("permissions") or [])
    if current_user.get("is_admin"):
        permissions.append("*")
    return ToolContext.from_normalized(
        normalized,
        source="tool_api",
        ip_address=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
        permissions=permissions,
        metadata={
            "role": current_user.get("role") or "user",
            "username": current_user.get("username") or "",
            "authenticated": bool(current_user.get("authenticated")),
            "message": payload.message,
            "file_path": payload.file_path,
        },
    )


def _normalized(payload: ToolActionPayload, current_user: dict):
    return MessageNormalizer().normalize(
        {
            "message": payload.message or f"执行工具 {payload}",
            "file_path": payload.file_path,
            "conversation_id": payload.conversation_id,
            "session_id": payload.conversation_id,
            "debug": payload.debug,
            "user_id": current_user.get("user_id") or "default_user",
            "explicit_has_file": bool(payload.file_path),
        }
    )
