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
                "user_id": "TEXT NOT NULL DEFAULT 'default_user'",
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
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_sessions_user_updated ON agent_sessions(user_id, updated_at, id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS file_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL DEFAULT 'default_user',
                conversation_id TEXT NOT NULL,
                file_id TEXT,
                filename TEXT,
                source_path TEXT,
                page TEXT,
                section TEXT,
                text TEXT NOT NULL,
                token_estimate INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        _ensure_columns(
            connection,
            "file_chunks",
            {
                "source_type": "TEXT",
                "sheet": "TEXT",
                "chunk_index": "INTEGER DEFAULT 0",
                "text_hash": "TEXT",
                "updated_at": "TEXT",
                "rag_indexed": "INTEGER DEFAULT 0",
            },
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_file_chunks_conversation_file ON file_chunks(user_id, conversation_id, file_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_file_chunks_user_conversation_file ON file_chunks(user_id, conversation_id, file_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_file_chunks_text ON file_chunks(text)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_indexes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                vector_provider TEXT,
                embedding_provider TEXT,
                embedding_model TEXT,
                chunk_count INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_columns(
            connection,
            "rag_indexes",
            {
                "rag_scope": "TEXT DEFAULT 'conversation'",
                "knowledge_base_id": "TEXT",
                "kb_file_id": "TEXT",
            },
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_indexes_user_conversation_file ON rag_indexes(user_id, conversation_id, file_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_indexes_scope_user_conversation ON rag_indexes(rag_scope, user_id, conversation_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_indexes_scope_kb ON rag_indexes(rag_scope, knowledge_base_id, kb_file_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_id TEXT UNIQUE NOT NULL,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                query TEXT NOT NULL,
                file_ids_json TEXT,
                top_k INTEGER,
                retrieval_mode TEXT,
                retrieved_chunk_ids_json TEXT,
                answer_message_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        _ensure_columns(
            connection,
            "rag_queries",
            {
                "rag_scope": "TEXT",
                "knowledge_base_ids_json": "TEXT",
                "source_breakdown_json": "TEXT",
            },
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_queries_user_conversation_created ON rag_queries(user_id, conversation_id, created_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_bases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_base_id TEXT UNIQUE NOT NULL,
                owner_user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                visibility TEXT DEFAULT 'private',
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_kb_owner_enabled ON knowledge_bases(owner_user_id, enabled, deleted_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_base_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kb_file_id TEXT UNIQUE NOT NULL,
                knowledge_base_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                file_type TEXT,
                mime_type TEXT,
                size INTEGER,
                processing_status TEXT DEFAULT 'pending',
                rag_index_status TEXT DEFAULT 'pending',
                rag_index_error TEXT,
                chunk_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_kb_files_kb_owner ON knowledge_base_files(knowledge_base_id, owner_user_id, deleted_at)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_base_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT UNIQUE NOT NULL,
                knowledge_base_id TEXT NOT NULL,
                kb_file_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                source_name TEXT,
                source_type TEXT,
                text TEXT NOT NULL,
                page INTEGER,
                sheet TEXT,
                section TEXT,
                chunk_index INTEGER DEFAULT 0,
                text_hash TEXT,
                rag_indexed INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_kb_chunks_kb_file ON knowledge_base_chunks(knowledge_base_id, kb_file_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_base_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                knowledge_base_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_kb_permissions_user ON knowledge_base_permissions(user_id, knowledge_base_id)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_knowledge_bases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                knowledge_base_id TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversation_kb_user_conversation ON conversation_knowledge_bases(user_id, conversation_id, enabled)"
        )
        connection.commit()
    finally:
        connection.close()
