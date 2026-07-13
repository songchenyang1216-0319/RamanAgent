from __future__ import annotations

from typing import Any

from backend.db.session import session_scope

from .base import SQLiteRepository, dumps_json, loads_json, now_iso


class TaskRepository(SQLiteRepository):
    table_name = "tasks"
    id_field = "task_id"

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = dict(payload or {})
        if not isinstance(item.get("result_json"), str):
            item["result_json"] = dumps_json(item.get("result_json") or {})
        if not isinstance(item.get("artifacts_json"), str):
            item["artifacts_json"] = dumps_json(item.get("artifacts_json") or [])
        if not isinstance(item.get("payload_json"), str):
            item["payload_json"] = dumps_json(item.get("payload_json") or {})
        return self.create(item)

    def get_by_idempotency_key(self, user_id: str, idempotency_key: str) -> dict[str, Any] | None:
        cleaned = str(idempotency_key or "").strip()
        if not cleaned:
            return None
        with session_scope() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM tasks
                WHERE user_id = ? AND idempotency_key = ? AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id, cleaned),
            ).fetchone()
        return dict(row) if row else None

    def add_event_step(self, task_id: str, event_name: str, detail: dict[str, Any] | None = None, *, status: str = "done") -> dict[str, Any]:
        from uuid import uuid4

        now = now_iso()
        with session_scope() as connection:
            count = connection.execute("SELECT COUNT(*) AS count FROM task_steps WHERE task_id = ?", (task_id,)).fetchone()
            step_index = int(count["count"] or 0) + 1 if count else 1
            payload = {
                "step_id": uuid4().hex,
                "task_id": task_id,
                "step_index": step_index,
                "name": event_name,
                "status": status,
                "detail_json": dumps_json(detail or {}),
                "started_at": now,
                "finished_at": now,
                "created_at": now,
                "updated_at": now,
            }
            columns = list(payload.keys())
            connection.execute(
                f"INSERT INTO task_steps ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [payload[column] for column in columns],
            )
        return payload

    def add_task_event(
        self,
        task_id: str,
        event_type: str,
        public_payload: dict[str, Any] | None = None,
        *,
        conversation_id: str | None = None,
        message_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        from uuid import uuid4

        now = now_iso()
        payload = dict(public_payload or {})
        with session_scope() as connection:
            if event_type in {"final", "done"}:
                existing = connection.execute(
                    "SELECT * FROM task_events WHERE task_id = ? AND event_type = ? ORDER BY sequence ASC LIMIT 1",
                    (task_id, event_type),
                ).fetchone()
                if existing is not None:
                    return dict(existing)
            row = connection.execute("SELECT COALESCE(MAX(sequence), 0) AS max_sequence FROM task_events WHERE task_id = ?", (task_id,)).fetchone()
            sequence = int(row["max_sequence"] or 0) + 1 if row else 1
            item = {
                "event_id": uuid4().hex,
                "task_id": task_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "trace_id": trace_id,
                "sequence": sequence,
                "event_type": event_type,
                "public_payload_json": dumps_json(payload),
                "created_at": now,
                "updated_at": now,
            }
            columns = list(item.keys())
            connection.execute(
                f"INSERT INTO task_events ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [item[column] for column in columns],
            )
        item["public_payload"] = payload
        item["event"] = event_type
        item.update(payload)
        return item

    def list_task_events(self, task_id: str, *, after_sequence: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with session_scope() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM task_events
                WHERE task_id = ? AND sequence > ?
                ORDER BY sequence ASC
                LIMIT ?
                """,
                (task_id, max(0, int(after_sequence or 0)), max(1, min(int(limit or 500), 1000))),
            ).fetchall()
        return [self._public_event(dict(row)) for row in rows]

    def get_event_sequence(self, task_id: str, event_id: str) -> int:
        if not event_id:
            return 0
        with session_scope() as connection:
            row = connection.execute(
                "SELECT sequence FROM task_events WHERE task_id = ? AND event_id = ?",
                (task_id, event_id),
            ).fetchone()
        return int(row["sequence"] or 0) if row else 0

    def get_task_with_steps(self, task_id: str) -> dict[str, Any] | None:
        task = self.get(task_id)
        if task is None:
            return None
        with session_scope() as connection:
            rows = connection.execute(
                "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_index ASC",
                (task_id,),
            ).fetchall()
        task["steps"] = [dict(row) for row in rows]
        task["result"] = loads_json(task.get("result_json"), {})
        task["artifacts"] = loads_json(task.get("artifacts_json"), [])
        task["payload"] = loads_json(task.get("payload_json"), {})
        return task

    def _public_event(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = loads_json(event.get("public_payload_json"), {})
        public = dict(event)
        public["public_payload"] = payload
        public["event"] = public.get("event_type")
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key in {"event_id", "sequence", "event_type", "created_at", "updated_at"}:
                    continue
                public[key] = value
        return public
