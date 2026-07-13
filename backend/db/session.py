"""Unified database session helpers.

The project still keeps several legacy JSON stores.  New persistence code should
use this module first, while old services can continue to read their JSON files
as fallback.
"""

from __future__ import annotations

import os
import re
import sqlite3
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from backend.db.database import DB_PATH, ensure_database_dir


def get_database_url() -> str:
    """Return the configured database URL.

    SQLite is the default.  PostgreSQL is intentionally represented as a URL so
    repositories have a stable seam for a future adapter without changing their
    public API.
    """

    return str(os.getenv("DATABASE_URL") or f"sqlite:///{DB_PATH.as_posix()}")


def normalize_sqlalchemy_url(database_url: str | None = None) -> str:
    url = str(database_url or get_database_url())
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("sqlite:///"):
        return url
    if url.startswith("sqlite://"):
        return url
    if "://" not in url:
        return f"sqlite:///{Path(url).as_posix()}"
    return url


def is_sqlite_url(database_url: str | None = None) -> bool:
    return normalize_sqlalchemy_url(database_url).startswith("sqlite")


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


@lru_cache(maxsize=8)
def get_engine(database_url: str | None = None) -> Engine:
    url = normalize_sqlalchemy_url(database_url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    kwargs: dict[str, object] = {
        "echo": str(os.getenv("DATABASE_ECHO", "false")).strip().lower() == "true",
        "future": True,
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }
    if not url.startswith("sqlite"):
        kwargs.update(
            {
                "pool_size": int(os.getenv("DB_POOL_SIZE", "10") or "10"),
                "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20") or "20"),
                "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800") or "1800"),
            }
        )
    return create_engine(url, **kwargs)


@lru_cache(maxsize=8)
def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def sqlalchemy_session_scope(database_url: str | None = None) -> Iterator[Session]:
    session = get_session_factory(database_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session() -> Iterator[Session]:
    with sqlalchemy_session_scope() as session:
        yield session


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
