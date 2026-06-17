from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable


class LocalTaskQueue:
    """Thread-pool backed queue used until Redis/Celery is introduced."""

    def __init__(self, max_workers: int = 3) -> None:
        self.executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
        self._futures: dict[str, Future] = {}
        self._lock = Lock()

    def submit(self, task_id: str, fn: Callable[[], None]) -> Future:
        future = self.executor.submit(fn)
        with self._lock:
            self._futures[task_id] = future
        return future

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            future = self._futures.get(task_id)
        return bool(future.cancel()) if future else False

    def future(self, task_id: str) -> Future | None:
        with self._lock:
            return self._futures.get(task_id)

