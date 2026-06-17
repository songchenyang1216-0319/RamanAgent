from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: int = 30
    tools: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class MCPConfig:
    servers: list[MCPServerConfig] = field(default_factory=list)
    path: str = ""
    available: bool = False
    error_message: str = ""

    def enabled_servers(self) -> list[MCPServerConfig]:
        return [server for server in self.servers if server.enabled]


def default_mcp_config_path() -> Path:
    raw = str(os.getenv("MCP_CONFIG_PATH") or "").strip()
    if raw:
        return Path(raw)
    return Path("config") / "mcp_servers.json"


def load_mcp_config(path: str | Path | None = None) -> MCPConfig:
    config_path = Path(path) if path else default_mcp_config_path()
    if not config_path.exists() and path is None:
        legacy_path = Path("backend") / "mcp" / "mcp_servers.json"
        if legacy_path.exists():
            config_path = legacy_path
    if not config_path.exists():
        return MCPConfig(path=str(config_path), available=False, error_message="MCP config not found.")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        raw_servers = payload.get("servers") if isinstance(payload, dict) else payload
        servers = []
        for item in raw_servers or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("id") or "").strip()
            if not name:
                continue
            servers.append(
                MCPServerConfig(
                    name=name,
                    transport=str(item.get("transport") or "stdio"),
                    command=str(item.get("command") or ""),
                    args=[str(arg) for arg in item.get("args") or []],
                    env={str(k): str(v) for k, v in dict(item.get("env") or {}).items()},
                    enabled=bool(item.get("enabled", True)),
                    timeout_seconds=int(item.get("timeout_seconds") or 30),
                    tools=[dict(tool) for tool in item.get("tools") or [] if isinstance(tool, dict)],
                )
            )
        return MCPConfig(servers=servers, path=str(config_path), available=True)
    except Exception as exc:
        return MCPConfig(path=str(config_path), available=False, error_message=str(exc))
