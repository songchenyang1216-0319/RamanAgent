from __future__ import annotations

import re
from typing import Any

from backend.agent.planning.tool_schema import ActionSchema, ToolSchema


def _safe_name(value: str) -> str:
    text = re.sub(r"[^0-9A-Za-z_]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_").lower()
    return text or "tool"


def mcp_tool_to_tool_spec(tool: dict[str, Any], *, server_name: str = "mcp") -> ToolSchema:
    raw_name = str(tool.get("name") or tool.get("tool_name") or "tool")
    tool_name = f"mcp_{_safe_name(server_name)}_{_safe_name(raw_name)}"
    input_schema = dict(tool.get("input_schema") or tool.get("parameters") or {"type": "object", "properties": {}})
    description = str(tool.get("description") or f"MCP tool from {server_name}: {raw_name}")
    action = ActionSchema(
        action_name="call",
        display_name=raw_name,
        description=description,
        input_schema=input_schema,
        arg_schema=input_schema,
        output_schema=dict(tool.get("output_schema") or {"type": "object"}),
        timeout_seconds=int(tool.get("timeout_seconds") or 60),
        side_effects=list(tool.get("side_effects") or ["network"]),
    )
    return ToolSchema(
        tool_name=tool_name,
        display_name=str(tool.get("display_name") or raw_name),
        description=description,
        category=str(tool.get("category") or "mcp"),
        owner=f"mcp:{server_name}",
        source="mcp",
        enabled=bool(tool.get("enabled", True)),
        available=bool(tool.get("available", True)),
        unavailable_reason=str(tool.get("unavailable_reason") or ""),
        actions={"call": action},
        tags=["mcp", server_name, raw_name],
        input_schema=input_schema,
        output_schema=dict(tool.get("output_schema") or {"type": "object"}),
    )
