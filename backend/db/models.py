"""SQLite table definitions for the productized RamanAgent persistence layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    name: str
    ddl: str
    columns: dict[str, str]
    indexes: tuple[str, ...] = ()


COMMON_TIMESTAMPS = {
    "created_at": "TEXT",
    "updated_at": "TEXT",
}


TABLE_SPECS: tuple[TableSpec, ...] = (
    TableSpec(
        "users",
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT DEFAULT 'user',
            is_active INTEGER DEFAULT 1,
            is_frozen INTEGER DEFAULT 0,
            last_login_at TEXT,
            deleted_at TEXT,
            version INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "username": "TEXT",
            "password_hash": "TEXT",
            "role": "TEXT DEFAULT 'user'",
            "is_active": "INTEGER DEFAULT 1",
            "is_frozen": "INTEGER DEFAULT 0",
            "last_login_at": "TEXT",
            "deleted_at": "TEXT",
            "version": "INTEGER DEFAULT 0",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",),
    ),
    TableSpec(
        "auth_tokens",
        """
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            refresh_token_id TEXT,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            last_used_at TEXT,
            user_agent TEXT,
            ip_hash TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """,
        {
            "user_id": "TEXT",
            "token_hash": "TEXT",
            "refresh_token_id": "TEXT",
            "expires_at": "TEXT",
            "revoked_at": "TEXT",
            "last_used_at": "TEXT",
            "user_agent": "TEXT",
            "ip_hash": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_tokens_hash ON auth_tokens(token_hash)",
            "CREATE INDEX IF NOT EXISTS idx_auth_tokens_user ON auth_tokens(user_id)",
        ),
    ),
    TableSpec(
        "refresh_tokens",
        """
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            refresh_token_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            token_family_id TEXT NOT NULL,
            parent_token_id TEXT,
            expires_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT,
            rotated_at TEXT,
            replaced_by_token_id TEXT,
            user_agent TEXT,
            ip_hash TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """,
        {
            "user_id": "TEXT",
            "token_hash": "TEXT",
            "token_family_id": "TEXT",
            "parent_token_id": "TEXT",
            "expires_at": "TEXT",
            "last_used_at": "TEXT",
            "revoked_at": "TEXT",
            "rotated_at": "TEXT",
            "replaced_by_token_id": "TEXT",
            "user_agent": "TEXT",
            "ip_hash": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash)",
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_family ON refresh_tokens(token_family_id)",
        ),
    ),
    TableSpec(
        "projects",
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            archived INTEGER DEFAULT 0,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "user_id": "TEXT",
            "name": "TEXT",
            "description": "TEXT",
            "archived": "INTEGER DEFAULT 0",
            "metadata_json": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_projects_user_updated ON projects(user_id, updated_at)",),
    ),
    TableSpec(
        "files",
        """
        CREATE TABLE IF NOT EXISTS files (
            file_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            project_id TEXT,
            conversation_id TEXT,
            workspace_id TEXT,
            filename TEXT,
            original_filename TEXT,
            file_type TEXT,
            mime_type TEXT,
            size INTEGER DEFAULT 0,
            path TEXT,
            kind TEXT DEFAULT 'upload',
            content_hash TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "user_id": "TEXT",
            "project_id": "TEXT",
            "conversation_id": "TEXT",
            "workspace_id": "TEXT",
            "filename": "TEXT",
            "original_filename": "TEXT",
            "file_type": "TEXT",
            "mime_type": "TEXT",
            "size": "INTEGER DEFAULT 0",
            "path": "TEXT",
            "kind": "TEXT DEFAULT 'upload'",
            "content_hash": "TEXT",
            "metadata_json": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        (
            "CREATE INDEX IF NOT EXISTS idx_files_user_project ON files(user_id, project_id)",
            "CREATE INDEX IF NOT EXISTS idx_files_user_workspace ON files(user_id, workspace_id)",
        ),
    ),
    TableSpec(
        "conversations",
        """
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT,
            summary TEXT,
            metadata_json TEXT,
            is_deleted INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "user_id": "TEXT",
            "title": "TEXT",
            "summary": "TEXT",
            "metadata_json": "TEXT",
            "is_deleted": "INTEGER DEFAULT 0",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, updated_at)",),
    ),
    TableSpec(
        "messages",
        """
        CREATE TABLE IF NOT EXISTS messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            user_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "conversation_id": "TEXT",
            "user_id": "TEXT",
            "role": "TEXT",
            "content": "TEXT",
            "metadata_json": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_messages_conversation_created ON messages(conversation_id, created_at)",),
    ),
    TableSpec(
        "tasks",
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            user_id TEXT,
            project_id TEXT,
            conversation_id TEXT,
            task_type TEXT NOT NULL,
            status TEXT NOT NULL,
            progress INTEGER DEFAULT 0,
            current_step TEXT,
            attempt INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 1,
            idempotency_key TEXT,
            cancel_requested INTEGER DEFAULT 0,
            heartbeat_at TEXT,
            locked_by TEXT,
            lease_until TEXT,
            retry_at TEXT,
            error_code TEXT,
            failed_reason TEXT,
            parent_task_id TEXT,
            trace_id TEXT,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            result_json TEXT,
            artifacts_json TEXT,
            payload_json TEXT,
            version INTEGER DEFAULT 0,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "user_id": "TEXT",
            "project_id": "TEXT",
            "conversation_id": "TEXT",
            "task_type": "TEXT",
            "status": "TEXT",
            "progress": "INTEGER DEFAULT 0",
            "current_step": "TEXT",
            "attempt": "INTEGER DEFAULT 0",
            "max_attempts": "INTEGER DEFAULT 1",
            "idempotency_key": "TEXT",
            "cancel_requested": "INTEGER DEFAULT 0",
            "heartbeat_at": "TEXT",
            "locked_by": "TEXT",
            "lease_until": "TEXT",
            "retry_at": "TEXT",
            "error_code": "TEXT",
            "failed_reason": "TEXT",
            "parent_task_id": "TEXT",
            "trace_id": "TEXT",
            "started_at": "TEXT",
            "finished_at": "TEXT",
            "error_message": "TEXT",
            "result_json": "TEXT",
            "artifacts_json": "TEXT",
            "payload_json": "TEXT",
            "version": "INTEGER DEFAULT 0",
            "deleted_at": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        (
            "CREATE INDEX IF NOT EXISTS idx_tasks_user_created ON tasks(user_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_tasks_retry ON tasks(status, retry_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency ON tasks(user_id, idempotency_key) WHERE idempotency_key IS NOT NULL",
        ),
    ),
    TableSpec(
        "task_steps",
        """
        CREATE TABLE IF NOT EXISTS task_steps (
            step_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            step_index INTEGER DEFAULT 0,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            detail_json TEXT,
            started_at TEXT,
            finished_at TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "task_id": "TEXT",
            "step_index": "INTEGER DEFAULT 0",
            "name": "TEXT",
            "status": "TEXT",
            "detail_json": "TEXT",
            "started_at": "TEXT",
            "finished_at": "TEXT",
            "error_message": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_task_steps_task ON task_steps(task_id, step_index)",),
    ),
    TableSpec(
        "task_events",
        """
        CREATE TABLE IF NOT EXISTS task_events (
            event_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            conversation_id TEXT,
            message_id TEXT,
            trace_id TEXT,
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            public_payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(task_id, sequence),
            FOREIGN KEY(task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        )
        """,
        {
            "task_id": "TEXT",
            "conversation_id": "TEXT",
            "message_id": "TEXT",
            "trace_id": "TEXT",
            "sequence": "INTEGER",
            "event_type": "TEXT",
            "public_payload_json": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_task_events_task_sequence ON task_events(task_id, sequence)",),
    ),
    TableSpec(
        "reports",
        """
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY,
            user_id TEXT,
            project_id TEXT,
            task_id TEXT,
            file_id TEXT,
            title TEXT,
            report_type TEXT,
            status TEXT,
            markdown_path TEXT,
            html_path TEXT,
            pdf_path TEXT,
            docx_path TEXT,
            json_path TEXT,
            error_message TEXT,
            metadata_json TEXT,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "user_id": "TEXT",
            "project_id": "TEXT",
            "task_id": "TEXT",
            "file_id": "TEXT",
            "title": "TEXT",
            "report_type": "TEXT",
            "status": "TEXT",
            "markdown_path": "TEXT",
            "html_path": "TEXT",
            "pdf_path": "TEXT",
            "docx_path": "TEXT",
            "json_path": "TEXT",
            "error_message": "TEXT",
            "metadata_json": "TEXT",
            "deleted_at": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_reports_user_project ON reports(user_id, project_id, created_at)",),
    ),
    TableSpec(
        "pipeline_runs",
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            pipeline_run_id TEXT PRIMARY KEY,
            user_id TEXT,
            project_id TEXT,
            conversation_id TEXT,
            file_id TEXT,
            pipeline_name TEXT,
            pipeline_request_json TEXT,
            pipeline_result_json TEXT,
            status TEXT,
            elapsed_ms INTEGER DEFAULT 0,
            artifacts_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "user_id": "TEXT",
            "project_id": "TEXT",
            "conversation_id": "TEXT",
            "file_id": "TEXT",
            "pipeline_name": "TEXT",
            "pipeline_request_json": "TEXT",
            "pipeline_result_json": "TEXT",
            "status": "TEXT",
            "elapsed_ms": "INTEGER DEFAULT 0",
            "artifacts_json": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_pipeline_runs_user_created ON pipeline_runs(user_id, created_at)",),
    ),
    TableSpec(
        "rag_queries",
        """
        CREATE TABLE IF NOT EXISTS rag_queries (
            rag_query_id TEXT PRIMARY KEY,
            query_id TEXT UNIQUE,
            user_id TEXT,
            conversation_id TEXT,
            query TEXT NOT NULL,
            rag_scope TEXT,
            file_ids_json TEXT,
            knowledge_base_ids_json TEXT,
            retrieved_chunks_json TEXT,
            retrieved_chunk_ids_json TEXT,
            citations_json TEXT,
            answer TEXT,
            latency_ms INTEGER DEFAULT 0,
            model_info_json TEXT,
            retrieval_mode TEXT,
            source_breakdown_json TEXT,
            top_k INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "rag_query_id": "TEXT",
            "query_id": "TEXT",
            "user_id": "TEXT",
            "conversation_id": "TEXT",
            "query": "TEXT",
            "rag_scope": "TEXT",
            "file_ids_json": "TEXT",
            "knowledge_base_ids_json": "TEXT",
            "retrieved_chunks_json": "TEXT",
            "retrieved_chunk_ids_json": "TEXT",
            "citations_json": "TEXT",
            "answer": "TEXT",
            "latency_ms": "INTEGER DEFAULT 0",
            "model_info_json": "TEXT",
            "retrieval_mode": "TEXT",
            "source_breakdown_json": "TEXT",
            "top_k": "INTEGER",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_rag_queries_user_conversation_created ON rag_queries(user_id, conversation_id, created_at)",),
    ),
    TableSpec(
        "skill_runs",
        """
        CREATE TABLE IF NOT EXISTS skill_runs (
            skill_run_id TEXT PRIMARY KEY,
            user_id TEXT,
            task_id TEXT,
            conversation_id TEXT,
            skill_name TEXT NOT NULL,
            action_name TEXT,
            status TEXT,
            input_json TEXT,
            output_json TEXT,
            error_message TEXT,
            elapsed_ms INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "user_id": "TEXT",
            "task_id": "TEXT",
            "conversation_id": "TEXT",
            "skill_name": "TEXT",
            "action_name": "TEXT",
            "status": "TEXT",
            "input_json": "TEXT",
            "output_json": "TEXT",
            "error_message": "TEXT",
            "elapsed_ms": "INTEGER DEFAULT 0",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_skill_runs_user_created ON skill_runs(user_id, created_at)",),
    ),
    TableSpec(
        "model_runs",
        """
        CREATE TABLE IF NOT EXISTS model_runs (
            model_run_id TEXT PRIMARY KEY,
            user_id TEXT,
            conversation_id TEXT,
            provider TEXT,
            model TEXT,
            status TEXT,
            latency_ms INTEGER DEFAULT 0,
            input_json TEXT,
            output_json TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "user_id": "TEXT",
            "conversation_id": "TEXT",
            "provider": "TEXT",
            "model": "TEXT",
            "status": "TEXT",
            "latency_ms": "INTEGER DEFAULT 0",
            "input_json": "TEXT",
            "output_json": "TEXT",
            "error_message": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_model_runs_user_created ON model_runs(user_id, created_at)",),
    ),
    TableSpec(
        "knowledge_bases",
        """
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            knowledge_base_id TEXT PRIMARY KEY,
            owner_user_id TEXT NOT NULL,
            user_id TEXT,
            name TEXT NOT NULL,
            description TEXT,
            visibility TEXT DEFAULT 'private',
            enabled INTEGER DEFAULT 1,
            metadata_json TEXT,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "owner_user_id": "TEXT",
            "user_id": "TEXT",
            "name": "TEXT",
            "description": "TEXT",
            "visibility": "TEXT DEFAULT 'private'",
            "enabled": "INTEGER DEFAULT 1",
            "metadata_json": "TEXT",
            "deleted_at": "TEXT",
            **COMMON_TIMESTAMPS,
        },
    ),
    TableSpec(
        "knowledge_base_files",
        """
        CREATE TABLE IF NOT EXISTS knowledge_base_files (
            kb_file_id TEXT PRIMARY KEY,
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
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "knowledge_base_id": "TEXT",
            "owner_user_id": "TEXT",
            "original_filename": "TEXT",
            "stored_path": "TEXT",
            "file_type": "TEXT",
            "mime_type": "TEXT",
            "size": "INTEGER",
            "processing_status": "TEXT DEFAULT 'pending'",
            "rag_index_status": "TEXT DEFAULT 'pending'",
            "rag_index_error": "TEXT",
            "chunk_count": "INTEGER DEFAULT 0",
            "deleted_at": "TEXT",
            **COMMON_TIMESTAMPS,
        },
    ),
    TableSpec(
        "audit_logs",
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            audit_id TEXT PRIMARY KEY,
            user_id TEXT,
            action TEXT NOT NULL,
            resource_type TEXT,
            resource_id TEXT,
            ip_address TEXT,
            user_agent TEXT,
            detail_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        {
            "user_id": "TEXT",
            "action": "TEXT",
            "resource_type": "TEXT",
            "resource_id": "TEXT",
            "ip_address": "TEXT",
            "user_agent": "TEXT",
            "detail_json": "TEXT",
            **COMMON_TIMESTAMPS,
        },
        ("CREATE INDEX IF NOT EXISTS idx_audit_logs_user_created ON audit_logs(user_id, created_at)",),
    ),
)
