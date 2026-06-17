from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    tool_name: str
    action_name: str
    status: str = "success"
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[Any] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    error_code: str = ""
    error_message: str = ""
    warning: str = ""
    elapsed_ms: int = 0
    requires_confirmation: bool = False
    confirmation_payload: dict[str, Any] = field(default_factory=dict)
    audit_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["success"] = bool(self.success)
        if self.success:
            payload["error_message"] = ""
            payload["error_code"] = ""
        return payload

    @classmethod
    def from_agent_response(cls, response, *, tool_name: str, action_name: str, elapsed_ms: int = 0, audit_id: str = "") -> "ToolResult":
        payload = response.to_dict() if hasattr(response, "to_dict") else dict(response or {})
        data = dict(payload.get("data") or {})
        return cls(
            success=bool(payload.get("success")),
            tool_name=tool_name,
            action_name=action_name,
            status="success" if payload.get("success") else "failed",
            summary=str(payload.get("reply") or payload.get("summary") or payload.get("error_message") or ""),
            data=data,
            artifacts=list(payload.get("artifacts") or data.get("artifacts") or []),
            citations=list(data.get("citations") or payload.get("citations") or []),
            error_message=str(payload.get("error_message") or ""),
            elapsed_ms=elapsed_ms,
            audit_id=audit_id,
        )
