from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from backend.db.orm import AuthTokenORM, RefreshTokenORM, UserORM
from backend.db.session import sqlalchemy_session_scope


def _to_dict(obj: Any) -> dict[str, Any] | None:
    if obj is None:
        return None
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


class AuthRepository:
    def list_users(self) -> list[dict[str, Any]]:
        with sqlalchemy_session_scope() as session:
            rows = session.execute(select(UserORM).order_by(UserORM.created_at.desc())).scalars().all()
            return [_to_dict(row) or {} for row in rows]

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with sqlalchemy_session_scope() as session:
            return _to_dict(session.get(UserORM, user_id))

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        normalized = str(username or "").strip().lower()
        with sqlalchemy_session_scope() as session:
            row = session.execute(select(UserORM).where(UserORM.username == normalized)).scalar_one_or_none()
            if row is None:
                row = session.execute(select(UserORM).where(UserORM.username == str(username or "").strip())).scalar_one_or_none()
            return _to_dict(row)

    def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        with sqlalchemy_session_scope() as session:
            user = UserORM(**payload)
            session.add(user)
            session.flush()
            return _to_dict(user) or {}

    def update_user(self, user_id: str, **changes: Any) -> dict[str, Any] | None:
        changes["updated_at"] = datetime.utcnow()
        with sqlalchemy_session_scope() as session:
            session.execute(update(UserORM).where(UserORM.user_id == user_id).values(**changes))
            row = session.get(UserORM, user_id)
            return _to_dict(row)

    def create_access_token(self, payload: dict[str, Any]) -> dict[str, Any]:
        with sqlalchemy_session_scope() as session:
            token = AuthTokenORM(**payload)
            session.add(token)
            session.flush()
            return _to_dict(token) or {}

    def get_access_token_by_hash(self, hashed: str) -> dict[str, Any] | None:
        with sqlalchemy_session_scope() as session:
            row = session.execute(select(AuthTokenORM).where(AuthTokenORM.token_hash == hashed)).scalar_one_or_none()
            return _to_dict(row)

    def update_access_token(self, token_id: str, **changes: Any) -> dict[str, Any] | None:
        changes["updated_at"] = datetime.utcnow()
        with sqlalchemy_session_scope() as session:
            session.execute(update(AuthTokenORM).where(AuthTokenORM.token_id == token_id).values(**changes))
            return _to_dict(session.get(AuthTokenORM, token_id))

    def revoke_user_access_tokens(self, user_id: str, *, refresh_token_id: str | None = None) -> int:
        values = {"revoked_at": datetime.utcnow(), "updated_at": datetime.utcnow()}
        with sqlalchemy_session_scope() as session:
            query = update(AuthTokenORM).where(AuthTokenORM.user_id == user_id, AuthTokenORM.revoked_at.is_(None))
            if refresh_token_id:
                query = query.where(AuthTokenORM.refresh_token_id == refresh_token_id)
            result = session.execute(query.values(**values))
            return int(result.rowcount or 0)

    def create_refresh_token(self, payload: dict[str, Any]) -> dict[str, Any]:
        with sqlalchemy_session_scope() as session:
            token = RefreshTokenORM(**payload)
            session.add(token)
            session.flush()
            return _to_dict(token) or {}

    def get_refresh_token_by_hash(self, hashed: str) -> dict[str, Any] | None:
        with sqlalchemy_session_scope() as session:
            row = session.execute(select(RefreshTokenORM).where(RefreshTokenORM.token_hash == hashed)).scalar_one_or_none()
            return _to_dict(row)

    def get_refresh_token(self, refresh_token_id: str) -> dict[str, Any] | None:
        with sqlalchemy_session_scope() as session:
            return _to_dict(session.get(RefreshTokenORM, refresh_token_id))

    def update_refresh_token(self, refresh_token_id: str, **changes: Any) -> dict[str, Any] | None:
        changes["updated_at"] = datetime.utcnow()
        with sqlalchemy_session_scope() as session:
            session.execute(update(RefreshTokenORM).where(RefreshTokenORM.refresh_token_id == refresh_token_id).values(**changes))
            return _to_dict(session.get(RefreshTokenORM, refresh_token_id))

    def list_refresh_tokens_for_user(self, user_id: str) -> list[dict[str, Any]]:
        with sqlalchemy_session_scope() as session:
            rows = session.execute(
                select(RefreshTokenORM).where(RefreshTokenORM.user_id == user_id).order_by(RefreshTokenORM.created_at.desc())
            ).scalars().all()
            return [_to_dict(row) or {} for row in rows]

    def revoke_refresh_token(self, refresh_token_id: str) -> None:
        self.update_refresh_token(refresh_token_id, revoked_at=datetime.utcnow())

    def revoke_refresh_family(self, token_family_id: str) -> int:
        values = {"revoked_at": datetime.utcnow(), "updated_at": datetime.utcnow()}
        with sqlalchemy_session_scope() as session:
            result = session.execute(
                update(RefreshTokenORM)
                .where(RefreshTokenORM.token_family_id == token_family_id, RefreshTokenORM.revoked_at.is_(None))
                .values(**values)
            )
            return int(result.rowcount or 0)
