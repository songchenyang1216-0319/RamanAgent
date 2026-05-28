from __future__ import annotations

from backend.schemas.agent_response import AgentResponse
from backend.skills.uploaded_package_skill import _extract_prompt_only_file_excerpt


class DocumentTool:
    name = "document_tool"

    def run(self, file_path: str, user_message: str = "") -> AgentResponse:
        excerpt = _extract_prompt_only_file_excerpt(file_path)
        if not excerpt:
            return AgentResponse(
                success=False,
                tool_used=True,
                tool_name=self.name,
                error_message="未能从文档中提取可读正文内容。",
            )
        reply = f"已读取文档正文片段，下面是可供后续模型处理的内容预览：\n\n{excerpt}"
        return AgentResponse(
            success=True,
            reply=reply,
            tool_used=True,
            tool_name=self.name,
            data={"document_excerpt": excerpt, "file_path": file_path, "message": user_message},
            source="tool_execution",
        )
