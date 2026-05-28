from __future__ import annotations

from backend.schemas.agent_response import AgentResponse
from backend.skills.registry import execute_skill


class WebSearchTool:
    name = "web_search_tool"

    def run(self, query: str) -> AgentResponse:
        result = execute_skill("web-search", action_name="search", query=query)
        raw = dict(result.data or {})
        reply = str(raw.get("summary") or raw.get("markdown") or result.summary or "").strip()
        return AgentResponse(
            success=bool(result.success and reply),
            reply=reply,
            tool_used=True,
            tool_name=self.name,
            data=raw,
            error_message=None if result.success else ("；".join(result.errors) or result.summary or "联网搜索失败。"),
            source="tool_execution",
        )
