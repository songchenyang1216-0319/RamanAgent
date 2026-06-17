from __future__ import annotations

import json
from pathlib import Path

from backend.mcp.mcp_config import load_mcp_config
from backend.mcp.mcp_registry import MCPRegistry


def test_mcp_config_loads_servers_and_marks_runtime_unavailable(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "docs",
                        "transport": "stdio",
                        "command": "python",
                        "args": ["server.py"],
                        "timeout_seconds": 15,
                        "tools": [{"name": "search", "description": "Search docs"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("MCP_RUNTIME_ENABLE", raising=False)
    config = load_mcp_config(config_path)
    assert config.available is True
    assert config.servers[0].transport == "stdio"
    registry = MCPRegistry(config=config)
    status = registry.status()
    assert status["available"] is False
    assert status["servers"][0]["available"] is False
    assert status["tools"][0]["source"] == "mcp"
    assert status["tools"][0]["available"] is False
