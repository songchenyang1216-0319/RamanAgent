from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.api.auth_dependencies import get_request_user_context
from backend.mcp.mcp_registry import MCPRegistry


router = APIRouter(prefix="/api/mcp", tags=["mcp"])


@router.get("/status")
def get_mcp_status(current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    return {"success": True, "mcp": MCPRegistry().status()}


@router.get("/servers")
def list_mcp_servers(current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    servers = MCPRegistry().list_servers()
    return {"success": True, "servers": servers, "total": len(servers)}


@router.get("/tools")
def list_mcp_tools(current_user: dict = Depends(get_request_user_context)) -> dict[str, Any]:
    tools = MCPRegistry().list_tools()
    return {"success": True, "tools": tools, "total": len(tools)}
