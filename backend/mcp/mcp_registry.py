from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .mcp_client import MCPClient
from .mcp_config import MCPConfig, MCPServerConfig, load_mcp_config


@dataclass
class MCPRegistry:
    config: MCPConfig = field(default_factory=load_mcp_config)

    def __post_init__(self) -> None:
        self.client = MCPClient(config=self.config)

    def status(self) -> dict[str, Any]:
        payload = self.client.status()
        payload["servers"] = self.list_servers()
        payload["tools"] = self.list_tools()
        return payload

    def list_servers(self) -> list[dict[str, Any]]:
        return [self._server_payload(server) for server in self.config.servers]

    def list_tools(self) -> list[dict[str, Any]]:
        items = []
        for spec in self.client.list_tool_specs():
            payload = spec.to_dict()
            payload["server_name"] = self._server_name_from_spec(payload)
            items.append(payload)
        return items

    def _server_payload(self, server: MCPServerConfig) -> dict[str, Any]:
        server_available = bool(self.client.available and server.enabled and server.command)
        return {
            "name": server.name,
            "transport": server.transport,
            "enabled": server.enabled,
            "available": server_available,
            "unavailable_reason": "" if server_available else self._server_unavailable_reason(server),
            "command": server.command,
            "args": server.args,
            "timeout_seconds": server.timeout_seconds,
            "tool_count": len(server.tools or []),
        }

    def _server_unavailable_reason(self, server: MCPServerConfig) -> str:
        if not self.config.available:
            return self.config.error_message or "MCP config unavailable."
        if not server.enabled:
            return "MCP server disabled."
        if not server.command:
            return "MCP server command not configured."
        return "MCP server not connected in this runtime stage."

    def _server_name_from_spec(self, payload: dict[str, Any]) -> str:
        for tag in payload.get("tags") or []:
            if tag != "mcp":
                return str(tag)
        return ""
