from __future__ import annotations

import os
import signal
import time
from typing import Any

from backend.db.init_db import init_database
from backend.db.session import session_scope
from backend.repositories.base import loads_json
from backend.security.startup_checks import assert_runtime_security
from backend.tasks.task_manager import TaskManager
from backend.tasks.task_schema import TaskCreateRequest
from backend.tasks.task_queue import recover_stale_tasks


_STOP = False


def _handle_stop(signum: int, frame: object) -> None:
    del signum, frame
    global _STOP
    _STOP = True


def _load_pending_tasks(limit: int = 5) -> list[dict[str, Any]]:
    with session_scope() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
    return [dict(row) for row in rows]


def run_once(manager: TaskManager | None = None) -> int:
    task_manager = manager or TaskManager()
    processed = 0
    for task in _load_pending_tasks():
        request = TaskCreateRequest(
            task_type=str(task.get("task_type") or ""),
            payload=loads_json(task.get("payload_json"), {}),
            user_id=task.get("user_id"),
            project_id=task.get("project_id"),
            conversation_id=task.get("conversation_id"),
        )
        task_manager._run_task(str(task["task_id"]), request)
        processed += 1
    return processed


def main() -> int:
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)
    assert_runtime_security()
    init_database()
    recovered = recover_stale_tasks()
    interval = max(1.0, float(os.getenv("TASK_WORKER_POLL_SECONDS", "2") or "2"))
    print(f"RamanAgent worker started; recovered={recovered}; polling pending tasks every {interval:g}s.")
    while not _STOP:
        processed = run_once()
        if processed == 0:
            time.sleep(interval)
    print("RamanAgent worker stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
