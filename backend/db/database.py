"""历史记录数据库初始化与连接。"""

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
