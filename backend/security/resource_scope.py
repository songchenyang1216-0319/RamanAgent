from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceScope:
    user_id: str
    is_admin: bool = False
    authenticated: bool = False
    trace_id: str | None = None
    reason: str | None = None

    @classmethod
    def from_auth_context(cls, context: dict, *, trace_id: str | None = None, reason: str | None = None) -> "ResourceScope":
        return cls(
            user_id=str(context.get("user_id") or ""),
            is_admin=bool(context.get("is_admin")),
            authenticated=bool(context.get("authenticated")),
            trace_id=trace_id,
            reason=reason,
        )
