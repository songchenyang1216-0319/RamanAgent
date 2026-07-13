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

from backend.repositories.auth_repository import AuthRepository
from backend.security.audit_service import AuditService
from backend.services.workspace_manager import DEFAULT_USER_ID, read_json, write_json
from raman_core.methanol.config import PROJECT_ROOT


USERS_PATH = PROJECT_ROOT / "storage" / "users.json"
TOKENS_PATH = PROJECT_ROOT / "storage" / "auth_tokens.json"
DEFAULT_ADMIN_USERNAME = os.getenv("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
DEFAULT_ACCESS_TOKEN_TTL_MINUTES = int(os.getenv("AUTH_ACCESS_TOKEN_TTL_MINUTES") or os.getenv("ACCESS_TOKEN_TTL_MINUTES", "30") or "30")
DEFAULT_REFRESH_TOKEN_TTL_DAYS = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "30") or "30")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def utcnow() -> datetime:
    return datetime.utcnow()


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


def token_hash(token: str) -> str:
    """Return a non-reversible token hash for storage.

    Development can run without AUTH_SECRET, but production startup rejects that
    configuration before this service is used.
    """

    secret = str(os.getenv("AUTH_SECRET") or "ramanagent-dev-token-pepper").encode("utf-8")
    digest = hmac.new(secret, str(token or "").encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac_sha256${digest}"


def hash_sensitive(value: str) -> str:
    if not value:
        return ""
    secret = str(os.getenv("AUTH_SECRET") or "ramanagent-dev-token-pepper").encode("utf-8")
    digest = hmac.new(secret, str(value).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac_sha256${digest}"


def is_password_strong(password: str) -> bool:
    value = str(password or "")
    if len(value) < 10:
        return False
    has_letter = any(char.isalpha() for char in value)
    has_digit = any(char.isdigit() for char in value)
    has_symbol = any(not char.isalnum() for char in value)
    lowered = value.lower()
    if lowered in {"admin123", "password", "password123", "123456", "12345678"}:
        return False
    return has_letter and has_digit and has_symbol


class UserService:
    """用户、Access Token 和 Refresh Token 服务。

    默认使用数据库主存储；当测试或迁移显式替换 users_path/tokens_path 时，
    自动退回旧 JSON 存储以保持兼容。
    """

    def __init__(self, users_path: Path | None = None, tokens_path: Path | None = None, repository: AuthRepository | None = None) -> None:
        self.users_path = Path(users_path) if users_path is not None else USERS_PATH
        self.tokens_path = Path(tokens_path) if tokens_path is not None else TOKENS_PATH
        self.repository = repository or AuthRepository()
        self.audit_service = AuditService()

    def _use_legacy_json(self) -> bool:
        if str(os.getenv("AUTH_STORAGE_BACKEND", "")).strip().lower() == "json":
            return True
        return self.users_path != USERS_PATH or self.tokens_path != TOKENS_PATH

    def _ensure_database_ready(self) -> None:
        if self._use_legacy_json():
            return
        if str(os.getenv("APP_ENV", "development")).strip().lower() in {"production", "prod", "staging"}:
            return
        from backend.db.init_db import init_database

        init_database()

    def list_users(self) -> list[dict[str, Any]]:
        if not self._use_legacy_json():
            self._ensure_database_ready()
            users = [self._public_user(item) for item in self.repository.list_users()]
            users.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
            return users
        users = self._load_users()
        users.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return users

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        if not self._use_legacy_json():
            self._ensure_database_ready()
            item = self.repository.get_user_by_id(user_id)
            return self._public_user(item) if item else None
        for item in self._load_users():
            if str(item.get("user_id") or "") == str(user_id):
                return dict(item)
        return None

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        if not self._use_legacy_json():
            self._ensure_database_ready()
            item = self.repository.get_user_by_username(username)
            return self._public_user(item) if item else None
        normalized = str(username or "").strip().lower()
        for item in self._load_users():
            if str(item.get("username") or "").strip().lower() == normalized:
                return dict(item)
        return None

    def create_user(self, username: str, password: str, role: str = "user", *, is_active: bool = True, user_id: str | None = None) -> dict[str, Any]:
        cleaned_username = str(username or "").strip()
        if len(cleaned_username) < 3:
            raise ValueError("用户名至少需要 3 个字符。")
        if not is_password_strong(password):
            raise ValueError("密码至少需要 10 个字符，并同时包含字母、数字和符号。")
        if role not in {"admin", "user"}:
            raise ValueError("role 只支持 admin 或 user。")
        if not self._use_legacy_json():
            self._ensure_database_ready()
            if self.repository.get_user_by_username(cleaned_username) is not None:
                raise ValueError("用户名已存在。")
            payload = {
                "user_id": str(user_id or uuid4().hex),
                "username": cleaned_username,
                "password_hash": _pbkdf2_hash(password),
                "role": role,
                "is_active": 1 if is_active else 0,
                "is_frozen": 0,
                "created_at": utcnow(),
                "updated_at": utcnow(),
                "last_login_at": None,
            }
            return self._public_user(self.repository.create_user(payload))
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
        if not self._use_legacy_json():
            self._ensure_database_ready()
            raw_user = self.repository.get_user_by_username(username)
            if not raw_user or not bool(raw_user.get("is_active")) or bool(raw_user.get("is_frozen")):
                return None
            if not verify_password_hash(password, str(raw_user.get("password_hash") or "")):
                return None
            return self._public_user(raw_user)
        user = self.get_user_by_username(username)
        if not user or not bool(user.get("is_active")):
            return None
        if not verify_password_hash(password, str(user.get("password_hash") or "")):
            return None
        return self._public_user(user)

    def create_token(self, user_id: str, *, ttl_minutes: int | None = None, user_agent: str | None = None, ip_hash: str | None = None, refresh_token_id: str | None = None) -> dict[str, Any]:
        user = self.get_user_by_id(user_id)
        if user is None:
            raise KeyError("用户不存在。")
        ttl = max(5, int(ttl_minutes or DEFAULT_ACCESS_TOKEN_TTL_MINUTES))
        expires_at = utcnow() + timedelta(minutes=ttl)
        token = secrets.token_urlsafe(32)
        if not self._use_legacy_json():
            self._ensure_database_ready()
            item = self.repository.create_access_token(
                {
                    "token_id": uuid4().hex,
                    "token_hash": token_hash(token),
                    "user_id": user_id,
                    "refresh_token_id": refresh_token_id,
                    "created_at": utcnow(),
                    "updated_at": utcnow(),
                    "expires_at": expires_at,
                    "revoked_at": None,
                    "last_used_at": None,
                    "user_agent": user_agent,
                    "ip_hash": ip_hash,
                }
            )
            self.touch_last_login(user_id)
            return {
                "token": token,
                "token_type": "bearer",
                "access_token_expires_at": expires_at.isoformat(timespec="seconds"),
                "expires_at": expires_at.isoformat(timespec="seconds"),
                "session_id": refresh_token_id,
                "user": self._public_user(user),
                "token_id": item.get("token_id"),
            }
        tokens = self._load_tokens()
        tokens = [item for item in tokens if str(item.get("user_id") or "") != str(user_id) or self._is_token_active(item)]
        tokens.append(
            {
                "token_id": uuid4().hex,
                "token_hash": token_hash(token),
                "user_id": user_id,
                "created_at": now_iso(),
                "expires_at": expires_at.isoformat(timespec="seconds"),
                "revoked_at": None,
                "last_used_at": None,
                "user_agent": user_agent,
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
        hashed = token_hash(token)
        if not self._use_legacy_json():
            self._ensure_database_ready()
            item = self.repository.get_access_token_by_hash(hashed)
            if item:
                self.repository.update_access_token(str(item["token_id"]), revoked_at=utcnow())
            return
        tokens = self._load_tokens()
        changed = False
        for item in tokens:
            if str(item.get("token_hash") or "") == hashed or str(item.get("token") or "") == str(token):
                item["is_active"] = False
                item["revoked_at"] = now_iso()
                changed = True
        if changed:
            self._save_tokens(tokens)

    def get_user_by_token(self, token: str) -> dict[str, Any] | None:
        if not token:
            return None
        hashed = token_hash(token)
        if not self._use_legacy_json():
            self._ensure_database_ready()
            item = self.repository.get_access_token_by_hash(hashed)
            if not item or not self._is_token_active(item):
                return None
            self.repository.update_access_token(str(item["token_id"]), last_used_at=utcnow())
            return self.get_user_by_id(str(item.get("user_id") or ""))
        active = None
        tokens = self._load_tokens()
        for item in tokens:
            if str(item.get("token_hash") or "") == hashed or str(item.get("token") or "") == str(token):
                active = item
                break
        if not active or not self._is_token_active(active):
            return None
        active["last_used_at"] = now_iso()
        self._save_tokens(tokens)
        return self.get_user_by_id(str(active.get("user_id") or ""))

    def create_token_pair(self, user_id: str, *, user_agent: str | None = None, ip_hash: str | None = None) -> dict[str, Any]:
        if self._use_legacy_json():
            token_payload = self.create_token(user_id, user_agent=user_agent, ip_hash=ip_hash)
            refresh_token = secrets.token_urlsafe(48)
            token_payload["refresh_token"] = refresh_token
            token_payload["refresh_token_expires_at"] = (utcnow() + timedelta(days=DEFAULT_REFRESH_TOKEN_TTL_DAYS)).isoformat(timespec="seconds")
            return token_payload

        self._ensure_database_ready()
        refresh_token = secrets.token_urlsafe(48)
        refresh_token_id = uuid4().hex
        family_id = uuid4().hex
        refresh_expires_at = utcnow() + timedelta(days=max(1, DEFAULT_REFRESH_TOKEN_TTL_DAYS))
        self.repository.create_refresh_token(
            {
                "refresh_token_id": refresh_token_id,
                "user_id": user_id,
                "token_hash": token_hash(refresh_token),
                "token_family_id": family_id,
                "parent_token_id": None,
                "created_at": utcnow(),
                "updated_at": utcnow(),
                "expires_at": refresh_expires_at,
                "last_used_at": None,
                "revoked_at": None,
                "rotated_at": None,
                "replaced_by_token_id": None,
                "user_agent": user_agent,
                "ip_hash": ip_hash,
            }
        )
        access = self.create_token(user_id, user_agent=user_agent, ip_hash=ip_hash, refresh_token_id=refresh_token_id)
        access["refresh_token"] = refresh_token
        access["refresh_token_expires_at"] = refresh_expires_at.isoformat(timespec="seconds")
        access["session_id"] = refresh_token_id
        return access

    def rotate_refresh_token(self, refresh_token: str, *, user_agent: str | None = None, ip_hash: str | None = None) -> dict[str, Any] | None:
        if self._use_legacy_json():
            return None
        self._ensure_database_ready()
        hashed = token_hash(refresh_token)
        current = self.repository.get_refresh_token_by_hash(hashed)
        if current is None:
            return None
        now = utcnow()
        if current.get("revoked_at") or current.get("rotated_at") or self._is_expired(current.get("expires_at")):
            self.repository.revoke_refresh_family(str(current.get("token_family_id") or ""))
            self.repository.revoke_user_access_tokens(str(current.get("user_id") or ""))
            self.audit_service.record(
                user_id=str(current.get("user_id") or ""),
                action="auth.refresh_replay",
                resource_type="refresh_token_family",
                resource_id=str(current.get("token_family_id") or ""),
                detail={"reason": "reused_or_expired_refresh_token"},
            )
            return {"success": False, "error_code": "AUTH_REFRESH_REPLAY", "message": "Refresh Token 已失效，请重新登录。"}

        new_token = secrets.token_urlsafe(48)
        new_refresh_token_id = uuid4().hex
        refresh_expires_at = now + timedelta(days=max(1, DEFAULT_REFRESH_TOKEN_TTL_DAYS))
        self.repository.create_refresh_token(
            {
                "refresh_token_id": new_refresh_token_id,
                "user_id": current["user_id"],
                "token_hash": token_hash(new_token),
                "token_family_id": current["token_family_id"],
                "parent_token_id": current["refresh_token_id"],
                "created_at": now,
                "updated_at": now,
                "expires_at": refresh_expires_at,
                "last_used_at": None,
                "revoked_at": None,
                "rotated_at": None,
                "replaced_by_token_id": None,
                "user_agent": user_agent,
                "ip_hash": ip_hash,
            }
        )
        self.repository.update_refresh_token(
            str(current["refresh_token_id"]),
            last_used_at=now,
            rotated_at=now,
            revoked_at=now,
            replaced_by_token_id=new_refresh_token_id,
        )
        access = self.create_token(str(current["user_id"]), user_agent=user_agent, ip_hash=ip_hash, refresh_token_id=new_refresh_token_id)
        access["refresh_token"] = new_token
        access["refresh_token_expires_at"] = refresh_expires_at.isoformat(timespec="seconds")
        access["session_id"] = new_refresh_token_id
        return {"success": True, **access}

    def revoke_refresh_token(self, refresh_token_id: str, *, user_id: str | None = None) -> bool:
        if self._use_legacy_json():
            return False
        item = self.repository.get_refresh_token(refresh_token_id)
        if item is None:
            return False
        if user_id and str(item.get("user_id") or "") != str(user_id):
            return False
        self.repository.revoke_refresh_token(refresh_token_id)
        self.repository.revoke_user_access_tokens(str(item.get("user_id") or ""), refresh_token_id=refresh_token_id)
        return True

    def revoke_refresh_token_value(self, refresh_token: str) -> bool:
        if self._use_legacy_json() or not refresh_token:
            return False
        item = self.repository.get_refresh_token_by_hash(token_hash(refresh_token))
        if item is None:
            return False
        return self.revoke_refresh_token(str(item["refresh_token_id"]), user_id=str(item.get("user_id") or ""))

    def revoke_all_sessions(self, user_id: str) -> int:
        if self._use_legacy_json():
            tokens = self._load_tokens()
            count = 0
            for item in tokens:
                if str(item.get("user_id") or "") == str(user_id) and bool(item.get("is_active")):
                    item["is_active"] = False
                    item["revoked_at"] = now_iso()
                    count += 1
            self._save_tokens(tokens)
            return count
        sessions = self.repository.list_refresh_tokens_for_user(user_id)
        count = 0
        for item in sessions:
            if not item.get("revoked_at"):
                self.repository.revoke_refresh_token(str(item["refresh_token_id"]))
                count += 1
        self.repository.revoke_user_access_tokens(user_id)
        return count

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        if self._use_legacy_json():
            return []
        sessions = self.repository.list_refresh_tokens_for_user(user_id)
        result = []
        for item in sessions:
            result.append(
                {
                    "session_id": item.get("refresh_token_id"),
                    "created_at": self._stringify_dt(item.get("created_at")),
                    "expires_at": self._stringify_dt(item.get("expires_at")),
                    "last_used_at": self._stringify_dt(item.get("last_used_at")),
                    "revoked_at": self._stringify_dt(item.get("revoked_at")),
                    "rotated_at": self._stringify_dt(item.get("rotated_at")),
                    "user_agent": item.get("user_agent"),
                    "active": not bool(item.get("revoked_at")) and not self._is_expired(item.get("expires_at")),
                }
            )
        return result

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
        for key in ("created_at", "updated_at", "last_login_at", "deleted_at"):
            if key in payload:
                payload[key] = self._stringify_dt(payload.get(key))
        return payload

    def _is_token_active(self, token_item: dict[str, Any]) -> bool:
        if "is_active" in token_item and not bool(token_item.get("is_active")):
            return False
        if token_item.get("revoked_at"):
            return False
        expires_at = str(token_item.get("expires_at") or "").strip()
        if not expires_at:
            return False
        try:
            return datetime.fromisoformat(expires_at) > utcnow()
        except Exception:
            return False

    def _is_expired(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, datetime):
            return value <= utcnow()
        try:
            return datetime.fromisoformat(str(value)) <= utcnow()
        except Exception:
            return True

    def _stringify_dt(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat(timespec="seconds")
        return value

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
