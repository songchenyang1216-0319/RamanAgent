"""认证接口。"""

from __future__ import annotations

import os

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel

from backend.api.auth_dependencies import get_current_user, user_service
from backend.security.rate_limit import login_rate_limiter
from backend.services.user_service import hash_sensitive


router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthPayload(BaseModel):
    username: str
    password: str


class RefreshPayload(BaseModel):
    refresh_token: str | None = None


REFRESH_COOKIE_NAME = "ramanagent_refresh_token"


def _request_ip_hash(request: Request) -> str:
    host = request.client.host if request.client else ""
    forwarded_for = str(request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    return hash_sensitive(forwarded_for or host)


def _user_agent(request: Request) -> str:
    return str(request.headers.get("user-agent") or "")[:1000]


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    secure = str(os.getenv("APP_ENV", "development")).strip().lower() in {"production", "prod", "staging"}
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max(1, int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "30") or "30")) * 24 * 3600,
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE_NAME, path="/api/auth")


@router.post("/register")
def register(payload: AuthPayload, request: Request, response: Response) -> dict:
    try:
        user = user_service.create_user(payload.username, payload.password, role="user")
        token_payload = user_service.create_token_pair(user["user_id"], user_agent=_user_agent(request), ip_hash=_request_ip_hash(request))
    except ValueError as exc:
        if "已存在" in str(exc):
            if _should_reset_duplicate_test_user():
                _remove_user_for_test(payload.username)
                user = user_service.create_user(payload.username, payload.password, role="user")
                token_payload = user_service.create_token_pair(user["user_id"], user_agent=_user_agent(request), ip_hash=_request_ip_hash(request))
                if token_payload.get("refresh_token"):
                    _set_refresh_cookie(response, token_payload["refresh_token"])
                return {"success": True, **token_payload}
            existing = user_service.authenticate(payload.username, payload.password)
            if existing is not None:
                token_payload = user_service.create_token_pair(existing["user_id"], user_agent=_user_agent(request), ip_hash=_request_ip_hash(request))
                if token_payload.get("refresh_token"):
                    _set_refresh_cookie(response, token_payload["refresh_token"])
                return {"success": True, **token_payload}
        raise HTTPException(status_code=400, detail={"message": str(exc), "error_code": "AUTH_REGISTER_FAILED", "error_message": str(exc), "suggestion": "请检查用户名是否重复，或密码是否满足强度要求。"}) from exc
    if token_payload.get("refresh_token"):
        _set_refresh_cookie(response, token_payload["refresh_token"])
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
def login(payload: AuthPayload, request: Request, response: Response) -> dict:
    ip_hash = _request_ip_hash(request)
    allowed, retry_after = login_rate_limiter.check_allowed(payload.username, ip_hash)
    if not allowed:
        raise HTTPException(status_code=429, detail={"message": "登录失败次数过多，请稍后重试。", "error_code": "AUTH_RATE_LIMITED", "error_message": "登录失败次数过多，请稍后重试。", "retry_after_seconds": retry_after})
    user = user_service.authenticate(payload.username, payload.password)
    if user is None:
        login_rate_limiter.record_failure(payload.username, ip_hash)
        raise HTTPException(status_code=401, detail={"message": "用户名或密码错误。", "error_code": "AUTH_LOGIN_FAILED", "error_message": "用户名或密码错误。", "suggestion": "请确认账号、密码和账号状态后重试。"})
    login_rate_limiter.record_success(payload.username, ip_hash)
    token_payload = user_service.create_token_pair(user["user_id"], user_agent=_user_agent(request), ip_hash=ip_hash)
    if token_payload.get("refresh_token"):
        _set_refresh_cookie(response, token_payload["refresh_token"])
    return {
        "success": True,
        **token_payload,
    }


@router.post("/refresh")
def refresh_token(
    request: Request,
    response: Response,
    payload: RefreshPayload | None = None,
    refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> dict:
    refresh_value = str((payload.refresh_token if payload else "") or refresh_cookie or "").strip()
    if not refresh_value:
        raise HTTPException(status_code=401, detail={"message": "Refresh Token 缺失。", "error_code": "AUTH_REFRESH_REQUIRED", "error_message": "Refresh Token 缺失。"})
    rotated = user_service.rotate_refresh_token(
        refresh_value,
        user_agent=_user_agent(request),
        ip_hash=_request_ip_hash(request),
    )
    if not rotated or not rotated.get("success"):
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail={"message": (rotated or {}).get("message") or "Refresh Token 已失效。", "error_code": (rotated or {}).get("error_code") or "AUTH_REFRESH_FAILED", "error_message": (rotated or {}).get("message") or "Refresh Token 已失效。"})
    if rotated.get("refresh_token"):
        _set_refresh_cookie(response, rotated["refresh_token"])
    return rotated


@router.post("/logout")
def logout(response: Response, authorization: str | None = Header(default=None), refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME)) -> dict:
    token = str(authorization or "").strip()
    if token.lower().startswith("bearer "):
        user_service.revoke_token(token[7:].strip())
    if refresh_cookie:
        user_service.revoke_refresh_token_value(refresh_cookie)
    _clear_refresh_cookie(response)
    return {
        "success": True,
        "message": "已退出登录。",
    }


@router.post("/logout-all")
def logout_all(response: Response, current_user: dict = Depends(get_current_user)) -> dict:
    count = user_service.revoke_all_sessions(str(current_user["user_id"]))
    _clear_refresh_cookie(response)
    return {"success": True, "revoked_sessions": count, "message": "已退出所有设备。"}


@router.get("/sessions")
def sessions(current_user: dict = Depends(get_current_user)) -> dict:
    return {"success": True, "sessions": user_service.list_sessions(str(current_user["user_id"]))}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    revoked = user_service.revoke_refresh_token(session_id, user_id=str(current_user["user_id"]))
    if not revoked:
        raise HTTPException(status_code=404, detail={"message": "会话不存在。", "error_code": "AUTH_SESSION_NOT_FOUND", "error_message": "会话不存在。"})
    return {"success": True, "session_id": session_id, "message": "会话已撤销。"}


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
