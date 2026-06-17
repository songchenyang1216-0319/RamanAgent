from __future__ import annotations

from backend.services.rag import RAGService
from backend.tool_runtime.tool_context import ToolContext
from backend.tool_runtime.tool_result import ToolResult


class RAGToolAdapter:
    def execute(self, tool_name: str, action_name: str, args: dict, context: ToolContext) -> ToolResult:
        if action_name not in {"answer", "query"}:
            return ToolResult(False, tool_name, action_name, status="failed", error_code="ACTION_NOT_FOUND", error_message=f"RAG 工具不支持动作：{action_name}")
        payload = RAGService().answer_with_rag(
            str(args.get("query") or args.get("message") or context.metadata.get("message") or ""),
            context.user_id,
            context.conversation_id,
            file_ids=list(args.get("file_ids") or context.file_ids or []),
            knowledge_base_ids=list(args.get("knowledge_base_ids") or context.metadata.get("knowledge_base_ids") or []),
            rag_scope=str(args.get("rag_scope") or context.metadata.get("rag_scope") or "conversation"),
        ).to_dict()
        success = bool(payload.get("success"))
        return ToolResult(
            success=success,
            tool_name=tool_name,
            action_name=action_name,
            status="success" if success else "failed",
            summary=str(payload.get("answer") or payload.get("reply") or payload.get("error_message") or ""),
            data=payload,
            citations=list(payload.get("citations") or []),
            error_code="" if success else "RAG_NO_CONTEXT",
            error_message=str(payload.get("error_message") or ""),
        )
