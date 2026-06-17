"""Tool schema definitions for LLM planning.

The dataclass names keep backward compatibility with the first implementation,
while the fields now map more closely to Function Calling / MCP style specs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DANGER_LEVELS = {"safe", "low", "medium", "high", "critical"}
SIDE_EFFECTS = {
    "none",
    "read_file",
    "write_file",
    "network",
    "execute_code",
    "delete_file",
    "modify_project",
    "modify_model",
    "cost_money",
    "long_running",
}


@dataclass(frozen=True)
class ActionSchema:
    action_name: str
    description: str
    display_name: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    required_args: list[str] = field(default_factory=list)
    default_args: dict[str, Any] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)
    requires_file: bool = False
    requires_confirmation: bool = False
    confirmation_message: str = ""
    danger_level: str = "low"
    timeout_seconds: int = 60
    retry_policy: dict[str, Any] = field(default_factory=lambda: {"max_attempts": 1})
    permissions: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=lambda: ["none"])
    visible_to_user: bool = True
    arg_schema: dict[str, Any] = field(default_factory=dict)
    supports_streaming: bool = False
    supports_async_task: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["danger_level"] = self.danger_level if self.danger_level in DANGER_LEVELS else "low"
        payload["side_effects"] = [item if item in SIDE_EFFECTS else "none" for item in self.side_effects]
        payload["input_schema"] = self.input_schema or {"type": "object", "properties": {}}
        payload["output_schema"] = self.output_schema or {"type": "object", "properties": {}}
        payload["arg_schema"] = self.arg_schema or payload["input_schema"]
        return payload


@dataclass(frozen=True)
class ToolSchema:
    tool_name: str
    display_name: str
    description: str
    category: str = "general"
    version: str = "1.0"
    owner: str = "system"
    source: str = "builtin"
    enabled: bool = True
    available: bool = True
    unavailable_reason: str = ""
    danger_level: str = "low"
    requires_auth: bool = False
    requires_file: bool = False
    permissions: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    actions: dict[str, ActionSchema] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)

    def has_action(self, action_name: str) -> bool:
        return str(action_name) in self.actions

    def get_action(self, action_name: str) -> ActionSchema | None:
        return self.actions.get(str(action_name))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = {key: action.to_dict() for key, action in self.actions.items()}
        payload["danger_level"] = self.danger_level if self.danger_level in DANGER_LEVELS else "low"
        payload["input_schema"] = self.input_schema or {"type": "object", "properties": {}}
        payload["output_schema"] = self.output_schema or {"type": "object", "properties": {}}
        return payload


ActionSpec = ActionSchema
ToolSpec = ToolSchema
