from __future__ import annotations

from backend.agent.intent_router import IntentRouter
from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState


RAMAN_PIPELINE_MARKERS = (
    "sg",
    "savitzky",
    "als",
    "z-score",
    "zscore",
    "z score",
    "预处理",
    "去基线",
    "归一化",
    "峰位",
    "主要峰",
    "标出来",
    "质量",
    "信噪比",
    "不要预测",
    "先不预测",
    "不同预处理",
    "比较",
    "对比",
    "深度学习",
    "去噪",
    "甲醇预测流程",
)


def looks_like_raman_pipeline_request(message: str) -> bool:
    text = str(message or "")
    lowered = text.lower()
    return any(marker in lowered for marker in RAMAN_PIPELINE_MARKERS) or any(marker in text for marker in RAMAN_PIPELINE_MARKERS)


def should_use_legacy_rule(state: GraphState) -> bool:
    normalized = state.normalized_message
    intent = state.intent
    if not normalized or not intent:
        return True
    if looks_like_raman_pipeline_request(normalized.message):
        return False
    if intent.intent in {
        "general_chat",
        "web_search",
        "model_management",
        "skill_management",
        "file_conversion",
        "report_generation",
        "image_understanding",
        "code_analysis",
    } and intent.confidence >= 0.9:
        return True
    if normalized.has_file and intent.intent in {"document_processing", "csv_analysis"} and intent.confidence >= 0.95:
        return True
    if intent.intent in {"conversation_rag", "knowledge_base_rag", "mixed_rag"} and intent.confidence >= 0.9:
        return True
    return False


class IntentNode(GraphNode):
    name = "intent"
    status_text = "正在判断任务类型。"

    def __init__(self, router: IntentRouter | None = None) -> None:
        self.router = router or IntentRouter()

    def run(self, state: GraphState) -> GraphState:
        if state.observations.get("status") == "handled":
            return state
        if not state.normalized_message:
            state.add_error("尚未完成消息标准化。", node=self.name)
            state.should_fallback = True
            state.fallback_reason = "NormalizeNode 未提供 normalized_message。"
            return state
        intent = self.router.route(state.normalized_message)
        state.intent = intent
        state.debug["rule_intent"] = intent.to_dict()
        state.debug["use_legacy_rule"] = should_use_legacy_rule(state)
        return state

    def end_summary(self, state: GraphState) -> str:
        if not state.intent:
            return "任务类型判断完成。"
        return f"规则路由识别为 {state.intent.intent}，置信度 {state.intent.confidence:.2f}。"

    def trace_data(self, state: GraphState) -> dict:
        return state.intent.to_dict() if state.intent else {}
