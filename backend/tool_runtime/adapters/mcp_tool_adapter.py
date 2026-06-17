from __future__ import annotations

from backend.mcp import MCPClient
from backend.tool_runtime.tool_context import ToolContext
from backend.tool_runtime.tool_result import ToolResult


class MCPRuntimeToolAdapter:
    def execute(self, tool_name: str, action_name: str, args: dict, context: ToolContext) -> ToolResult:
        client = MCPClient()
        result = client.call_tool(tool_name, args)
        success = bool(result.get("success"))
        return ToolResult(
            success=success,
            tool_name=tool_name,
            action_name=action_name,
            status="success" if success else "failed",
            summary=str(result.get("summary") or result.get("error_message") or ""),
            data=result,
            error_code="" if success else "MCP_SERVER_UNAVAILABLE",
            error_message="" if success else str(result.get("error_message") or "MCP server 当前不可用。"),
        )
