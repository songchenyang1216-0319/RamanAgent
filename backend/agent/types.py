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
    files: list[dict[str, Any]] = field(default_factory=list)
    file_ids: list[str] = field(default_factory=list)
    selected_files: list[dict[str, Any]] = field(default_factory=list)
    knowledge_base_ids: list[str] = field(default_factory=list)
    rag_scope: str | None = None

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
    rag_scope: str | None = None
    knowledge_base_ids: list[str] = field(default_factory=list)
    model_provider: str | None = None
    model_name: str | None = None
    steps: list[str] = field(default_factory=list)
    need_final_summarization: bool = False
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentDecision:
    intent: str
    route_type: str
    confidence: float
    reason: str
    selected_skill: str | None = None
    selected_action: str | None = None
    selected_tool: str | None = None
    requires_file: bool = False
    selected_files: list[dict[str, Any]] = field(default_factory=list)
    rag_scope: str | None = None
    knowledge_base_ids: list[str] = field(default_factory=list)
    requires_web: bool = False
    requires_model: bool = False
    user_visible_plan: list[str] = field(default_factory=list)

    @classmethod
    def from_intent_and_plan(cls, intent: IntentResult, plan: AgentPlan, selected_files: list[dict[str, Any]] | None = None) -> "AgentDecision":
        return cls(
            intent=intent.intent,
            route_type=plan.route_type,
            confidence=intent.confidence,
            reason=intent.reason,
            selected_skill=plan.skill_name,
            selected_action=plan.action_name,
            selected_tool=plan.tool_name,
            requires_file=intent.requires_file,
            selected_files=list(selected_files or []),
            rag_scope=plan.rag_scope,
            knowledge_base_ids=list(plan.knowledge_base_ids or []),
            requires_web=intent.intent == "web_search",
            requires_model=bool(intent.requires_llm or plan.route_type in {"model", "hybrid", "rag"}),
            user_visible_plan=list(plan.steps or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
