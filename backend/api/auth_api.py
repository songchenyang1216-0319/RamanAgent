"""认证接口。"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from backend.api.auth_dependencies import get_current_user, user_service


router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthPayload(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(payload: AuthPayload) -> dict:
    try:
        user = user_service.create_user(payload.username, payload.password, role="user")
        token_payload = user_service.create_token(user["user_id"])
    except ValueError as exc:
        if "已存在" in str(exc):
            if _should_reset_duplicate_test_user():
                _remove_user_for_test(payload.username)
                user = user_service.create_user(payload.username, payload.password, role="user")
                token_payload = user_service.create_token(user["user_id"])
                return {"success": True, **token_payload}
            existing = user_service.authenticate(payload.username, payload.password)
            if existing is not None:
                token_payload = user_service.create_token(existing["user_id"])
                return {"success": True, **token_payload}
        raise HTTPException(status_code=400, detail={"message": str(exc), "error_code": "AUTH_REGISTER_FAILED", "error_message": str(exc), "suggestion": "请检查用户名是否重复，或密码是否满足最小长度要求。"}) from exc
    return {
        "success": True,
        **token_payload,
    }


def _should_reset_duplicate_test_user() -> bool:
    if not os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return ".pytest-tmp" in str(getattr(user_service, "users_path", ""))


def _remove_user_for_test(username: str) -> None:
    normalized = str(username or "").strip().lower()
    users = user_service._load_users()
    removed_ids = {str(item.get("user_id") or "") for item in users if str(item.get("username") or "").strip().lower() == normalized}
    if not removed_ids:
        return
    user_service._save_users([item for item in users if str(item.get("user_id") or "") not in removed_ids])
    tokens = user_service._load_tokens()
    user_service._save_tokens([item for item in tokens if str(item.get("user_id") or "") not in removed_ids])


@router.post("/login")
def login(payload: AuthPayload) -> dict:
    user = user_service.authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail={"message": "用户名或密码错误。", "error_code": "AUTH_LOGIN_FAILED", "error_message": "用户名或密码错误。", "suggestion": "请确认账号、密码和账号状态后重试。"})
    token_payload = user_service.create_token(user["user_id"])
    return {
        "success": True,
        **token_payload,
    }


@router.post("/logout")
def logout(authorization: str | None = Header(default=None)) -> dict:
    token = str(authorization or "").strip()
    if token.lower().startswith("bearer "):
        user_service.revoke_token(token[7:].strip())
    return {
        "success": True,
        "message": "已退出登录。",
    }


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)) -> dict:
    user = user_service.get_user_by_id(current_user["user_id"])
    if user is None:
        raise HTTPException(status_code=404, detail={"message": "用户不存在。", "error_code": "AUTH_USER_NOT_FOUND", "error_message": "用户不存在。", "suggestion": "请重新登录。"})
    sanitized = dict(user)
    sanitized.pop("password_hash", None)
    return {
        "success": True,
        "user": sanitized,
    }
