from __future__ import annotations

from backend.schemas.agent_response import AgentResponse
from backend.tools.csv_tool import CsvTool
from backend.tools.document_tool import DocumentTool
from backend.tools.file_info_tool import FileInfoTool
from backend.tools.web_search_tool import WebSearchTool


class ToolRunner:
    def __init__(self) -> None:
        self.csv_tool = CsvTool()
        self.document_tool = DocumentTool()
        self.file_info_tool = FileInfoTool()
        self.web_search_tool = WebSearchTool()

    def run(self, tool_name: str, normalized_message) -> AgentResponse:
        if tool_name == "csv_tool":
            return self.csv_tool.run(normalized_message.file_path or "", normalized_message.message)
        if tool_name == "document_tool":
            return self.document_tool.run(
                normalized_message.file_path or "",
                normalized_message.message,
                user_id=normalized_message.user_id,
                conversation_id=normalized_message.conversation_id,
            )
        if tool_name == "file_info_tool":
            return self.file_info_tool.run(normalized_message.file_path or "", normalized_message.message)
        if tool_name == "web_search_tool":
            return self.web_search_tool.run(normalized_message.message)
        return AgentResponse(success=False, tool_used=True, tool_name=tool_name, error_message=f"未实现的工具：{tool_name}")
