"""ChatGPT-style conversation APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.agent.session_store import (
    create_session,
    delete_session,
    get_recent_messages,
    get_session,
    list_sessions,
    rename_session,
    search_sessions,
    update_session,
)
from backend.api.auth_dependencies import get_request_user_context
from backend.security.ownership_guard import ownership_guard
from backend.security.resource_scope import ResourceScope
from backend.services.workspace_manager import DEFAULT_USER_ID, WorkspaceManager


router = APIRouter(prefix="/api/conversations", tags=["conversations"])
workspace_manager = WorkspaceManager()


class CreateConversationRequest(BaseModel):
    title: str | None = None
    user_id: str | None = None


class UpdateConversationRequest(BaseModel):
    title: str | None = None
    is_deleted: bool | None = None


class SearchMessagesRequest(BaseModel):
    query: str
    limit: int = 30


def _effective_user_id(current_user: dict[str, Any], explicit_user_id: str | None = None) -> str:
    if current_user.get("authenticated"):
        return str(current_user.get("user_id") or DEFAULT_USER_ID)
    return str(explicit_user_id or DEFAULT_USER_ID).strip() or DEFAULT_USER_ID


def _ensure_owner(session: dict[str, Any] | None, user_id: str, current_user: dict[str, Any]) -> dict[str, Any]:
    if session is None or bool(session.get("is_deleted")):
        raise HTTPException(status_code=404, detail="会话不存在。")
    if current_user.get("is_admin"):
        return session
    if str(session.get("user_id") or DEFAULT_USER_ID) != str(user_id):
        raise HTTPException(status_code=403, detail="无权访问该会话。")
    return session


def _scope(current_user: dict[str, Any]) -> ResourceScope:
    return ResourceScope.from_auth_context(current_user)


@router.get("")
def list_conversations(
    user_id: str = Query(default=DEFAULT_USER_ID),
    q: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user_id = _effective_user_id(current_user, user_id)
    conversations = search_sessions(effective_user_id, q, limit=limit) if q.strip() else list_sessions(effective_user_id, limit=limit)
    return {
        "success": True,
        "user_id": effective_user_id,
        "conversations": conversations,
        "total": len(conversations),
    }


@router.post("")
def create_conversation(payload: CreateConversationRequest | None = None, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    payload = payload or CreateConversationRequest()
    effective_user_id = _effective_user_id(current_user, payload.user_id)
    session = create_session(user_id=effective_user_id)
    if payload.title:
        session = rename_session(str(session["session_id"]), payload.title)
    workspace = workspace_manager.create_workspace(effective_user_id, str(session["session_id"]))
    update_session(str(session["session_id"]), "user_id", workspace["user_id"])
    return {
        "success": True,
        "conversation": {
            "conversation_id": session["session_id"],
            "session_id": session["session_id"],
            "user_id": workspace["user_id"],
            "title": session.get("title") or "新聊天",
            "summary": session.get("summary") or "",
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
            "message_count": int(session.get("message_count") or 0),
        },
    }


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user_id = _effective_user_id(current_user, user_id)
    if current_user.get("authenticated"):
        session = ownership_guard.require_conversation_owner(conversation_id, _scope(current_user))
        effective_user_id = str(session.get("user_id") or effective_user_id)
    else:
        session = _ensure_owner(get_session(conversation_id), effective_user_id, current_user)
    workspace = workspace_manager.read_workspace_context(effective_user_id, conversation_id)
    return {
        "success": True,
        "conversation": {
            "conversation_id": session["session_id"],
            "session_id": session["session_id"],
            "user_id": session.get("user_id") or effective_user_id,
            "title": session.get("title") or "新聊天",
            "summary": session.get("summary") or "",
            "created_at": session.get("created_at"),
            "updated_at": session.get("updated_at"),
            "message_count": int(session.get("message_count") or 0),
            "last_file": session.get("last_file"),
            "last_report": session.get("last_report"),
            "task_state": session.get("task_state") or {},
        },
        "workspace": workspace,
    }


@router.patch("/{conversation_id}")
def update_conversation(conversation_id: str, payload: UpdateConversationRequest, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    session = get_session(conversation_id)
    user_id = str((session or {}).get("user_id") or DEFAULT_USER_ID)
    if current_user.get("authenticated"):
        ownership_guard.require_conversation_owner(conversation_id, _scope(current_user))
    else:
        _ensure_owner(session, user_id, current_user)
    if payload.title is not None:
        session = rename_session(conversation_id, payload.title)
    if payload.is_deleted is not None:
        session = update_session(conversation_id, "is_deleted", bool(payload.is_deleted))
    return {
        "success": True,
        "conversation": {
            "conversation_id": conversation_id,
            "session_id": conversation_id,
            "user_id": session.get("user_id") or user_id,
            "title": session.get("title") or "新聊天",
            "summary": session.get("summary") or "",
            "updated_at": session.get("updated_at"),
            "is_deleted": bool(session.get("is_deleted")),
        },
    }


@router.delete("/{conversation_id}")
def remove_conversation(conversation_id: str, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    session = get_session(conversation_id)
    user_id = str((session or {}).get("user_id") or DEFAULT_USER_ID)
    if current_user.get("authenticated"):
        ownership_guard.require_conversation_owner(conversation_id, _scope(current_user))
    else:
        _ensure_owner(session, user_id, current_user)
    deleted = delete_session(conversation_id)
    return {
        "success": True,
        "conversation_id": conversation_id,
        "session_id": conversation_id,
        "is_deleted": bool(deleted.get("is_deleted", True)),
        "message": "会话已删除。",
    }


@router.get("/{conversation_id}/messages")
def list_messages(
    conversation_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    effective_user_id = _effective_user_id(current_user, user_id)
    if current_user.get("authenticated"):
        ownership_guard.require_conversation_owner(conversation_id, _scope(current_user))
    else:
        _ensure_owner(get_session(conversation_id), effective_user_id, current_user)
    return {
        "success": True,
        "conversation_id": conversation_id,
        "session_id": conversation_id,
        "messages": get_recent_messages(conversation_id, limit=limit),
    }


@router.post("/{conversation_id}/messages/search")
def search_messages(conversation_id: str, payload: SearchMessagesRequest, current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    session = get_session(conversation_id)
    user_id = str((session or {}).get("user_id") or DEFAULT_USER_ID)
    if current_user.get("authenticated"):
        ownership_guard.require_conversation_owner(conversation_id, _scope(current_user))
    else:
        _ensure_owner(session, user_id, current_user)
    keyword = str(payload.query or "").strip().lower()
    messages = get_recent_messages(conversation_id, limit=500)
    if keyword:
        messages = [item for item in messages if keyword in str(item.get("content") or "").lower()]
    limit = max(1, min(int(payload.limit or 30), 100))
    return {
        "success": True,
        "conversation_id": conversation_id,
        "messages": messages[-limit:],
        "total": len(messages[-limit:]),
    }
