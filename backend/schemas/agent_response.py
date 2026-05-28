from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AgentResponse:
    success: bool
    reply: str = ""
    intent: str = "unknown"
    route: str = "fallback"
    skill_used: bool = False
    skill_name: str | None = None
    skill_mode: str | None = None
    tool_used: bool = False
    tool_name: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    artifacts: list[Any] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    category: str | None = None
    action_name: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    model_info: dict[str, Any] = field(default_factory=dict)
    llm_model_info: dict[str, Any] = field(default_factory=dict)
    source: str = "orchestrator"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["skill_used"] = bool(self.skill_used)
        payload["tool_used"] = bool(self.tool_used)
        payload["success"] = bool(self.success)
        payload["reply"] = str(self.reply or "")
        payload["error_message"] = self.error_message if not self.success else None
        return payload

