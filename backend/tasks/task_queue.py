from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Lock
from typing import Callable, Protocol

from backend.repositories.base import loads_json, now_iso
from backend.repositories.task_repository import TaskRepository
from backend.db.session import session_scope


class TaskQueueBackend(Protocol):
    def submit(self, task_id: str, fn: Callable[[], None] | None = None) -> object:
        ...

    def cancel(self, task_id: str) -> bool:
        ...

    def retry(self, task_id: str) -> object:
        ...

    def get_status(self, task_id: str) -> str:
        ...

    def heartbeat(self, task_id: str, *, worker_id: str) -> None:
        ...

    def publish_event(self, task_id: str, event: str, payload: dict | None = None) -> None:
        ...

    def recover_stale_tasks(self) -> int:
        ...


class LocalTaskQueueBackend:
    """Thread-pool queue used for tests and offline development."""

    def __init__(self, max_workers: int = 3, repository: TaskRepository | None = None) -> None:
        self.executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
        self.repository = repository or TaskRepository()
        self._futures: dict[str, Future] = {}
        self._lock = Lock()

    def submit(self, task_id: str, fn: Callable[[], None] | None = None) -> Future:
        if fn is None:
            raise ValueError("LocalTaskQueueBackend.submit 需要可调用任务。")
        future = self.executor.submit(fn)
        with self._lock:
            self._futures[task_id] = future
        self.repository.update(task_id, status="queued", current_step="已入队")
        return future

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            future = self._futures.get(task_id)
        self.repository.update(task_id, cancel_requested=1, updated_at=now_iso())
        return bool(future.cancel()) if future else False

    def retry(self, task_id: str) -> object:
        self.repository.update(task_id, status="pending", cancel_requested=0, retry_at=now_iso())
        return task_id

    def future(self, task_id: str) -> Future | None:
        with self._lock:
            return self._futures.get(task_id)

    def get_status(self, task_id: str) -> str:
        task = self.repository.get(task_id) or {}
        return str(task.get("status") or "unknown")

    def heartbeat(self, task_id: str, *, worker_id: str) -> None:
        lease_until = (datetime.now() + timedelta(seconds=int(os.getenv("TASK_LEASE_SECONDS", "120") or "120"))).isoformat(timespec="seconds")
        self.repository.update(task_id, heartbeat_at=now_iso(), locked_by=worker_id, lease_until=lease_until)

    def publish_event(self, task_id: str, event: str, payload: dict | None = None) -> None:
        self.repository.add_task_event(task_id, event, payload or {})

    def recover_stale_tasks(self) -> int:
        return recover_stale_tasks(self.repository)


class CeleryTaskQueueBackend:
    """Celery-backed queue. Importing Celery is delayed so local tests stay light."""

    def __init__(self, repository: TaskRepository | None = None) -> None:
        self.repository = repository or TaskRepository()
        try:
            from backend.tasks.celery_app import execute_task
        except Exception as exc:  # pragma: no cover - exercised when celery extra is absent
            raise RuntimeError("TASK_QUEUE_BACKEND=celery 需要安装 celery 和 redis 依赖。") from exc
        self._execute_task = execute_task

    def submit(self, task_id: str, fn: Callable[[], None] | None = None) -> object:
        del fn
        self.repository.update(task_id, status="queued", current_step="已提交 Celery 队列")
        return self._execute_task.delay(task_id)

    def cancel(self, task_id: str) -> bool:
        self.repository.update(task_id, cancel_requested=1, updated_at=now_iso())
        return True

    def retry(self, task_id: str) -> object:
        self.repository.update(task_id, status="pending", cancel_requested=0, retry_at=now_iso())
        return self.submit(task_id)

    def get_status(self, task_id: str) -> str:
        task = self.repository.get(task_id) or {}
        return str(task.get("status") or "unknown")

    def heartbeat(self, task_id: str, *, worker_id: str) -> None:
        lease_until = (datetime.now() + timedelta(seconds=int(os.getenv("TASK_LEASE_SECONDS", "120") or "120"))).isoformat(timespec="seconds")
        self.repository.update(task_id, heartbeat_at=now_iso(), locked_by=worker_id, lease_until=lease_until)

    def publish_event(self, task_id: str, event: str, payload: dict | None = None) -> None:
        self.repository.add_task_event(task_id, event, payload or {})

    def recover_stale_tasks(self) -> int:
        return recover_stale_tasks(self.repository)


def recover_stale_tasks(repository: TaskRepository | None = None) -> int:
    repo = repository or TaskRepository()
    recovered = 0
    with session_scope() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM tasks
            WHERE status IN ('running', 'queued', 'retrying')
              AND lease_until IS NOT NULL
              AND lease_until < ?
            """,
            (now_iso(),),
        ).fetchall()
        for row in rows:
            task = dict(row)
            attempt = int(task.get("attempt") or 0)
            max_attempts = max(1, int(task.get("max_attempts") or 1))
            if attempt < max_attempts:
                connection.execute(
                    "UPDATE tasks SET status = ?, retry_at = ?, locked_by = NULL, lease_until = NULL, updated_at = ? WHERE task_id = ?",
                    ("pending", now_iso(), now_iso(), task["task_id"]),
                )
                recovered += 1
            else:
                connection.execute(
                    "UPDATE tasks SET status = ?, failed_reason = ?, updated_at = ? WHERE task_id = ?",
                    ("dead_letter", "worker lease expired", now_iso(), task["task_id"]),
                )
    return recovered


def create_task_queue_backend(repository: TaskRepository | None = None) -> TaskQueueBackend:
    backend = str(os.getenv("TASK_QUEUE_BACKEND", "local") or "local").strip().lower()
    if backend == "celery":
        return CeleryTaskQueueBackend(repository=repository)
    return LocalTaskQueueBackend(max_workers=int(os.getenv("TASK_QUEUE_WORKERS", "2") or "2"), repository=repository)


# Backward-compatible name used by older imports/tests.
LocalTaskQueue = LocalTaskQueueBackend
