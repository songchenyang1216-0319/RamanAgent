from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class ToolContext:
    user_id: str = "default_user"
    conversation_id: str = ""
    session_id: str = ""
    project_id: str = ""
    workspace_id: str = ""
    file_ids: list[str] = field(default_factory=list)
    active_files: list[dict[str, Any]] = field(default_factory=list)
    request_id: str = field(default_factory=lambda: uuid4().hex)
    task_id: str = ""
    debug: bool = False
    permissions: list[str] = field(default_factory=list)
    source: str = "agent"
    ip_address: str = ""
    user_agent: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_normalized(cls, normalized, **overrides: Any) -> "ToolContext":
        base_metadata = dict(getattr(normalized, "metadata", {}) or {})
        override_metadata = dict(overrides.pop("metadata", {}) or {})
        base_metadata.update(override_metadata)
        return cls(
            user_id=getattr(normalized, "user_id", "default_user") or "default_user",
            conversation_id=getattr(normalized, "conversation_id", "") or "",
            session_id=getattr(normalized, "session_id", "") or "",
            workspace_id=getattr(normalized, "workspace_id", "") or "",
            file_ids=list(getattr(normalized, "file_ids", []) or []),
            active_files=list(getattr(normalized, "files", []) or []),
            debug=bool(getattr(normalized, "debug", False)),
            metadata=base_metadata,
            **overrides,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
