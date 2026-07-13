from __future__ import annotations

import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException

from backend.db.orm import UserORM
from backend.db.session import get_engine, get_session_factory, sqlalchemy_session_scope
from backend.security.ownership_guard import OwnershipGuard
from backend.security.resource_scope import ResourceScope
from backend.services.user_service import UserService
from backend.tasks.task_manager import TaskManager
from backend.tasks.task_schema import TaskCreateRequest


def _set_temp_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "agent.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_path.as_posix())
    monkeypatch.setenv("AUTH_SECRET", "phase2_test_secret_value_32_chars")
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    return db_path


def _alembic_config() -> Config:
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def test_alembic_upgrade_downgrade_upgrade_sqlite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_temp_database(monkeypatch, tmp_path)
    config = _alembic_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_sqlalchemy_transaction_rollback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_temp_database(monkeypatch, tmp_path)
    command.upgrade(_alembic_config(), "head")
    with pytest.raises(RuntimeError):
        with sqlalchemy_session_scope() as session:
            session.add(
                UserORM(
                    user_id="rollback-user",
                    username="rollback",
                    password_hash="hash",
                    role="user",
                )
            )
            raise RuntimeError("force rollback")
    with sqlalchemy_session_scope() as session:
        assert session.get(UserORM, "rollback-user") is None


def test_refresh_token_rotation_and_replay_revokes_family(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_temp_database(monkeypatch, tmp_path)
    command.upgrade(_alembic_config(), "head")
    service = UserService()
    user = service.create_user("rotation_user", "StrongPass123!")
    pair = service.create_token_pair(user["user_id"], user_agent="pytest", ip_hash="ip")
    rotated = service.rotate_refresh_token(pair["refresh_token"], user_agent="pytest-2", ip_hash="ip")
    assert rotated and rotated["success"] is True

    replay = service.rotate_refresh_token(pair["refresh_token"], user_agent="pytest-3", ip_hash="ip")
    assert replay and replay["error_code"] == "AUTH_REFRESH_REPLAY"
    sessions = service.list_sessions(user["user_id"])
    assert sessions
    assert all(not item["active"] for item in sessions)


def test_task_events_are_persistent_ordered_and_resumeable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _set_temp_database(monkeypatch, tmp_path)
    from backend.db.init_db import init_database

    init_database()
    manager = TaskManager()
    task = manager.create_task(TaskCreateRequest(task_type="echo", payload={"message": "ok"}, user_id="task-user", idempotency_key="same"))
    duplicate = manager.create_task(TaskCreateRequest(task_type="echo", payload={"message": "ok"}, user_id="task-user", idempotency_key="same"))
    assert duplicate["task_id"] == task["task_id"]
    time.sleep(0.8)
    events = manager.task_events(task["task_id"])
    sequences = [int(item["sequence"]) for item in events]
    assert sequences == sorted(sequences)
    assert len(sequences) == len(set(sequences))
    assert len([item for item in events if item["event_type"] == "final"]) == 1
    assert len([item for item in events if item["event_type"] == "done"]) == 1
    resumed = manager.task_events_after(task["task_id"], after_sequence=sequences[-2])
    assert [item["sequence"] for item in resumed] == [sequences[-1]]


def test_ownership_guard_blocks_non_owner_and_allows_admin_audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from backend.db.init_db import init_database

    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + (tmp_path / "guard.db").as_posix())
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    init_database()
    guard = OwnershipGuard()
    with pytest.raises(HTTPException):
        guard._require_owner(
            scope=ResourceScope(user_id="user-a", is_admin=False, authenticated=True),
            resource_type="task",
            resource_id="task-b",
            owner_user_id="user-b",
            payload={"task_id": "task-b"},
        )

    allowed = guard._require_owner(
        scope=ResourceScope(user_id="admin", is_admin=True, authenticated=True, reason="unit-test"),
        resource_type="task",
        resource_id="task-b",
        owner_user_id="user-b",
        payload={"task_id": "task-b"},
    )
    assert allowed["task_id"] == "task-b"
