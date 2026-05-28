from __future__ import annotations

from backend.schemas.agent_response import AgentResponse
from backend.tools.csv_tool import CsvTool
from backend.tools.document_tool import DocumentTool
from backend.tools.web_search_tool import WebSearchTool


class ToolRunner:
    def __init__(self) -> None:
        self.csv_tool = CsvTool()
        self.document_tool = DocumentTool()
        self.web_search_tool = WebSearchTool()

    def run(self, tool_name: str, normalized_message) -> AgentResponse:
        if tool_name == "csv_tool":
            return self.csv_tool.run(normalized_message.file_path or "", normalized_message.message)
        if tool_name == "document_tool":
            return self.document_tool.run(normalized_message.file_path or "", normalized_message.message)
        if tool_name == "web_search_tool":
            return self.web_search_tool.run(normalized_message.message)
        return AgentResponse(success=False, tool_used=True, tool_name=tool_name, error_message=f"未实现的工具：{tool_name}")

