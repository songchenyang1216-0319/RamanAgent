from __future__ import annotations

from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState


class NormalizeNode(GraphNode):
    name = "normalize"
    status_text = "正在整理消息、文件和会话上下文。"

    def __init__(self, normalizer: MessageNormalizer | None = None) -> None:
        self.normalizer = normalizer or MessageNormalizer()

    def run(self, state: GraphState) -> GraphState:
        normalized = self.normalizer.normalize(state.request_payload)
        state.normalized_message = normalized
        state.conversation_id = normalized.conversation_id
        state.session_id = normalized.session_id
        state.user_id = normalized.user_id
        state.message = normalized.message
        state.files = list(normalized.files or [])
        state.debug["normalized_message"] = {
            "has_file": normalized.has_file,
            "file_type": normalized.file_type,
            "file_name": normalized.file_name,
            "file_ids": list(normalized.file_ids or []),
            "knowledge_base_ids": list(normalized.knowledge_base_ids or []),
            "rag_scope": normalized.rag_scope,
        }
        return state

    def end_summary(self, state: GraphState) -> str:
        normalized = state.normalized_message
        if not normalized:
            return "消息整理完成。"
        if normalized.has_file:
            return f"消息整理完成，已识别文件：{normalized.file_name or normalized.file_type or '未命名文件'}。"
        return "消息整理完成。"

    def trace_data(self, state: GraphState) -> dict:
        normalized = state.normalized_message
        if not normalized:
            return {}
        return {
            "conversation_id": normalized.conversation_id,
            "session_id": normalized.session_id,
            "has_file": normalized.has_file,
            "file_type": normalized.file_type,
        }
