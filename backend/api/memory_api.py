"""User long-term memory APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.auth_dependencies import get_request_user_context
from backend.services.user_memory_manager import UserMemoryManager
from backend.services.workspace_manager import DEFAULT_USER_ID


router = APIRouter(prefix="/api/memory", tags=["memory"])
memory_manager = UserMemoryManager()


class MemoryPatchRequest(BaseModel):
    memory: dict[str, Any] | None = None
    patch: dict[str, Any] | None = None


def _effective_user_id(current_user: dict[str, Any], user_id: str | None = None) -> str:
    if current_user.get("authenticated"):
        return str(current_user.get("user_id") or DEFAULT_USER_ID)
    return str(user_id or DEFAULT_USER_ID).strip() or DEFAULT_USER_ID


@router.get("")
def get_memory(user_id: str = DEFAULT_USER_ID, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    effective_user_id = _effective_user_id(current_user, user_id)
    return {"success": True, "memory": memory_manager.get_user_memory(effective_user_id)}


@router.patch("")
def update_memory(payload: MemoryPatchRequest, user_id: str = DEFAULT_USER_ID, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    effective_user_id = _effective_user_id(current_user, user_id)
    if payload.memory is not None:
        memory = memory_manager.replace_user_memory(effective_user_id, payload.memory)
    else:
        memory = memory_manager.update_user_memory(effective_user_id, payload.patch or {})
    return {"success": True, "memory": memory}


@router.delete("")
def clear_memory(user_id: str = DEFAULT_USER_ID, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    effective_user_id = _effective_user_id(current_user, user_id)
    return {"success": True, "memory": memory_manager.clear_user_memory(effective_user_id), "message": "长期记忆已清空。"}
