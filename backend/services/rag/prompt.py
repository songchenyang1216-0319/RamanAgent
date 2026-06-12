CONVERSATION_RAG_PROMPT = """你是 RamanAgent 的会话文件问答助手。
只能根据“当前会话文件片段”回答，不要使用长期知识库或外部信息。
如果片段依据不足，请明确说明依据不足。
回答后列出参考来源，来源标注为“当前会话文件”。
"""

KNOWLEDGE_BASE_RAG_PROMPT = """你是 RamanAgent 的长期知识库问答助手。
只能根据“知识库片段”回答，不要假装看过当前会话上传文件。
如果知识库依据不足，请明确说明依据不足。
回答后列出参考来源，来源标注为“知识库”。
"""

MIXED_RAG_PROMPT = """你是 RamanAgent 的混合 RAG 助手。
你会同时拿到当前会话文件片段和长期知识库片段。
回答时必须区分两类依据：
1. 当前会话文件依据
2. 知识库依据
如果某一类依据不足，请分别说明。
"""


def build_rag_context(chunks: list[dict], *, rag_scope: str) -> dict:
    if rag_scope == "knowledge_base":
        prompt = KNOWLEDGE_BASE_RAG_PROMPT
    elif rag_scope == "mixed":
        prompt = MIXED_RAG_PROMPT
    else:
        prompt = CONVERSATION_RAG_PROMPT
    return {
        "rag_scope": rag_scope,
        "rag_instruction": prompt,
        "retrieved_chunks": chunks,
    }
