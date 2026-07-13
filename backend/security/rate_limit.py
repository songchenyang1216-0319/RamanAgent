from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock


def utcnow() -> datetime:
    return datetime.utcnow()


@dataclass
class LoginFailureState:
    count: int = 0
    locked_until: datetime | None = None
    updated_at: datetime | None = None


class InMemoryLoginRateLimiter:
    def __init__(self, *, max_failures: int = 5, lock_seconds: int = 300) -> None:
        self.max_failures = max(1, int(max_failures))
        self.lock_seconds = max(1, int(lock_seconds))
        self._states: dict[str, LoginFailureState] = {}
        self._lock = Lock()

    def _key(self, username: str, ip_hash: str | None) -> str:
        return f"{str(username or '').strip().lower()}::{str(ip_hash or '')}"

    def check_allowed(self, username: str, ip_hash: str | None) -> tuple[bool, int]:
        key = self._key(username, ip_hash)
        now = utcnow()
        with self._lock:
            state = self._states.get(key)
            if not state or not state.locked_until:
                return True, 0
            if state.locked_until <= now:
                self._states.pop(key, None)
                return True, 0
            return False, int((state.locked_until - now).total_seconds())

    def record_failure(self, username: str, ip_hash: str | None) -> None:
        key = self._key(username, ip_hash)
        now = utcnow()
        with self._lock:
            state = self._states.setdefault(key, LoginFailureState())
            state.count += 1
            state.updated_at = now
            if state.count >= self.max_failures:
                state.locked_until = now + timedelta(seconds=self.lock_seconds)

    def record_success(self, username: str, ip_hash: str | None) -> None:
        key = self._key(username, ip_hash)
        with self._lock:
            self._states.pop(key, None)


login_rate_limiter = InMemoryLoginRateLimiter()
