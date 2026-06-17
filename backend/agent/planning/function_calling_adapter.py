from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .tool_catalog import ToolCatalog
from .tool_schema import ActionSpec, ToolSpec


@dataclass(frozen=True)
class FunctionToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    provider: str = "generic"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FunctionCallingAdapter:
    """Export RamanAgent ToolSpec/ActionSpec to provider-compatible schemas."""

    @staticmethod
    def function_name(tool: ToolSpec, action: ActionSpec) -> str:
        return f"{tool.tool_name}__{action.action_name}"

    @staticmethod
    def from_function_name(name: str) -> tuple[str, str]:
        if "__" not in str(name):
            return str(name), "call"
        tool_name, action_name = str(name).split("__", 1)
        return tool_name, action_name

    @classmethod
    def to_generic_schema(cls, tool: ToolSpec, action: ActionSpec, *, strict: bool = False) -> dict[str, Any]:
        parameters = cls._parameters_schema(action, strict=strict)
        return {
            "name": cls.function_name(tool, action),
            "description": cls._description(tool, action),
            "parameters": parameters,
            "strict": bool(strict),
            "metadata": {
                "tool_name": tool.tool_name,
                "action_name": action.action_name,
                "category": tool.category,
                "danger_level": action.danger_level or tool.danger_level,
                "requires_file": bool(action.requires_file or tool.requires_file),
                "requires_confirmation": bool(action.requires_confirmation),
            },
        }

    @classmethod
    def to_openai_function(cls, tool: ToolSpec, action: ActionSpec, *, strict: bool = False) -> dict[str, Any]:
        payload = cls.to_generic_schema(tool, action, strict=strict)
        function_payload = {
            "name": payload["name"],
            "description": payload["description"],
            "parameters": payload["parameters"],
        }
        if strict:
            function_payload["strict"] = True
        return {"type": "function", "function": function_payload}

    @classmethod
    def to_qwen_function(cls, tool: ToolSpec, action: ActionSpec, *, strict: bool = False) -> dict[str, Any]:
        payload = cls.to_generic_schema(tool, action, strict=strict)
        return {
            "type": "function",
            "function": {
                "name": payload["name"],
                "description": payload["description"],
                "parameters": payload["parameters"],
            },
            "x-qwen-strict": bool(strict),
            "x-ramanagent": payload["metadata"],
        }

    @classmethod
    def tool_to_openai_functions(cls, tool: ToolSpec, *, strict: bool = False) -> list[dict[str, Any]]:
        return [cls.to_openai_function(tool, action, strict=strict) for action in tool.actions.values() if action.visible_to_user]

    @classmethod
    def tool_to_qwen_functions(cls, tool: ToolSpec, *, strict: bool = False) -> list[dict[str, Any]]:
        return [cls.to_qwen_function(tool, action, strict=strict) for action in tool.actions.values() if action.visible_to_user]

    @classmethod
    def tool_to_generic_functions(cls, tool: ToolSpec, *, strict: bool = False) -> list[dict[str, Any]]:
        return [cls.to_generic_schema(tool, action, strict=strict) for action in tool.actions.values() if action.visible_to_user]

    @classmethod
    def to_openai_tools(cls, catalog: ToolCatalog | dict[str, ToolSpec] | list[ToolSpec], *, strict: bool = False) -> list[dict[str, Any]]:
        return [cls.to_openai_function(tool, action, strict=strict) for tool, action in cls._iter_visible_actions(catalog)]

    @classmethod
    def to_qwen_tools(cls, catalog: ToolCatalog | dict[str, ToolSpec] | list[ToolSpec], *, strict: bool = False) -> list[dict[str, Any]]:
        return [cls.to_qwen_function(tool, action, strict=strict) for tool, action in cls._iter_visible_actions(catalog)]

    @classmethod
    def to_deepseek_tools(cls, catalog: ToolCatalog | dict[str, ToolSpec] | list[ToolSpec], *, strict: bool = False) -> list[dict[str, Any]]:
        return cls.to_openai_tools(catalog, strict=strict)

    @classmethod
    def to_generic_json_schema(cls, catalog: ToolCatalog | dict[str, ToolSpec] | list[ToolSpec], *, strict: bool = False) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tool_calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "arguments": {"type": "object"},
                        },
                        "required": ["name", "arguments"],
                        "additionalProperties": False if strict else True,
                    },
                }
            },
            "required": ["tool_calls"],
            "additionalProperties": False if strict else True,
            "x-ramanagent-tools": cls.tool_catalog_to_generic_functions(catalog, strict=strict),
        }

    @classmethod
    def tool_catalog_to_generic_functions(cls, catalog: ToolCatalog | dict[str, ToolSpec] | list[ToolSpec], *, strict: bool = False) -> list[dict[str, Any]]:
        return [cls.to_generic_schema(tool, action, strict=strict) for tool, action in cls._iter_visible_actions(catalog)]

    @classmethod
    def parse_tool_calls(cls, provider_response: Any, *, provider: str = "generic") -> list[FunctionToolCall]:
        raw_calls = cls._extract_raw_tool_calls(provider_response)
        calls: list[FunctionToolCall] = []
        for index, raw_call in enumerate(raw_calls, start=1):
            call_id = str(raw_call.get("id") or f"call_{index:03d}")
            function_payload = raw_call.get("function") if isinstance(raw_call.get("function"), dict) else raw_call
            name = str(function_payload.get("name") or raw_call.get("name") or "")
            arguments = cls._parse_arguments(function_payload.get("arguments", raw_call.get("arguments", {})))
            calls.append(FunctionToolCall(id=call_id, name=name, arguments=arguments, provider=provider))
        return calls

    @classmethod
    def parallel_tool_calls(cls, calls: list[FunctionToolCall | dict[str, Any]]) -> dict[str, Any]:
        normalized = []
        for index, call in enumerate(calls, start=1):
            if isinstance(call, FunctionToolCall):
                normalized.append(call.to_dict())
            else:
                payload = dict(call or {})
                payload.setdefault("id", f"call_{index:03d}")
                payload.setdefault("provider", "generic")
                payload.setdefault("arguments", {})
                normalized.append(payload)
        return {"parallel": True, "tool_calls": normalized}

    @staticmethod
    def _description(tool: ToolSpec, action: ActionSpec) -> str:
        parts = [tool.display_name or tool.tool_name, action.display_name or action.action_name, action.description or tool.description]
        return " / ".join(str(part) for part in parts if str(part or "").strip())

    @staticmethod
    def _parameters_schema(action: ActionSpec, *, strict: bool) -> dict[str, Any]:
        schema = dict(action.input_schema or action.arg_schema or {"type": "object", "properties": {}})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        required = list(action.required_args or schema.get("required") or [])
        if strict:
            schema["additionalProperties"] = False
        if required:
            schema["required"] = required
        return schema

    @classmethod
    def _iter_visible_actions(cls, catalog: ToolCatalog | dict[str, ToolSpec] | list[ToolSpec]):
        if isinstance(catalog, ToolCatalog):
            tools = list(catalog._tools.values())
        elif isinstance(catalog, dict):
            tools = list(catalog.values())
        else:
            tools = list(catalog or [])
        for tool in tools:
            if not getattr(tool, "enabled", True):
                continue
            for action in tool.actions.values():
                if action.visible_to_user:
                    yield tool, action

    @classmethod
    def _extract_raw_tool_calls(cls, provider_response: Any) -> list[dict[str, Any]]:
        if isinstance(provider_response, list):
            return [dict(item) for item in provider_response if isinstance(item, dict)]
        if not isinstance(provider_response, dict):
            return []
        if isinstance(provider_response.get("tool_calls"), list):
            return [dict(item) for item in provider_response["tool_calls"] if isinstance(item, dict)]
        message = provider_response.get("message") if isinstance(provider_response.get("message"), dict) else {}
        if isinstance(message.get("tool_calls"), list):
            return [dict(item) for item in message["tool_calls"] if isinstance(item, dict)]
        choices = provider_response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            return cls._extract_raw_tool_calls(first.get("message") or first)
        return []

    @staticmethod
    def _parse_arguments(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value or "{}")
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}
