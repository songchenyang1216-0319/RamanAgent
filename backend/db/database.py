"""SQLite 数据库支持。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from raman_core.methanol.config import RESULT_DIR, ensure_dirs


DB_PATH = RESULT_DIR / "ramanagent.db"


def ensure_database_dir() -> None:
    """确保数据库目录存在。"""
    ensure_dirs()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)


def get_db_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """获取 SQLite 连接，并设置行工厂。"""
    ensure_database_dir()
    path = db_path or DB_PATH
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_columns(connection: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing_columns = _table_columns(connection, table_name)
    for name, definition in columns.items():
        if name not in existing_columns:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


def init_agent_memory_db(db_path: Path | None = None) -> None:
    """初始化会话记忆相关表。"""
    connection = get_db_connection(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_analysis_json TEXT,
                last_file TEXT,
                last_report TEXT,
                task_state_json TEXT,
                summary TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        _ensure_columns(
            connection,
            "agent_sessions",
            {
                "title": "TEXT",
                "last_analysis_json": "TEXT",
                "last_file": "TEXT",
                "last_report": "TEXT",
                "task_state_json": "TEXT",
                "summary": "TEXT",
                "is_deleted": "INTEGER NOT NULL DEFAULT 0",
            },
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        _ensure_columns(
            connection,
            "agent_messages",
            {
                "metadata_json": "TEXT",
            },
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_messages_session_created ON agent_messages(session_id, created_at, id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_sessions_updated ON agent_sessions(updated_at, id)"
        )
        connection.commit()
    finally:
        connection.close()
