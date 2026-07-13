from __future__ import annotations

import os
from collections.abc import Mapping


PRODUCTION_ENVS = {"production", "prod", "staging"}
PLACEHOLDER_SECRETS = {
    "",
    "changeme",
    "change_me",
    "change_me_in_production",
    "replace_me",
    "placeholder",
    "your_auth_secret",
    "your_auth_secret_here",
}
WEAK_DEFAULT_PASSWORDS = {
    "admin",
    "admin123",
    "password",
    "password123",
    "123456",
    "12345678",
    "changeme",
    "change_me",
}


def is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def get_app_env(env: Mapping[str, str] | None = None) -> str:
    source = env or os.environ
    return str(source.get("APP_ENV", "development") or "development").strip().lower()


def _is_placeholder_secret(value: str) -> bool:
    cleaned = str(value or "").strip().lower()
    return cleaned in PLACEHOLDER_SECRETS or cleaned.startswith(("your_", "example_", "dummy_"))


def _is_weak_password(value: str) -> bool:
    cleaned = str(value or "").strip()
    lowered = cleaned.lower()
    if lowered in WEAK_DEFAULT_PASSWORDS:
        return True
    if len(cleaned) < 12:
        return True
    has_letter = any(char.isalpha() for char in cleaned)
    has_digit = any(char.isdigit() for char in cleaned)
    has_symbol = any(not char.isalnum() for char in cleaned)
    return not (has_letter and has_digit and has_symbol)


def validate_runtime_security(env: Mapping[str, str] | None = None) -> list[str]:
    source = env or os.environ
    app_env = get_app_env(source)
    if app_env not in PRODUCTION_ENVS:
        return []

    issues: list[str] = []
    auth_secret = str(source.get("AUTH_SECRET", "") or "").strip()
    if len(auth_secret) < 32 or _is_placeholder_secret(auth_secret):
        issues.append("production/staging must set AUTH_SECRET to a non-placeholder value with at least 32 characters")

    default_password = str(source.get("DEFAULT_ADMIN_PASSWORD", "admin123") or "").strip()
    if _is_weak_password(default_password):
        issues.append("production/staging must not use the default or weak admin password")

    if is_truthy(source.get("ALLOW_ANONYMOUS_DEV")):
        issues.append("ALLOW_ANONYMOUS_DEV must not be set in production/staging")

    if str(source.get("VECTOR_DB_PROVIDER", "") or "").strip().lower() == "mock":
        issues.append("production/staging must not use VECTOR_DB_PROVIDER=mock")

    if str(source.get("EMBEDDING_PROVIDER", "") or "").strip().lower() == "mock":
        issues.append("production/staging must not use EMBEDDING_PROVIDER=mock")

    runtime_mode = str(source.get("AGENT_RUNTIME_MODE", "graph") or "graph").strip().lower()
    if runtime_mode != "graph":
        issues.append("production/staging must use AGENT_RUNTIME_MODE=graph")

    return issues


def assert_runtime_security(env: Mapping[str, str] | None = None) -> None:
    issues = validate_runtime_security(env)
    if issues:
        details = "\n".join(f"- {issue}" for issue in issues)
        raise RuntimeError(f"Production security configuration failed:\n{details}")


def get_database_revision_status() -> dict[str, str | bool | None]:
    try:
        from alembic.config import Config
        from alembic.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from backend.db.session import get_engine

        config = Config("alembic.ini")
        script = ScriptDirectory.from_config(config)
        head = script.get_current_head()
        with get_engine().connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        return {"ok": bool(current and current == head), "current": current, "head": head, "error": None}
    except Exception as exc:
        return {"ok": False, "current": None, "head": None, "error": type(exc).__name__}


def assert_database_revision_current(env: Mapping[str, str] | None = None) -> None:
    if get_app_env(env) not in PRODUCTION_ENVS:
        return
    status = get_database_revision_status()
    if not status.get("ok"):
        raise RuntimeError(
            "Database schema revision is not current. "
            f"current={status.get('current')} head={status.get('head')} error={status.get('error')}. "
            "Run: alembic upgrade head"
        )
