"""用户与认证基础服务。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.workspace_manager import DEFAULT_USER_ID, read_json, write_json
from raman_core.methanol.config import PROJECT_ROOT


USERS_PATH = PROJECT_ROOT / "storage" / "users.json"
TOKENS_PATH = PROJECT_ROOT / "storage" / "auth_tokens.json"
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
DEFAULT_TOKEN_TTL_HOURS = int(os.getenv("AUTH_TOKEN_TTL_HOURS", "72") or "72")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _pbkdf2_hash(password: str, salt: bytes | None = None) -> str:
    raw_salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), raw_salt, 120_000)
    return "pbkdf2_sha256$120000$%s$%s" % (
        base64.b64encode(raw_salt).decode("ascii"),
        base64.b64encode(derived).decode("ascii"),
    )


def verify_password_hash(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, digest_text = str(password_hash or "").split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text.encode("ascii"))
        expected = base64.b64decode(digest_text.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


class UserService:
    """基于 JSON 的最小用户与会话令牌服务。"""

    def __init__(self, users_path: Path | None = None, tokens_path: Path | None = None) -> None:
        self.users_path = Path(users_path) if users_path is not None else USERS_PATH
        self.tokens_path = Path(tokens_path) if tokens_path is not None else TOKENS_PATH

    def list_users(self) -> list[dict[str, Any]]:
        users = self._load_users()
        users.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return users

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        for item in self._load_users():
            if str(item.get("user_id") or "") == str(user_id):
                return dict(item)
        return None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        normalized = str(username or "").strip().lower()
        for item in self._load_users():
            if str(item.get("username") or "").strip().lower() == normalized:
                return dict(item)
        return None

    def create_user(self, username: str, password: str, role: str = "user", *, is_active: bool = True, user_id: str | None = None) -> dict[str, Any]:
        cleaned_username = str(username or "").strip()
        if len(cleaned_username) < 3:
            raise ValueError("用户名至少需要 3 个字符。")
        if len(str(password or "")) < 6:
            raise ValueError("密码至少需要 6 个字符。")
        if role not in {"admin", "user"}:
            raise ValueError("role 只支持 admin 或 user。")
        users = self._load_users()
        if any(str(item.get("username") or "").strip().lower() == cleaned_username.lower() for item in users):
            raise ValueError("用户名已存在。")
        payload = {
            "user_id": str(user_id or uuid4().hex),
            "username": cleaned_username,
            "password_hash": _pbkdf2_hash(password),
            "role": role,
            "created_at": now_iso(),
            "last_login_at": None,
            "is_active": bool(is_active),
        }
        users.append(payload)
        self._save_users(users)
        return self._public_user(payload)

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_user_by_username(username)
        if not user or not bool(user.get("is_active")):
            return None
        if not verify_password_hash(password, str(user.get("password_hash") or "")):
            return None
        return self._public_user(user)

    def create_token(self, user_id: str, *, ttl_hours: int | None = None) -> dict[str, Any]:
        user = self.get_user_by_id(user_id)
        if user is None:
            raise KeyError("用户不存在。")
        expires_at = datetime.now() + timedelta(hours=max(1, int(ttl_hours or DEFAULT_TOKEN_TTL_HOURS)))
        token = secrets.token_urlsafe(32)
        tokens = self._load_tokens()
        tokens = [item for item in tokens if str(item.get("user_id") or "") != str(user_id) or self._is_token_active(item)]
        tokens.append(
            {
                "token": token,
                "user_id": user_id,
                "created_at": now_iso(),
                "expires_at": expires_at.isoformat(timespec="seconds"),
                "is_active": True,
            }
        )
        self._save_tokens(tokens)
        self.touch_last_login(user_id)
        return {
            "token": token,
            "token_type": "bearer",
            "expires_at": expires_at.isoformat(timespec="seconds"),
            "user": self._public_user(user),
        }

    def revoke_token(self, token: str) -> None:
        tokens = self._load_tokens()
        changed = False
        for item in tokens:
            if str(item.get("token") or "") == str(token):
                item["is_active"] = False
                changed = True
        if changed:
            self._save_tokens(tokens)

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        active = None
        tokens = self._load_tokens()
        for item in tokens:
            if str(item.get("token") or "") == str(token):
                active = item
                break
        if not active or not self._is_token_active(active):
            return None
        return self.get_user_by_id(str(active.get("user_id") or ""))

    def ensure_default_admin(self, *, app_env: str) -> dict[str, Any] | None:
        if str(app_env or "").strip().lower() != "development":
            return None
        existing = self.get_user_by_username(DEFAULT_ADMIN_USERNAME)
        if existing:
            if str(existing.get("user_id") or "") != DEFAULT_USER_ID:
                return self._public_user(existing)
            return self._public_user(existing)
        users = self._load_users()
        payload = {
            "user_id": DEFAULT_USER_ID,
            "username": DEFAULT_ADMIN_USERNAME,
            "password_hash": _pbkdf2_hash(DEFAULT_ADMIN_PASSWORD),
            "role": "admin",
            "created_at": now_iso(),
            "last_login_at": None,
            "is_active": True,
        }
        users.append(payload)
        self._save_users(users)
        return self._public_user(payload)

    def touch_last_login(self, user_id: str) -> None:
        users = self._load_users()
        changed = False
        for item in users:
            if str(item.get("user_id") or "") == str(user_id):
                item["last_login_at"] = now_iso()
                changed = True
                break
        if changed:
            self._save_users(users)

    def _public_user(self, user: dict[str, Any]) -> dict[str, Any]:
        payload = dict(user or {})
        payload.pop("password_hash", None)
        return payload

    def _is_token_active(self, token_item: dict[str, Any]) -> bool:
        if not bool(token_item.get("is_active")):
            return False
        expires_at = str(token_item.get("expires_at") or "").strip()
        if not expires_at:
            return False
        try:
            return datetime.fromisoformat(expires_at) > datetime.now()
        except Exception:
            return False

    def _load_users(self) -> list[dict[str, Any]]:
        value = read_json(self.users_path, [])
        return value if isinstance(value, list) else []

    def _save_users(self, users: list[dict[str, Any]]) -> None:
        write_json(self.users_path, users)

    def _load_tokens(self) -> list[dict[str, Any]]:
        value = read_json(self.tokens_path, [])
        return value if isinstance(value, list) else []

    def _save_tokens(self, tokens: list[dict[str, Any]]) -> None:
        write_json(self.tokens_path, tokens)
