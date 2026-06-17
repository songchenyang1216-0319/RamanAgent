from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.agent.types import AgentPlan, IntentResult, NormalizedMessage
from backend.agent.planning.plan_types import LLMPlan, PlannerOutput, ValidationResult
from backend.agent.runtime.graph_events import GraphTraceEvent


@dataclass
class GraphState:
    request_payload: dict[str, Any]
    normalized_message: NormalizedMessage | None = None
    conversation_id: str = ""
    session_id: str = ""
    user_id: str = "default_user"
    message: str = ""
    files: list[dict[str, Any]] = field(default_factory=list)
    intent: IntentResult | None = None
    plan: LLMPlan | AgentPlan | None = None
    planner_output: PlannerOutput | None = None
    validated_plan: LLMPlan | AgentPlan | None = None
    validation_result: ValidationResult | None = None
    execution_results: Any = None
    observations: dict[str, Any] = field(default_factory=dict)
    repair_attempts: int = 0
    requires_confirmation: bool = False
    confirmation_message: str = ""
    final_response: dict[str, Any] | None = None
    stream_events: list[dict[str, Any]] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)
    elapsed_ms: int = 0
    should_fallback: bool = False
    fallback_reason: str = ""

    @property
    def debug_enabled(self) -> bool:
        return bool(self.normalized_message.debug if self.normalized_message else self.request_payload.get("debug", False))

    def mark_elapsed(self) -> None:
        self.elapsed_ms = int((time.perf_counter() - self.started_at) * 1000)

    def add_error(self, message: str, *, node: str = "", error_type: str = "error", recoverable: bool = False) -> None:
        self.errors.append(
            {
                "node": node,
                "type": error_type,
                "message": message,
                "recoverable": bool(recoverable),
            }
        )

    def add_trace(self, event: GraphTraceEvent) -> None:
        self.debug.setdefault("node_trace", [])
        self.debug["node_trace"].append(event.to_dict())

    def public_debug(self) -> dict[str, Any]:
        if not self.debug_enabled:
            return {}
        payload = dict(self.debug or {})
        payload["errors"] = list(self.errors or [])
        payload["observations"] = dict(self.observations or {})
        return payload

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.normalized_message is not None:
            payload["normalized_message"] = self.normalized_message.to_dict()
        if self.intent is not None:
            payload["intent"] = self.intent.to_dict()
        for key in ("plan", "validated_plan"):
            value = getattr(self, key)
            if hasattr(value, "to_dict"):
                payload[key] = value.to_dict()
        if self.validation_result is not None:
            payload["validation_result"] = self.validation_result.to_dict()
        if self.planner_output is not None:
            payload["planner_output"] = {
                "source": self.planner_output.source,
                "raw": self.planner_output.raw if self.debug_enabled else "",
                "plan": self.planner_output.plan.to_dict(),
            }
        return payload
