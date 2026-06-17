from __future__ import annotations

import time
from typing import Callable, TypeVar


T = TypeVar("T")


def run_with_retry(func: Callable[[], T], retry_policy: dict | None = None) -> T:
    policy = dict(retry_policy or {})
    attempts = max(1, int(policy.get("max_attempts") or 1))
    delay = max(0.0, float(policy.get("delay_seconds") or 0))
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1 and delay:
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc
