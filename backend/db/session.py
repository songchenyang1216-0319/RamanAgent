"""Unified database session helpers.

The project still keeps several legacy JSON stores.  New persistence code should
use this module first, while old services can continue to read their JSON files
as fallback.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from backend.db.database import DB_PATH, ensure_database_dir


def get_database_url() -> str:
    """Return the configured database URL.

    SQLite is the default.  PostgreSQL is intentionally represented as a URL so
    repositories have a stable seam for a future adapter without changing their
    public API.
    """

    return str(os.getenv("DATABASE_URL") or f"sqlite:///{DB_PATH.as_posix()}")


def _sqlite_path_from_url(database_url: str) -> Path:
    parsed = urlparse(database_url)
    if parsed.scheme in {"", "sqlite"}:
        if parsed.scheme == "":
            return Path(database_url)
        raw_path = parsed.path or ""
        if parsed.netloc and parsed.netloc not in {"", "."}:
            raw_path = f"//{parsed.netloc}{raw_path}"
        if re.match(r"^/[A-Za-z]:/", raw_path):
            raw_path = raw_path[1:]
        return Path(raw_path)
    raise NotImplementedError(
        "当前运行时仅内置 SQLite。PostgreSQL 已通过 DATABASE_URL 预留，"
        "后续可在 backend/db/session.py 增加 psycopg/SQLAlchemy adapter。"
    )


def get_connection(database_url: str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with dict-like rows."""

    ensure_database_dir()
    url = database_url or get_database_url()
    path = _sqlite_path_from_url(url)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[sqlite3.Connection]:
    """Context manager that commits on success and rolls back on failure."""

    connection = get_connection(database_url)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
