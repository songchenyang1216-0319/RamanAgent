"""Types used by the enhanced LLM planning layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


PlanType = Literal["model", "tool", "skill", "rag", "raman_pipeline", "hybrid", "fallback"]


@dataclass
class PlanStep:
    step_id: str
    tool_name: str
    action_name: str
    args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMPlan:
    plan_type: str
    intent: str
    confidence: float
    requires_file: bool
    requires_confirmation: bool
    reason: str
    steps: list[PlanStep] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LLMPlan":
        steps = [
            PlanStep(
                step_id=str(item.get("step_id") or f"step_{index + 1:03d}"),
                tool_name=str(item.get("tool_name") or ""),
                action_name=str(item.get("action_name") or ""),
                args=dict(item.get("args") or {}),
            )
            for index, item in enumerate(payload.get("steps") or [])
            if isinstance(item, dict)
        ]
        return cls(
            plan_type=str(payload.get("plan_type") or "fallback"),
            intent=str(payload.get("intent") or "unknown"),
            confidence=float(payload.get("confidence") or 0.0),
            requires_file=bool(payload.get("requires_file", False)),
            requires_confirmation=bool(payload.get("requires_confirmation", False)),
            reason=str(payload.get("reason") or ""),
            steps=steps,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [step.to_dict() for step in self.steps]
        return payload


@dataclass
class PlannerOutput:
    plan: LLMPlan
    raw: str
    source: str = "llm_planner"


@dataclass
class ValidationResult:
    valid: bool
    plan: LLMPlan | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fallback_reason: str = ""
    should_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "plan": self.plan.to_dict() if self.plan else None,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "fallback_reason": self.fallback_reason,
            "should_fallback": bool(self.should_fallback),
        }

