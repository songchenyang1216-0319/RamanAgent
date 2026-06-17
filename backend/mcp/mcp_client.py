from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .mcp_config import MCPConfig, load_mcp_config
from .mcp_tool_adapter import mcp_tool_to_tool_spec


@dataclass
class MCPClient:
    config: MCPConfig = field(default_factory=load_mcp_config)

    @property
    def available(self) -> bool:
        runtime_enabled = str(os.getenv("MCP_RUNTIME_ENABLE", "") or "").lower() in {"1", "true", "yes"}
        return bool(runtime_enabled and self.config.available and any(server.command for server in self.config.enabled_servers()))

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "config_available": self.config.available,
            "config_path": self.config.path,
            "error_message": self.config.error_message,
            "server_count": len(self.config.servers),
            "enabled_server_count": len(self.config.enabled_servers()),
        }

    def list_tool_specs(self) -> list[Any]:
        if not self.config.available:
            return []
        specs = []
        for server in self.config.enabled_servers():
            server_available = self.available and bool(server.command)
            for tool in server.tools:
                payload = dict(tool)
                if not server_available:
                    payload["available"] = False
                    payload["unavailable_reason"] = "MCP runtime connection is unavailable in this stage." if server.command else "MCP server command not configured."
                specs.append(mcp_tool_to_tool_spec(payload, server_name=server.name))
        return specs

    def call_tool(self, tool_name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "success": False,
            "available": self.available,
            "tool_name": tool_name,
            "args": dict(args or {}),
            "error_code": "MCP_SERVER_UNAVAILABLE",
            "error_message": "MCP runtime connection is unavailable in this stage.",
        }
