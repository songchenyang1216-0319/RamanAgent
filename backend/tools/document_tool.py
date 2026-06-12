from __future__ import annotations

from pathlib import Path

from backend.schemas.agent_response import AgentResponse
from backend.services.file_processor import FileProcessorRegistry
from backend.skills.uploaded_package_skill import _extract_prompt_only_file_excerpt


class DocumentTool:
    name = "document_tool"

    def __init__(self) -> None:
        self.file_processors = FileProcessorRegistry()

    def run(
        self,
        file_path: str,
        user_message: str = "",
        *,
        user_id: str = "default_user",
        conversation_id: str = "",
    ) -> AgentResponse:
        relevant_chunks = self.file_processors.search_chunks(
            user_id=user_id,
            conversation_id=conversation_id,
            query=user_message,
            source_path=str(Path(file_path)),
            limit=6,
        )
        if relevant_chunks:
            excerpt = "\n\n".join(
                f"[{chunk.get('filename') or Path(file_path).name}"
                f"{' p.' + str(chunk.get('page')) if chunk.get('page') is not None else ''}"
                f"{' / ' + str(chunk.get('section')) if chunk.get('section') else ''}]\n"
                f"{chunk.get('text') or ''}"
                for chunk in relevant_chunks
            ).strip()
        else:
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
            data={
                "document_excerpt": excerpt,
                "relevant_chunks": relevant_chunks,
                "file_path": file_path,
                "message": user_message,
            },
            source="tool_execution",
        )
