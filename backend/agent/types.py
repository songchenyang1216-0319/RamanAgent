from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class NormalizedMessage:
    message: str
    raw_message: str
    conversation_id: str
    session_id: str
    user_id: str
    debug: bool = False
    provider_id: str | None = None
    model_id: str | None = None
    selected_model: dict[str, Any] = field(default_factory=dict)
    enabled_skills: list[str] = field(default_factory=list)
    workspace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    file_path: str | None = None
    file_name: str | None = None
    file_suffix: str | None = None
    file_type: str | None = None
    has_file: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntentResult:
    intent: str
    confidence: float
    reason: str
    recommended_route: str
    candidate_skills: list[str] = field(default_factory=list)
    requires_file: bool = False
    requires_tool: bool = False
    requires_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentPlan:
    route_type: str
    skill_name: str | None = None
    skill_mode: str | None = None
    action_name: str | None = None
    tool_name: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    steps: list[str] = field(default_factory=list)
    need_final_summarization: bool = False
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

