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

