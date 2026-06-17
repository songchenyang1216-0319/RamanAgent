from __future__ import annotations

from pathlib import Path

from backend.agent.planning.tool_catalog import ToolCatalog
from backend.mcp.mcp_client import MCPClient
from backend.mcp.mcp_config import load_mcp_config
from backend.mcp.mcp_tool_adapter import mcp_tool_to_tool_spec


def test_mcp_unavailable_when_config_missing(tmp_path: Path) -> None:
    config = load_mcp_config(tmp_path / "missing.json")
    client = MCPClient(config=config)
    assert client.available is False
    assert client.status()["available"] is False
    assert client.list_tool_specs() == []


def test_mcp_tool_adapter_marks_source() -> None:
    spec = mcp_tool_to_tool_spec({"name": "search", "description": "Search docs"}, server_name="docs")
    assert spec.tool_name == "mcp_docs_search"
    assert spec.owner == "mcp:docs"
    assert spec.get_action("call") is not None
    assert spec.get_action("call").side_effects == ["network"]


def test_tool_catalog_loads_without_mcp_config() -> None:
    catalog = ToolCatalog()
    assert catalog.get("raman_pipeline") is not None
