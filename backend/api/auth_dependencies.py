"""认证与权限依赖。"""

from __future__ import annotations

import os
from typing import Any

from fastapi import Header, HTTPException

from backend.services.user_service import UserService
from backend.services.workspace_manager import DEFAULT_USER_ID


user_service = UserService()


def get_app_env() -> str:
    return str(os.getenv("APP_ENV", "development") or "development").strip().lower()


def _extract_bearer_token(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    if not value.lower().startswith("bearer "):
        return ""
    return value[7:].strip()


def get_request_user_context(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """开发环境允许 fallback 到默认管理员，生产环境必须显式登录。"""
    app_env = get_app_env()
    token = _extract_bearer_token(authorization)
    if token:
        user = user_service.get_user_by_token(token)
        if user is None:
            raise HTTPException(status_code=401, detail={"message": "登录状态已失效。", "error_code": "AUTH_INVALID_TOKEN", "error_message": "登录状态已失效。", "suggestion": "请重新登录后重试。"})
        return {
            "authenticated": True,
            "token": token,
            "user_id": user["user_id"],
            "username": user["username"],
            "role": user.get("role") or "user",
            "is_admin": str(user.get("role") or "") == "admin",
            "app_env": app_env,
        }

    if app_env == "development":
        fallback = user_service.ensure_default_admin(app_env=app_env) or {
            "user_id": DEFAULT_USER_ID,
            "username": "admin",
            "role": "admin",
        }
        return {
            "authenticated": False,
            "token": "",
            "user_id": fallback["user_id"],
            "username": fallback["username"],
            "role": fallback.get("role") or "admin",
            "is_admin": True,
            "app_env": app_env,
        }

    raise HTTPException(status_code=401, detail={"message": "当前接口需要登录后访问。", "error_code": "AUTH_REQUIRED", "error_message": "当前接口需要登录后访问。", "suggestion": "请先注册或登录。"})


def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    context = get_request_user_context(authorization=authorization)
    if not context.get("authenticated") and context.get("app_env") != "development":
        raise HTTPException(status_code=401, detail={"message": "当前接口需要登录后访问。", "error_code": "AUTH_REQUIRED", "error_message": "当前接口需要登录后访问。", "suggestion": "请先登录后再继续。"})
    return context


def require_admin(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    context = get_request_user_context(authorization=authorization)
    if not bool(context.get("is_admin")):
        raise HTTPException(status_code=403, detail={"message": "当前接口仅管理员可访问。", "error_code": "AUTH_ADMIN_REQUIRED", "error_message": "当前接口仅管理员可访问。", "suggestion": "请使用管理员账号重试。"})
    return context
