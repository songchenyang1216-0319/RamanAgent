from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.init_db import init_database
from backend.db.orm import AuthTokenORM, UserORM
from backend.db.session import sqlalchemy_session_scope
from backend.services.user_service import token_hash


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def migrate_legacy_storage(*, dry_run: bool = False, storage_root: Path | None = None) -> dict[str, int | bool]:
    storage = storage_root or PROJECT_ROOT / "storage"
    users_path = storage / "users.json"
    tokens_path = storage / "auth_tokens.json"
    users = _read_json(users_path, [])
    tokens = _read_json(tokens_path, [])
    stats: dict[str, int | bool] = {
        "dry_run": dry_run,
        "users_seen": len(users) if isinstance(users, list) else 0,
        "users_inserted": 0,
        "users_skipped": 0,
        "tokens_seen": len(tokens) if isinstance(tokens, list) else 0,
        "tokens_inserted": 0,
        "tokens_skipped": 0,
    }

    if dry_run:
        return stats

    init_database()
    with sqlalchemy_session_scope() as session:
        for item in users if isinstance(users, list) else []:
            user_id = str(item.get("user_id") or "").strip() or uuid4().hex
            username = str(item.get("username") or "").strip()
            password_hash = str(item.get("password_hash") or "").strip()
            if not username or not password_hash:
                stats["users_skipped"] = int(stats["users_skipped"]) + 1
                continue
            existing = session.get(UserORM, user_id) or session.execute(select(UserORM).where(UserORM.username == username)).scalar_one_or_none()
            if existing is not None:
                stats["users_skipped"] = int(stats["users_skipped"]) + 1
                continue
            session.add(
                UserORM(
                    user_id=user_id,
                    username=username,
                    password_hash=password_hash,
                    role=str(item.get("role") or "user"),
                    is_active=1 if item.get("is_active", True) else 0,
                    is_frozen=0,
                    created_at=_parse_dt(item.get("created_at")) or datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    last_login_at=_parse_dt(item.get("last_login_at")),
                )
            )
            stats["users_inserted"] = int(stats["users_inserted"]) + 1

        for item in tokens if isinstance(tokens, list) else []:
            user_id = str(item.get("user_id") or "").strip()
            raw_hash = str(item.get("token_hash") or "").strip()
            raw_token = str(item.get("token") or "").strip()
            hashed = raw_hash or (token_hash(raw_token) if raw_token else "")
            expires_at = _parse_dt(item.get("expires_at"))
            if not user_id or not hashed or expires_at is None:
                stats["tokens_skipped"] = int(stats["tokens_skipped"]) + 1
                continue
            existing = session.execute(select(AuthTokenORM).where(AuthTokenORM.token_hash == hashed)).scalar_one_or_none()
            if existing is not None:
                stats["tokens_skipped"] = int(stats["tokens_skipped"]) + 1
                continue
            if session.get(UserORM, user_id) is None:
                stats["tokens_skipped"] = int(stats["tokens_skipped"]) + 1
                continue
            session.add(
                AuthTokenORM(
                    token_id=str(item.get("token_id") or uuid4().hex),
                    user_id=user_id,
                    token_hash=hashed,
                    expires_at=expires_at,
                    revoked_at=_parse_dt(item.get("revoked_at")) if not item.get("is_active", True) else None,
                    last_used_at=_parse_dt(item.get("last_used_at")),
                    user_agent=str(item.get("user_agent") or "") or None,
                    ip_hash=str(item.get("ip_hash") or "") or None,
                    created_at=_parse_dt(item.get("created_at")) or datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            stats["tokens_inserted"] = int(stats["tokens_inserted"]) + 1
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy JSON auth storage into the SQL database.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--storage-root", type=Path, default=PROJECT_ROOT / "storage")
    args = parser.parse_args(argv)
    stats = migrate_legacy_storage(dry_run=args.dry_run, storage_root=args.storage_root)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
