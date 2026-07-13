from __future__ import annotations

import os

from celery import Celery

from backend.repositories.base import loads_json
from backend.repositories.task_repository import TaskRepository
from backend.tasks.task_manager import TaskManager
from backend.tasks.task_queue import LocalTaskQueueBackend
from backend.tasks.task_schema import TaskCreateRequest


celery_app = Celery(
    "ramanagent",
    broker=os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL") or "redis://redis:6379/0",
    backend=os.getenv("CELERY_RESULT_BACKEND") or "redis://redis:6379/1",
)
celery_app.conf.update(
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)


@celery_app.task(name="ramanagent.execute_task", bind=True)
def execute_task(self, task_id: str) -> dict:
    del self
    repository = TaskRepository()
    task = repository.get_task_with_steps(task_id)
    if task is None:
        return {"success": False, "error": "task not found", "task_id": task_id}
    request = TaskCreateRequest(
        task_type=str(task.get("task_type") or ""),
        payload=loads_json(task.get("payload_json"), {}),
        user_id=task.get("user_id"),
        project_id=task.get("project_id"),
        conversation_id=task.get("conversation_id"),
        max_attempts=max(1, int(task.get("max_attempts") or 1)),
        parent_task_id=task.get("parent_task_id"),
        trace_id=task.get("trace_id"),
    )
    manager = TaskManager(repository=repository, queue=LocalTaskQueueBackend(repository=repository))
    manager._run_task(task_id, request)
    return {"success": True, "task_id": task_id}
