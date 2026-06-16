"""Tool schema definitions for LLM planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionSchema:
    action_name: str
    description: str
    requires_file: bool = False
    arg_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolSchema:
    tool_name: str
    display_name: str
    description: str
    actions: dict[str, ActionSchema] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def has_action(self, action_name: str) -> bool:
        return str(action_name) in self.actions

    def get_action(self, action_name: str) -> ActionSchema | None:
        return self.actions.get(str(action_name))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["actions"] = {key: action.to_dict() for key, action in self.actions.items()}
        return payload

