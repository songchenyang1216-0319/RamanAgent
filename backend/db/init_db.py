"""Database bootstrap for productized persistence."""

from __future__ import annotations

import sqlite3

from backend.db.models import TABLE_SPECS
from backend.db.session import session_scope


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_columns(connection: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = _table_columns(connection, table_name)
    for column_name, definition in columns.items():
        if column_name not in existing:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def init_database() -> None:
    """Create or migrate the unified SQLite schema.

    This is intentionally idempotent and additive so it can run beside
    init_history_db/init_agent_memory_db without breaking old data.
    """

    with session_scope() as connection:
        for spec in TABLE_SPECS:
            connection.execute(spec.ddl)
            _ensure_columns(connection, spec.name, spec.columns)
            for index_sql in spec.indexes:
                connection.execute(index_sql)

